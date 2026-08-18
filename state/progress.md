# progress.md — State 子系统（手册 05 章）

> 只追加，禁重写（WRAP UP 铁律）。每段格式：时间 + 做到哪 + 证据 + 未解决。

## 2026-08-18 · 插件初始化

- 项目建立：五子包子包就位（AGENTS/tools/governance/hooks/state）。
- 证据：`python3 deepseek_host.py --self-test` 全绿（README 依赖矩阵含本机工具链实测）。
- 未解决：L2/L4 工具（sparse/coccinelle/qemu/virtme）本机未装；DeepSeek key 未配。

## 2026-08-18 10:10:01
[self-test] 账本写入验证

## 2026-08-18 10:10:30
[self-test] 账本写入验证

## 2026-08-18 10:26:07
[self-test] 账本写入验证

## 2026-08-18 13:27:49
[self-test] 账本写入验证

## 2026-08-18 13:32:05
[self-test] 账本写入验证

## 2026-08-18 13:36:44
[timeout] 12 turns reached —— 交接：按 progress.md 续跑

## 2026-08-18 13:37:38
[done] 收尾汇报：

**1) graph_guard（--base HEAD）：exit 1，REJECT**
- 触发规则 G4："空 diff"——`HEAD` 相对自身无差异，守卫没有看到任何可复核的行为变更。
- 这说明"goto err_clk_disable"修复 diff 很可能已被上一会话 commit 进 HEAD（或落在别处），未提交工作区为空。按指令"不再改代码、不 commit"

## 2026-08-18 13:38:47
[self-test] 账本写入验证

## 2026-08-18 13:39:17
[done] 复核完成：graph_guard（base=HEAD）verdict 为 **PASS**，无任何 findings——工作区那份 `drivers/char/demo.c` 的 `goto err_clk_disable` 修复 diff 通过反 Goodhart 检查（无空 diff、无抑制行、无无关重排）。按指令未改代码、未 commit。

## 2026-08-18 · 智谱 coding plan 真实 e2e（glm-5.3 三轮）

- 冒烟：coding 端点 glm-5.3 thinking:disabled 下对话+function calling 全通（无 reasoning 泄漏）。
- R1（12轮）：正确产出 goto err_clk_disable 修复（+5/-1 契约级）；claim S-E2E 落账；超时交接（终止3）。
- **抓到宿主真 bug**：graph_guard/graph_conflict 的 git 上下文误指插件目录而非 KERNEL_SRC——R1 在验证环节打转的根因。已修（--repo "$KERNEL_SRC"），self-test 回归绿。
- R2（续传）：release 落账完成闭环；agent 面对错误工具输出未谎报完成，如实上报诊断（V 组件语义生效）。
- R3（修后）：graph_guard 真实 PASS 被正确引用，单工具调用自然收尾（终止2）。
- 未解决：R1 若轮数更足能否自主完成全流程未复测；DeepSeek 官方端点未测（智谱已证端点无关性）。

## 2026-08-18 13:40:34
[self-test] 账本写入验证

## 2026-08-18 13:44:57
[self-test] 账本写入验证

## 2026-08-18 13:46:44
[done] 文件 `drivers/char/demo.c` 在当前内核源码树中**不存在**（open 返回 ENOENT）——无法汇报 probe 结构。

根据 progress.md 记录，该文件及其中 `goto err_clk_disable` 修复 diff 是上一会话在 **插件自建工作树**（非 KERNEL_SRC）中操作的产物，当前会话的 KERNEL_SRC 内并无此文件。

## 2026-08-18 13:47:56
[done] **汇报**：`demo_probe` 采用单出口 `goto` 错误处理链——`demo_hw_init` 失败时跳转 `err_clk_disable` 执行 `clk_disable_unprepare(clk)` 清理时钟资源再返回错误码；`clk` 本身由 `devm_clk_get` 管理（自动释放），无需手动 `clk_put`。

## 2026-08-18 13:48:16
[self-test] 账本写入验证

## 2026-08-18 · 主流引擎适配（方言注册表）

- 新增 engines/dialects.py（8引擎注册表：zhipu✅/deepseek/dashscope/moonshot/openai/anthropic/gemini/local）+ engine_probe.py 探针（T1对话+T2工具调用=硬门，T3 thinker可降级）。
- env 链升级：KH_API_KEY/KH_BASE_URL（兼容旧名 DEEPSEEK_*）；KH_ENGINE 显式指定或按 base_url 自动识别。
- 实测：glm-5.3 与 glm-5-Turbo 双模型探针 ALL PASS；Turbo 进六组件循环一次调用直达（读文件+汇报 goto err 结构）。
- **再抓一个真 bug**：read_file/write_file 相对路径按插件 CWD 解析而非 KERNEL_SRC（graph_guard 同族病）→ resolve() 锚定 KERNEL_SRC，已修+回归绿。
- reasoning_content 全引擎统一不回灌：宿主只 append content+tool_calls，协议层天然安全。

## 2026-08-18 13:49:06
[self-test] 账本写入验证

## 2026-08-18 15:41:47
[self-test] 账本写入验证

## 2026-08-18 15:42:46
[cache] hit=3200 miss=3435 rate=48%（前缀稳定=省钱，DeepSeek 计费 hit≈1/10）

## 2026-08-18 15:42:46
[done] `demo_probe` 采用单出口 `goto` 错误处理链：`demo_hw_init` 失败时跳转 `err_clk_disable` 执行 `clk_disable_unprepare(clk)` 清理已使能的时钟后返回错误码；`clk` 本身由 `devm_clk_get` 获取（设备移除时自动释放），无需手动 `clk_put`。

## 2026-08-18 · cache 遥测 + 外部评审吸收

- 实证(智谱 coding 端点)：T4 探针第二次调用 hit=128 miss=29；真实循环 turn1 miss=3236 → turn2 hit=3200 miss=199（98.8% 命中）——前缀缓存自动生效，hit≈1/10 计价。
- 新增 cache_usage() 跨家字段兼容 + run() 逐轮 [usage] 遥测 + 结束落账 + 探针 T4。
- 核实：官方 deepseek-ai/deepseek-harness(dsh) 8-13 真实开源(453K行 TS/Cordis)——我方先前疑为幻觉，已纠正；README 加关系澄清，ROADMAP.md 记外部评审吸收(P0-P4 已做/缺口对照+修订路线)。
