# deepseek-kernel-harness · Linux kernel 开发插件

> **一句话**：把《[harness工程手册](../工程化手册库/harness工程手册/README.md)》的五子系统/六组件骨架，特化到 **DeepSeek 引擎 + Linux kernel 开发** 场景的可插入插件项目。
> **建立**：2026-08-18 · 手册 v1.0 全对应
> **核心命题**（来自手册 02 章 #65-66）：in-loop 检查点治不了 **Goodhart / 向上盲区 / 冲突** 三种结构病——kernel 开发恰是三种病的重灾区，所以本插件的差异点不在 loop 层工具，而在 **[governance/ graph 层治理](#-graph-层治理本插件的差异点)**。

---

## 🧩 是什么 / 不是什么

| | 说明 |
|---|---|
| **是** | 一个**领域插件包**（Instructions + Tools + Scope + State + Graph 治理五个子包）+ 一个 **DeepSeek 宿主**（`deepseek_host.py`，手册 12 章骨架的 kernel 特化版） |
| **不是** | 通用 agent 框架。E/T/C 循环骨架来自手册 12 章，本插件只做"kernel 领域增量"——这正是插件化边界（手册 02 章 Loop 原语之 `skills`） |
| **引擎** | **主流 LLM 通吃**：宿主只说 OpenAI 兼容协议，方言注册表 [`engines/dialects.py`](engines/dialects.py) 覆盖 zhipu✅/deepseek/qwen/kimi/openai/anthropic/gemini/local 八家；`engine_probe.py` 一键探针；换引擎只动 env（`KH_BASE_URL/KH_API_KEY/KH_LOOP_MODEL`） |
| **自检** | `python3 deepseek_host.py --self-test` **零依赖零 key 零内核树**可跑（bash 已验证） |

---

## 📂 目录（五子系统 × kernel 领域映射）

```
deepseek-kernel-harness/
├── README.md               ← 本文件（目录宪法）
├── INTEGRATION.md          ★ 任意 agent 接线指南（opencode/cline/Claude Code 四针脚公式）
├── AGENTS.md               ← Instructions 子系统：内核开发契约（<200 行）
├── plugin.json             ← 插件清单：六组件挂点声明（宿主按此装载）
├── deepseek_host.py        ← 宿主：DeepSeek 端点 + E/T/C/S/L/V 骨架 + 插件装载（路线A）
│                             （agent 在场时退休为 self-test + CI 兜底，见 INTEGRATION §1）
├── config/
│   └── deepseek.yaml       ← 端点/路由/预算（模型方言见手册 09 章）
├── templates/
│   └── opencode.kernel.json ← opencode 接线模板（provider+instructions+permission）
├── tools/                  ← Verification 子系统：kernel 验证金字塔 L1-L4
│   ├── k_check.sh          ← L1 风格：checkpatch.pl --strict
│   ├── k_static.sh         ← L2 静态：sparse(C=2) + coccinelle（缺则报装法）
│   ├── k_build.sh          ← L3 构建：make W=1 增量（objtree 锁定，防并行互踩）
│   ├── k_boot.sh           ← L4 冒烟：virtme/QEMU 启动（缺则报装法）
│   └── k_maintainer.sh     ← LKML：get_maintainer.pl 收件人解析
├── governance/             ← ★ Graph 层治理（本插件差异点）
│   ├── goodhart_guards.py  ← 反 Goodhart：diff 级反 gaming 守卫
│   ├── global_conflicts.py ← 治向上盲区：跨子系统全局冲突检查
│   └── patch_queue.py      ← 治冲突：补丁队列串行化 + 同文件互斥
├── hooks/
│   ├── authorize.py        ← Scope 子系统：白名单 + 危险命令拦截（fail-closed，路线A）
│   └── pre-commit.sample   ★ 治理硬门禁：外部 agent 路线的 VCS 层强制（INTEGRATION §5）
└── state/                  ← State 子系统：进度 + 补丁账本
    ├── progress.md         ← 只追加（手册 05 章铁律）
    └── patch_ledger.jsonl  ← 补丁账本：series 顺序 + 验证证据 + graph 检查记录
```

---

## 🚀 快速开始

```bash
# 0) 自检（不需要 API key / 内核树 / 联网）
python3 deepseek_host.py --self-test

# 0.5) 换引擎？export KH_BASE_URL/KH_API_KEY 后先跑探针（T1对话+T2工具调用=硬门）
python3 engine_probe.py

# 0.6) 用 opencode/cline 等 agent 跑？→ 读 INTEGRATION.md（四针脚接线，五分钟）
#      无 agent runtime（CI/cron）才用下面的宿主直跑：
# 1) 配置端点（DeepSeek，OpenAI 兼容）
export DEEPSEEK_API_KEY=sk-...
export DEEPSEEK_BASE_URL=https://api.deepseek.com   # 默认值，可指向本地 vLLM
export KERNEL_SRC=/path/to/linux                     # 内核树（脚本会自动探测）

# 2) 跑一个真实任务（示例：给某驱动加一个错误处理分支）
python3 deepseek_host.py \
  --task "在 drivers/char/xxx.c 的 probe 失败路径补充 clk_disable_unprepare，补丁需过 L1-L3" \
  --max-turns 30

# 3) 单独用工具层（不启动 agent——CI 里就是这么用的）
tools/k_check.sh   drivers/char/xxx.c
tools/k_build.sh   drivers/char/xxx.c
python3 governance/goodhart_guards.py --base HEAD~1
```

**依赖矩阵**（本机已实测 2026-08-18）：

| 层 | 需要 | 缺失时行为 |
|---|---|---|
| L1 checkpatch | perl + 内核树 | 报缺 `KERNEL_SRC`，退出码 2 |
| L2 sparse/coccinelle | `sparse`/`coccinelle` 包 | 明确报装法（apt 命令），退出码 2 |
| L3 build | gcc + make | 已具备 |
| L4 boot | qemu / virtme | 明确报装法，退出码 2 |
| host | `pip install openai`（仅真实任务需要） | self-test 不需要 |

---

## ★ Graph 层治理（本插件的差异点）

手册 02 章 #65-66 的三种结构病 → kernel 开发的具体形态 → 本插件的治法：

| 结构病 | kernel 开发中的形态 | 治法（governance/） |
|---|---|---|
| **Goodhart**（指标被 gaming） | agent 为消 warning 注释掉代码、加 `// SPDX` 抑制行、空 diff 骗绿 | `goodhart_guards.py`：**不看警告数看 diff 结构**——代码净删除超阈值 / 注释率突增 / checkpatch 抑制注释 / 空 commit → 拒绝并记账 |
| **向上盲区**（局部看不见全局） | 改了 `include/` 头文件只编译了当前驱动；改了 Kconfig 只验单 config | `global_conflicts.py`：头文件改动→全树 grep 引用面 + 至少 2 个 allyesconfig/allmodconfig 抽样重编；Kconfig 改动→config 矩阵抽样 |
| **冲突**（并行分支互踩） | 两个 patch series 改同一文件；objtree 并行 make 互踩 | `patch_queue.py`：账本即队列——同文件互斥锁（file→series 占用表）、`git apply --check` 预检、基线漂移检测（rebase 检查） |

**为什么放 graph 层而不是 loop 层**：这三个检查都需要**跨节点全局视角**（多个 agent 会话/多个补丁/多个子系统的联合状态），单节点 in-loop 检查点原理上看不见——这正是四层栈的判断式（手册 02 章）：需要共享状态与恢复时，loop 必须升格为 graph。

---

## 🔧 六组件对照（Completeness Matrix 自评）

| 组件 | 实现处 | 手册章 |
|---|---|---|
| E 执行循环 | `deepseek_host.py: run()` 三终止条件（自然/轮数/超时+交接摘要） | 03/12 |
| T 工具注册 | `plugin.json` 声明 + host `exec_tool`（schema 校验 + 16K 结果预算 + 报错即导航） | 03/12 |
| C 上下文 | 80% 触发压缩，压缩前 flush 账本；工具结果截断保尾部 | 04 |
| S 状态 | `state/patch_ledger.jsonl`（追加式）+ `progress.md`（只追加） | 05 |
| L 钩子 | `hooks/authorize.py`：fail-closed 白名单 + 危险命令拦截 + 审计行 | 03 |
| V 验证 | `tools/` 金字塔 L1-L4，exit code 即证据；graph 检查不过 = 补丁禁入队列 | 06 |

**判定**：6✓ 生产候选形态（工具链完整度取决于宿主机装了什么，缺失项全部显式暴露而非静默跳过——这本身是 V 组件要求）。

---

## 🗺️ 在 work4ai 知识网中的位置

- 上游理论：[harness工程手册](../工程化手册库/harness工程手册/README.md)（02 五子系统 / 03 六组件 / 06 验证 / 08 多模型 / 12 骨架）
- 姊妹活案例：[harness_rl](../讲透Agent/实战案例-RL领域Agent/harness_rl/DESIGN.md)（v4，bandit 内环 + AHE 外环）——本插件是其"领域插件化"路线的 kernel 实例
- 模型方言：DeepSeek reasoner 的 `reasoning_content` 不回灌上下文（手册 09 章 Preserved Thinking 铁律的 DeepSeek 方言形态）

## 📌 下一步（路线图）

- [ ] 接真实内核树跑一轮 L1-L3 全链路（等有 DeepSeek key + 内核树的环境）
- [ ] L4 virtme 冒烟接 kunit 选择器（按改动 subsystem 选 selftest 集）
- [ ] 进化闭环（手册 11 章）：把 patch_ledger 的 REJECT 原因回流为 guard 规则增量

## 📄 License

[MIT](LICENSE) © 2026 leemiracle

## 🧭 与官方 DeepSeek Harness (dsh) 的关系

官方 [`deepseek-ai/deepseek-harness`](https://github.com/deepseek-ai/deepseek-harness)（2026-08-13 开源）是 TypeScript/Cordis 插件 runtime。**本仓库是独立发展的 Python CLI 级领域插件**（六组件教学骨架），非 Cordis 包格式，不能被 dsh 直接 mount——但 `tools/` 金字塔与 `governance/` 三查的长期路线是包装成 dsh-plugin 进官方生态（详见 [ROADMAP.md](ROADMAP.md)）。

---

**版本**：v0.1（2026-08-18）· 核心隐喻：**loop 层工具是修车的扳手，graph 层治理是车检线——扳手再好，也发现不了两辆车在抢同一条车道。**
