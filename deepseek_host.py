#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deepseek_host.py — 宿主：DeepSeek 引擎 + 六组件骨架 + kernel-dev 插件装载

Agent = Model(DeepSeek) + Harness(六组件, 手册12章骨架) + Plugin(kernel-dev, ./plugin.json)

六组件对照（Completeness Matrix 6✓）:
  E = run() 三终止条件（自然结束/轮数上限/超时交接）
  T = TOOLS + exec_tool（schema 校验 + 结果预算 + 报错即导航）
  C = maybe_compact（80% 触发；压缩前 flush 账本）+ 工具结果截断
  S = Ledger（progress.md 只追加）+ state/patch_ledger.jsonl（governance 共享状态）
  L = hooks/authorize.py（fail-closed + 审计行）
  V = run_verify（exit code 即证据）+ graph 三查门禁

零依赖自检: python3 deepseek_host.py --self-test
真实运行:   python3 deepseek_host.py --task "..." （需 pip install openai + DEEPSEEK_API_KEY）
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from hooks.authorize import authorize  # noqa: E402  L 组件

# ===== C 组件：上下文预算（手册 04 章趋同参数；抄默认后须回归验证）=====
FILE_MAX_LINES, TOOL_RESULT_CAP = 2000, 16_000
COMPACT_TRIGGER, KEEP_RECENT = 0.8, 20_000
WINDOW = 128_000
MAX_TURNS_DEFAULT = 40
VERIFY_TIMEOUT = 300

# ===== 引擎方言（手册 08/09 章）：注册表见 engines/dialects.py，换引擎只动 env =====
from engines.dialects import (api_key, base_url, loop_model, thinker_model,  # noqa: E402
                              resolve_dialect)

# ===== T 组件：插件工具 schema（挂载自 plugin.json mount_points.T）=====
def _tool(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}

TOOLS = [
    _tool("read_file", "读文件（限内核树/插件目录），大文件先看前 2000 行",
          {"path": {"type": "string"}, "offset": {"type": "integer", "default": 1}}, ["path"]),
    _tool("grep_tree", "在 KERNEL_SRC 内 grep -rn（比全树读文件省上下文）",
          {"pattern": {"type": "string"}, "path": {"type": "string", "default": "."},
           "glob": {"type": "string", "default": "*.[ch]"}}, ["pattern"]),
    _tool("run_verify", "跑验证命令。exit code 即完成证据（AGENTS.md：验证不过=没完成）",
          {"cmd": {"type": "string"}}, ["cmd"]),
    _tool("write_file", "写文件（白名单：KERNEL_SRC + state/）。改前先 claim 补丁队列",
          {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    _tool("k_check", "L1 风格: checkpatch --strict（不过不碰 L2）",
          {"target": {"type": "string", "description": "file.c 或 patch.diff"}}, ["target"]),
    _tool("k_static", "L2 静态: sparse C=2 + coccinelle",
          {"target": {"type": "string"}}, ["target"]),
    _tool("k_build", "L3 构建: make W=1 增量（objtree 已 flock，防并行互踩）",
          {"target": {"type": "string"}}, ["target"]),
    _tool("k_boot", "L4 冒烟: virtme/qemu 启动", {}, []),
    _tool("k_maintainer", "LKML 收件人: get_maintainer.pl（收件人不自选）",
          {"target": {"type": "string"}}, ["target"]),
    _tool("graph_guard", "graph 三查①反Goodhart: diff 结构级反 gaming（改完必跑）",
          {"base": {"type": "string", "default": "HEAD~1"}}, []),
    _tool("graph_conflict", "graph 三查②盲区: 影响面分析+补验清单（头文件/Kconfig 改动必跑）",
          {"base": {"type": "string", "default": "HEAD~1"}}, []),
    _tool("patch_queue", "graph 三查③冲突: 补丁队列。action=claim须先过①②。改文件前先查占用",
          {"action": {"type": "string", "enum": ["status", "claim", "release", "precheck"]},
           "series": {"type": "string"}, "files": {"type": "array", "items": {"type": "string"}},
           "patch": {"type": "string"}}, ["action"]),
    _tool("deep_plan", "重量级规划/审查 → 路由到 deepseek-reasoner（手册08章 cascade）。循环内不许用超过2次",
          {"question": {"type": "string"}}, ["question"]),
]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


# ===== S 组件：账本 =====
class Ledger:
    def __init__(self, root=ROOT / "state"):
        self.progress = root / "progress.md"
        self.progress.touch(exist_ok=True)

    def wrap_up(self, note):                       # 只追加（手册 05 章铁律）
        with open(self.progress, "a") as f:
            f.write(f"\n## {time.strftime('%F %T')}\n{note}\n")
        print(f"[ledger] {note[:120]}")


# ===== T 组件：执行（结果预算 + 报错即导航）=====
def _cap(text, cap=TOOL_RESULT_CAP):
    text = text or ""
    if len(text) <= cap:
        return text
    return text[-cap:] + f"\n[...truncated, kept tail {cap}B. 用更窄的 grep/offset 定位]"


def _sh(cmd, timeout=VERIFY_TIMEOUT):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout,
                           cwd=str(ROOT))
        out = (r.stdout or "") + (r.stderr or "")
        return f"exit={r.returncode}\n{_cap(out)}"
    except subprocess.TimeoutExpired:
        return f"exit=124\nTIMEOUT after {timeout}s —— 缩小范围（单文件/单规则）或分层跑"


def exec_tool(name, args):
    ks = os.environ.get("KERNEL_SRC", "")

    def resolve(path):
        """相对路径锚定 KERNEL_SRC（e2e 实测教训：否则按插件 CWD 解析 → 误报 ENOENT）"""
        p = Path(path)
        return p if p.is_absolute() or not ks else (Path(ks) / p)

    if name == "read_file":
        p = resolve(args["path"])
        try:
            lines = p.read_text(errors="replace").splitlines()
        except OSError as e:
            return f"ERROR: {e} —— 路径相对内核树（KERNEL_SRC={ks or '未设'}）再试"
        off = int(args.get("offset", 1))
        sl = lines[off - 1: off - 1 + FILE_MAX_LINES]
        return _cap(f"[{p}:{off}-{off + len(sl) - 1} of {len(lines)}]\n" + "\n".join(sl))
    if name == "grep_tree":
        base = ks or "."
        return _sh(f'grep -rn --include="{args.get("glob", "*.[ch]")}" -e "{args["pattern"]}" '
                   f'{args.get("path", ".")} 2>/dev/null | head -80')
    if name == "run_verify":
        return _sh(args["cmd"])
    if name == "write_file":
        p = resolve(args["path"])
        p.write_text(args["content"])
        return f"wrote {len(args['content'])}B to {p}"
    kmap = {"k_check": ("k_check.sh", ["target"]), "k_static": ("k_static.sh", ["target"]),
            "k_build": ("k_build.sh", ["target"]), "k_boot": ("k_boot.sh", []),
            "k_maintainer": ("k_maintainer.sh", ["target"])}
    if name in kmap:
        sh_name, keys = kmap[name]
        return _sh(f"bash tools/{sh_name} " + " ".join(args.get(k, "") for k in keys))
    if name == "graph_guard":
        repo = ks or "."      # git 上下文必须是内核树（工作区），不是插件目录（e2e 实测教训）
        return _sh(f'python3 governance/goodhart_guards.py --base {args.get("base", "HEAD~1")} '
                   f'--repo "{repo}" --json')
    if name == "graph_conflict":
        repo = ks or "."
        return _sh(f'python3 governance/global_conflicts.py --base {args.get("base", "HEAD~1")} '
                   f'--repo "{repo}" --json')
    if name == "patch_queue":
        a = args["action"]
        if a == "status":
            return _sh("python3 governance/patch_queue.py status")
        if a == "claim":
            return _sh("python3 governance/patch_queue.py claim "
                       f'{args.get("series", "S?")} ' + " ".join(args.get("files", [])))
        if a == "release":
            return _sh(f'python3 governance/patch_queue.py release {args.get("series", "S?")}')
        return _sh(f'python3 governance/patch_queue.py precheck {args.get("patch", "")}')
    if name == "deep_plan":
        return deep_plan(args["question"])
    return "unknown tool"


# ===== 08 章 cascade：reasoner 做 deep_plan（09 章方言：剔除 reasoning_content 回灌）=====
def deep_plan(question):
    try:
        from openai import OpenAI
    except ImportError:
        return "openai 未装（pip install openai）——降级：直接在循环内规划，跳过 reasoner"
    if not api_key():
        return "API key 未配置（KH_API_KEY / DEEPSEEK_API_KEY）——降级：直接在循环内规划"
    client = OpenAI(base_url=base_url(), api_key=api_key())
    sys_p = (Path(ROOT / "AGENTS.md").read_text()[:6000]
             + "\n\n你是规划审查员。给出：改动文件清单/验证层级/风险点。不写代码。")
    d = resolve_dialect()
    try:
        r = client.chat.completions.create(
            model=thinker_model(),
            messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": question}],
            **d["thinker_kwargs"])
        # reasoning_content 只留结论，不回灌循环（Preserved Thinking，全引擎一致：
        # deepseek-reasoner / glm-5.3 / qwen3-thinking 均只取 content）
        return _cap(r.choices[0].message.content or "(thinker 无 content)")
    except Exception as e:
        return f"thinker 失败（{e}）——降级回 loop 模型，不中断"


# ===== C 组件：压缩（触发前 flush 账本）=====
def est_tokens(msgs):
    return sum(len(str(m.get("content", ""))) for m in msgs) // 4


def maybe_compact(messages, ledger):
    if est_tokens(messages) < COMPACT_TRIGGER * WINDOW:
        return messages
    ledger.wrap_up("[auto] pre-compact flush（手册04章：压缩前落盘）")
    head = "\n".join(str(m.get("content", ""))[:400] for m in messages[:4])
    compacted = [{"role": "user",
                  "content": f"[compact] 前情摘要（原文已压缩，详情查 state/progress.md）:\n{head}"}]
    tail_chars, tail = KEEP_RECENT, []
    for m in reversed(messages):            # 从尾往前保最近（tool_call/result 配对靠连续）
        if tail_chars <= 0:
            break
        tail.insert(0, m)
        tail_chars -= len(str(m.get("content", "")))
    return compacted + tail


# ===== E 组件：主循环（三终止条件）=====
def run(task, max_turns=MAX_TURNS_DEFAULT):
    from openai import OpenAI
    url = base_url()
    client = OpenAI(base_url=url, api_key=api_key())
    dialect = resolve_dialect(url)          # 方言注册表：换引擎只动 env（手册 09 章）
    ledger = Ledger()
    agents_md = (ROOT / "AGENTS.md").read_text() if (ROOT / "AGENTS.md").exists() else "You are a kernel dev agent."
    progress_tail = ledger.progress.read_text()[-2000:]
    messages = [{"role": "system", "content": agents_md},
                {"role": "user", "content": f"[断点续传·progress 尾部]\n{progress_tail}\n\n[TASK]\n{task}"}]
    for turn in range(max_turns):                              # 终止1：轮数上限
        messages = maybe_compact(messages, ledger)
        r = client.chat.completions.create(model=loop_model(), messages=messages,
                                           tools=TOOLS, **dialect["loop_kwargs"])
        msg = r.choices[0].message
        if not msg.tool_calls:
            ledger.wrap_up(f"[done] {msg.content[:200]}")     # 终止2：自然结束
            return msg.content
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            ok, why = authorize(tc.function.name, args)       # L 组件：fail-closed
            print(f"[audit] {tc.function.name} -> {'ALLOW' if ok else 'DENY ' + why}")
            result = exec_tool(tc.function.name, args) if ok else f"DENIED: {why}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    ledger.wrap_up(f"[timeout] {max_turns} turns reached —— 交接：按 progress.md 续跑")
    return "TIMEOUT（已交接）"                                  # 终止3：超时可交接


# ===== 零依赖 self-test（不需 key/内核树/openai）=====
def self_test():
    print("== deepseek_host self-test ==")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"  [{'✓' if cond else '✗'}] {name}")

    # 1 插件清单装载
    plugin = json.loads((ROOT / "plugin.json").read_text())
    check("plugin.json 解析 + 治理挂点三件", all(
        Path(ROOT / 'governance', f).exists() for f in
        ['goodhart_guards.py', 'global_conflicts.py', 'patch_queue.py']))
    # 2 工具注册
    check(f"工具注册 {len(TOOLS)} 个（≥12）", len(TOOLS) >= 12 and len(TOOL_NAMES) == len(TOOLS))
    # 3 L 组件 fail-closed
    check("authorize 拦截 mrproper", authorize("run_verify", {"cmd": "make mrproper"})[0] is False)
    check("authorize 拒未知工具", authorize("qq", {})[0] is False)
    # 4 tools/*.sh 语法
    for shf in sorted((ROOT / "tools").glob("*.sh")):
        rc = subprocess.run(f"bash -n {shf}", shell=True).returncode
        check(f"bash -n {shf.name}", rc == 0)
    # 5 governance 三件套各自 self-test
    for py in ["goodhart_guards.py", "global_conflicts.py", "patch_queue.py"]:
        rc = subprocess.run(f"python3 governance/{py} --self-test", shell=True,
                            cwd=str(ROOT), capture_output=True, text=True)
        check(f"{py} --self-test", rc.returncode == 0)
        print("    └ " + rc.stdout.strip().splitlines()[-1])   # 各件套自己的 ALL PASS/FAILED 行
    # 6 账本追加
    led = Ledger()
    n0 = len(led.progress.read_text())
    led.wrap_up("[self-test] 账本写入验证")
    check("progress.md 只追加", len(led.progress.read_text()) > n0)
    # 7 引擎方言注册表（换引擎只动 env 的结构保证）
    from engines.dialects import DIALECTS
    check(f"方言注册表 {len(DIALECTS)} 引擎（每引擎含 loop/thinker kwargs）",
          all("loop_kwargs" in v and "thinker_kwargs" in v for v in DIALECTS.values()))
    # 8 端点状态（信息项，不算失败）
    d = resolve_dialect()
    print(f"  [i] 引擎={d['name']} loop={loop_model()} thinker={thinker_model()} "
          f"tested={'✅' if d['tested'] else '⚠'}")
    print(f"  [i] API key: {'已配置' if api_key() else '未配置（真实任务前 export KH_API_KEY）'}")
    print(f"  [i] KERNEL_SRC: {os.environ.get('KERNEL_SRC', '未配置（工具脚本自动探测）')}")
    print("self-test:", "ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--task")
    ap.add_argument("--max-turns", type=int, default=MAX_TURNS_DEFAULT)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.task:
        ap.error("给 --task 或 --self-test")
        return 2
    if not api_key():
        print("缺 API key（export KH_API_KEY=...，兼容旧名 DEEPSEEK_API_KEY）")
        return 2
    print(run(args.task, args.max_turns))


if __name__ == "__main__":
    sys.exit(main())
