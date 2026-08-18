# INTEGRATION.md · 任意 agent 接线指南

> **一句话**：把 deepseek-kernel-harness 接到 opencode / cline / Claude Code / Cursor 等任意编码 agent 上跑。
> **前提认知**：agent（opencode/cline）自己就是完整六组件 harness（E/T/C/S/L/V 全有）——所以接线的不是"把我们的宿主塞给它们"，而是**把插件层四件资产（契约/工具/账本/治理）挂进 agent 的对应挂点**。
> **建立**：2026-08-18 · 配套 [README](README.md) · 理论依据 [harness工程手册](../工程化手册库/harness工程手册/README.md) 02/03 章

---

## 1. 三层架构：谁宿主、谁引擎、谁插件

```
┌─────────────────────────────────────────────────────────────┐
│ 引擎层  DeepSeek API（deepseek-chat / deepseek-reasoner）      │ ← agent 的 provider 配置接入
├─────────────────────────────────────────────────────────────┤
│ agent 层  opencode / cline / Claude Code / Cursor ...        │ ← 自带完整六组件循环
│           （E 循环 / T 工具注册 / C 上下文 / S 会话 / L 权限）    │
├─────────────────────────────────────────────────────────────┤
│ 插件层  deepseek-kernel-harness（本仓库，与 agent 无关）        │
│           AGENTS.md 契约 + tools/ 金字塔 + governance/ 三查    │
│           + state/ 账本                                       │
└─────────────────────────────────────────────────────────────┘
```

**两条路线，插件层共享**：

| 路线 | 宿主 | 场景 | deepseek_host.py 的角色 |
|---|---|---|---|
| **A 无 agent** | `deepseek_host.py` 自己 | CI / cron / 裸机批处理 | 主角（六组件骨架跑 agent 循环）|
| **B 有 agent** ★ | opencode / cline / ... | 交互式开发 | **退休**为 self-test 工具 + CI 兜底 |

路线 B 下引擎接入由 agent 完成：opencode 用 `/connect`（DeepSeek 是原生 provider）或自定义 provider 块；cline 在 VSCode 设置里选。

---

## 2. 四针脚：任意 agent 的通用接线公式

插件层全部是**普通 CLI + Markdown 契约 + JSONL 账本**（无 SDK、无 runtime 依赖）——这是手册 03 章"代码是最佳 harness 媒介"（可执行/可检视/有状态）的设计红利，所以任何"指令文件 + bash 工具"齐备的 agent 都能接：

| 针脚 | 插件资产 | → 挂进 agent 哪里 | 强制力 |
|---|---|---|---|
| ① 指令针 | `AGENTS.md` | agent 的指令/规则文件 | 进 system 上下文（契约级）|
| ② 工具针 | `tools/*.sh` + `governance/*.py` | agent 的 bash 工具直接调用（普通 CLI）| exit code 即证据（V 级，强）|
| ③ 状态针 | `state/progress.md` + `patch_ledger.jsonl` | AGENTS.md 契约要求 agent 维护 | 契约级（"没记账=没发生"）|
| ④ 权限针 | `hooks/authorize.py` 的 DENY_PATTERNS | **翻译**成 agent 的 permission/审批配置 | 近似（见 §5 降级说明）|

---

## 3. opencode 接线（五分钟）

### 3.1 布局：在内核树里启动 opencode（推荐）

```bash
export KERNEL_SRC=/path/to/linux          # tools/ 自动探测兜底用
export DEEPSEEK_API_KEY=sk-...             # 引擎 key
cd /path/to/linux && opencode               # agent 的 edit 天然落在内核树内
```

### 3.2 引擎接入（二选一）

**方式 1（最简，原生）**：opencode 内 `/connect` → 选 DeepSeek → 贴 key → `/models` 选模型。
**方式 2（可控端点，如本地 vLLM）**：把 [`templates/opencode.kernel.json`](templates/opencode.kernel.json) 中 `provider` 块抄进内核树的 `opencode.json`，改 `baseURL`。

**实测：换任意 OpenAI 兼容引擎只动环境变量**（2026-08-18 智谱 coding plan 实证，三轮 e2e + 双模型探针全通）：

```bash
export KH_API_KEY=<key>                                             # 新名（兼容旧名 DEEPSEEK_API_KEY）
export KH_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4      # 新名（兼容旧名 DEEPSEEK_BASE_URL）
export KH_LOOP_MODEL=glm-5.3 KH_THINKER_MODEL=glm-5.3               # 可选：覆盖注册表默认
# 宿主自动方言：bigmodel → thinking:disabled；dashscope → enable_thinking:false；其余裸调
```

### 引擎矩阵（注册表 `engines/dialects.py`；探针 `engine_probe.py` 一键验证）

| 引擎 | base_url | loop 默认 | 方言要点 | 实测 |
|---|---|---|---|---|
| zhipu | `open.bigmodel.cn/api/coding/paas/v4` | glm-5.3 | loop 强制 `thinking:disabled` | ✅ 三轮 e2e + 5-Turbo 循环 |
| deepseek | `api.deepseek.com` | deepseek-chat | reasoner 不收 thinking 参数 | ⚠ 端点未测（方言已核） |
| dashscope(qwen) | `dashscope.aliyuncs.com/compatible-mode/v1` | qwen3-coder-plus | `enable_thinking` 开关 | ⚠ |
| moonshot(kimi) | `api.moonshot.cn/v1` | kimi-k2 | 原生 OpenAI 风格，无思考开关 | ⚠ |
| openai | `api.openai.com/v1` | gpt-5-mini | 推理靠模型名，无参数 | ⚠ |
| anthropic | `api.anthropic.com/v1` | claude-sonnet-4-5 | 官方 OpenAI 兼容层 | ⚠ |
| gemini | `generativelanguage.googleapis.com/v1beta/openai` | gemini-2.5-flash | 兼容端点 | ⚠ |
| local | `localhost:8000/v1` 等 | 按部署 | vLLM/Ollama/LMStudio；key 填非空 | ⚠ |

接入新引擎三步：`export KH_BASE_URL/KH_API_KEY` → `python3 engine_probe.py`（T1 对话 + T2 工具调用是硬门）→ 不过再往注册表补该家 kwargs。**reasoning_content 全引擎统一不回灌**（宿主只 append content+tool_calls，协议层天然安全）。

### 3.3 插件装载

把 [`templates/opencode.kernel.json`](templates/opencode.kernel.json) 抄到内核树根的 `opencode.json`，做两处替换：

- `<PLUGIN_ROOT>` → 插件绝对路径（`instructions` 数组把 AGENTS.md 注入 system 上下文 = 指令针）
- `permission.bash`：注意**规则按序求值、最后匹配者胜**——宽规则 `"*": "ask"` 在前，allow 居中，deny 垫底（权限针的近似实现）
- `external_directory` 放行插件目录（agent 读插件文档/脚本用）

改完**重启 opencode**（config 不热加载）。装 pre-commit 硬门禁（§5）。

### 3.4 验收（smoke 四步）

```text
1. 插件健康：bash 工具跑 `python3 <PLUGIN_ROOT>/deepseek_host.py --self-test` → ALL PASS
2. 指令针生效：问 agent "复述你的验证纪律与反 Goodhart 红线" → 应能背出金字塔顺序与 G1-G4
3. 工具针生效：让它跑 `bash <PLUGIN_ROOT>/tools/k_check.sh <某文件>` → 返回 exit code 与 checkpatch 输出
4. 治理针生效：让它构造一个"注释掉报警代码"的补丁后 commit → pre-commit 应拒绝（G2）
```

---

## 4. cline 接线

| 针脚 | 做法 |
|---|---|
| ① 指令 | `mkdir .clinerules && cp <PLUGIN_ROOT>/AGENTS.md .clinerules/kernel.md`（VSCode 工作区=内核树）|
| 引擎 | cline 设置 → API Provider 选 **DeepSeek**（原生）或 OpenAI Compatible（`https://api.deepseek.com`）；Act 模式用 chat 系，Plan 模式可配 reasoner |
| ② 工具 | 无需注册——cline 的 execute_terminal/bash 直接调 `tools/*.sh`、`governance/*.py` |
| ④ 权限 | cline 的 Allowed Commands 是 **allowlist**（无 deny-list）→ 建议：execute **不开** auto-approve（每条命令人工批），仅把 `python3 <PLUGIN_ROOT>/governance/*` 等只读命令加白 |
| 环境 | `KERNEL_SRC` 需对 VSCode 进程可见（从终端 `code .` 启动以继承 shell env，或写进 settings 的 terminal.integrated.env）|

其他 agent 一行表（同一公式）：

| agent | 指令文件 | 权限配置 |
|---|---|---|
| Claude Code | `cp AGENTS.md CLAUDE.md` | settings.json `permissions.deny` 数组 |
| Cursor | `.cursor/rules/kernel.md`（抄 AGENTS.md）| rules 里附 deny 清单 |
| Gemini CLI | `GEMINI.md` | `.gemini/settings.json` |

---

## 5. 降级与硬化（诚实说明，最重要的一节）

外部 agent 接线后，两处强制力**降级**，必须知道：

| 组件 | 宿主路线 A（deepseek_host.py）| agent 路线 B（opencode/cline）| 硬化手段 |
|---|---|---|---|
| L 权限门 | `authorize.py` fail-closed，**每个工具调用强制过** | 翻译成 permission glob——**近似**（glob 弱于正则，agent 也可能换姿势绕）| opencode deny 规则 + 敏感目录 external_directory deny |
| governance 三查 | exec_tool 内置工具 + 宿主门禁 | 变成"AGENTS.md 契约 + agent 自觉调用"——**agent 理论上可以不跑 graph_guard** | ★ **pre-commit 硬门禁**（下）+ CI |

**pre-commit 硬门禁**（治理回到强制态的手册正解：挂到"无论谁干活都绕不过的咽喉"——agent 可换，`git commit` 不可绕）：

```bash
cd /path/to/linux
KERNEL_HARNESS_ROOT=/path/to/deepseek-kernel-harness \
  cp $KERNEL_HARNESS_ROOT/hooks/pre-commit.sample .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
# 验证：staged 一个"注释掉报警代码"的改动 → git commit → 应被 G2 拒绝
```

 [`hooks/pre-commit.sample`](hooks/pre-commit.sample) 对 staged diff 跑 `goodhart_guards.py`，fail-closed（找不到插件也拒绝）；正当删除任务走 `git commit --no-verify` 人工留痕绕过。

---

## 6. 故障排查

| 症状 | 原因 | 修法 |
|---|---|---|
| agent 不遵守金字塔顺序 | 指令针没接上 | 确认 `instructions` 路径有效 + 重启 opencode；问它"你的验证纪律"自检 |
| `k_check.sh` 报 KERNEL_SRC not found | env 没传进 agent 进程 | 启动 agent 前 export；cline 从终端启动 VSCode |
| opencode 拒绝启动 | config 字段拼错（硬校验）| 按 §3.3 重抄模板；逃生门 `OPENCODE_DISABLE_PROJECT_CONFIG=1` |
| 工具结果被截断 | 结果预算（防上下文爆炸，设计如此）| 让 agent 用更窄的 grep/offset，别调大预算 |
| agent 直接 `git commit` 绕过治理 | 没装 pre-commit | §5 安装；或 CI 层再跑一遍三查 |
| cline 里 reasoner 输出空 | reasoning_content 方言 | Plan/Act 分模配；reasoner 只做规划不做工具循环（09 章方言表）|

---

## 7. 与手册的对应（教学侧注）

- 路线 B 的"agent=宿主、插件不动" = 手册 02 章 dsh 插件化路线的实证
- pre-commit 硬门禁 = 手册 02 章 #65-66 "三种结构病必须上移到不可绕过的层"的第二次落地（第一次是 governance/ 本身）
- 降级表 = Completeness Matrix 思维：换了宿主要重查六组件谁降级了、怎么补

**版本**：v1.0（2026-08-18）· 配套 v0.1 插件 · 核心口诀：**agent 可换，插件不动；契约进上下文，治理挂咽喉。**
