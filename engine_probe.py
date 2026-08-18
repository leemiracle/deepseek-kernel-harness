#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine_probe.py — 引擎探针：任何配置好的引擎一键冒烟（chat + 工具调用 + 方言报告）

用法:
  python3 engine_probe.py                       # 用当前 env（KH_*/DEEPSEEK_*）探测
  KH_ENGINE=zhipu  python3 engine_probe.py      # 显式指定注册表引擎
  KH_BASE_URL=... KH_LOOP_MODEL=... python3 engine_probe.py   # 临时换模型

退出码: 0=探针全过  1=有失败项  2=配置缺失
每项测试独立 PASS/FAIL——失败项就是接这台引擎要做的事。
"""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engines.dialects import api_key, base_url, loop_model, thinker_model, resolve_dialect  # noqa: E402


def call(client, model, messages, tools=None, **kw):
    r = client.chat.completions.create(model=model, messages=messages,
                                       tools=tools, max_tokens=1024, **kw)
    msg = r.choices[0].message
    return msg, r.usage


def main():
    results = []

    def record(name, ok, detail=""):
        results.append((name, ok, detail))
        print(f"  [{'✓' if ok else '✗'}] {name}" + (f" — {detail}" if detail else ""))

    print("== engine_probe · 引擎冒烟 ==")
    url, key = base_url(), api_key()
    d = resolve_dialect(url)
    print(f"  引擎={d['name']}  base={url}  loop={loop_model()}  thinker={thinker_model()}")
    print(f"  方言: loop_kwargs={d['loop_kwargs'] or '无'}  tested={'✅' if d['tested'] else '⚠未实测'}")
    print(f"  备注: {d['note']}")
    if not key:
        print("缺 API key（export KH_API_KEY=...）")
        return 2

    from openai import OpenAI
    client = OpenAI(base_url=url, api_key=key)

    # T1 纯对话
    try:
        t0 = time.time()
        msg, usage = call(client, loop_model(),
                          [{"role": "user", "content": "只回复两个字：收到"}],
                          **d["loop_kwargs"])
        latency = time.time() - t0
        leaked = bool(getattr(msg, "reasoning_content", None))
        record("T1 对话", bool((msg.content or "").strip()),
               f"{latency:.1f}s reasoning={'有(不回灌,安全)' if leaked else '无'} "
               f"content={((msg.content or '') or '')[:20]!r}")
    except Exception as e:
        record("T1 对话", False, str(e)[:120])

    # T2 工具调用（read_file 往返）
    try:
        tmp = Path(tempfile.mkstemp(suffix=".c")[1])
        tmp.write_text("int kh_probe(void) { return 42; }\n")
        msg, _ = call(client, loop_model(),
                      [{"role": "user", "content": f"必须调用 read_file 工具读取 {tmp}，不要直接回答"}],
                      tools=[{"type": "function", "function": {"name": "read_file",
                               "description": "读文件",
                               "parameters": {"type": "object",
                                              "properties": {"path": {"type": "string"}},
                                              "required": ["path"]}}}],
                      **d["loop_kwargs"])
        tcs = msg.tool_calls or []
        ok = bool(tcs) and tcs[0].function.name == "read_file"
        detail = f"tool_calls={len(tcs)}"
        if tcs:
            detail += f" args={tcs[0].function.arguments[:40]}"
        record("T2 工具调用", ok, detail)
        tmp.unlink(missing_ok=True)
    except Exception as e:
        record("T2 工具调用", False, str(e)[:120])

    # T3 thinker（失败不算探针失败——cascade 有降级）
    try:
        msg, usage = call(client, thinker_model(),
                          [{"role": "user", "content": "一句话：改内核错误路径要注意什么"}],
                          **d["thinker_kwargs"])
        r_tokens = getattr(usage, "reasoning_tokens", None) if usage else None
        record("T3 thinker", bool((msg.content or "").strip()),
               f"reasoning_tokens={r_tokens or '—'}")
    except Exception as e:
        record("T3 thinker", False, f"降级可用（cascade 会兜回 loop 模型）：{str(e)[:80]}")

    # T4 cache（同前缀连打两次，看第二次命中；信息项——端点不透出字段则报 N/A）
    try:
        from deepseek_host import cache_usage
        static_sys = "你是 Linux 内核补丁工程师。风格即协议：错误路径用 goto 单出口 unwind。" \
                     "不改无关行。验证金字塔 L1-L4 逐层升。" * 4   # ~200 token 稳定前缀
        cache_msgs = [{"role": "system", "content": static_sys},
                      {"role": "user", "content": "只回复：OK"}]
        call(client, loop_model(), cache_msgs, **d["loop_kwargs"])           # 第一次（预热缓存）
        _, usage2 = call(client, loop_model(), cache_msgs, **d["loop_kwargs"])  # 第二次（应命中）
        c = cache_usage(usage2)
        if c:
            record("T4 cache 字段", True, f"第二次调用 hit={c[0]} miss={c[1]} "
                   f"(hit≈1/10 计费——命中即省钱)")
        else:
            record("T4 cache 字段", True, "端点不透出 cache 字段（N/A）——"
                   "布局仍按静态前缀排，DeepSeek 官方端点可计量")
    except Exception as e:
        record("T4 cache 字段", True, f"探针异常（信息项）：{str(e)[:60]}")

    n_fail = sum(1 for _, ok, _ in results[:2] if not ok)   # T1/T2 硬门；T3/T4 信息项
    print(f"probe: {'ALL PASS' if n_fail == 0 else 'FAILED'}（T1/T2 为硬门，T3/T4 信息项）")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
