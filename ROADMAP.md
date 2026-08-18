# ROADMAP.md · 演进路线（外部评审吸收版）

> **来源**：2026-08-18 三份外部 AI 评审（P0-P4 扩展建议 + cache 优化方案）→ 逐条核实 → 已做/缺口对照。
> **原则**：吸收前先验证——外部建议中 "dsh = DeepSeek 官方 Cordis 框架" 经 websearch 证实为真（我方一度误判为幻觉，纠正）。

---

## 一、命名空间事实（必须知道）

**官方 `deepseek-ai/deepseek-harness`（dsh）2026-08-13 开源**（早我方 5 天）：
- 453K 行 TypeScript / 219 包，MIT，基于 Cordis 插件内核（Koishi 作者 shigma 的元框架 v4 fork）
- "Everything is a Plugin"：model adapter / tool registry / agent loop / UI 全部可挂载
- 默认模型目录 `deepseek-v4-flash/pro`，1M context window / 256K output
- 官方呼吁插件仓库打 `dsh-plugin` topic 进生态发现

**本仓库与它的关系**（诚实声明）：
- 本仓库是**独立发展的 Python CLI 级插件**（六组件教学骨架 + 领域金字塔 + graph 治理），**不是 Cordis 包格式**（无 `apply(ctx)`），dsh 不能直接 mount
- 我方 `dsh` topic 让仓库出现在生态搜索——是机会也需澄清，避免被误认为官方组件
- **长期路线**：把 `tools/` 金字塔 + `governance/` 三查包装成真正的 dsh-plugin（npm 包），宿主骨架则被 dsh 替代——CLI 层资产全部保值

---

## 二、外部 P0-P4 建议对照（已做 vs 真缺口）

| 外部建议 | 优先级 | 现状 | 判定 |
|---|---|---|---|
| 结构化错误解析器（日志→JSON） | P0 | 部分：`_cap` 截断保尾部 + "报错即导航"；无 schema 化解析 | **真缺口 P0** |
| 自动修复闭环 | P0 | **已具备**：`run()` 循环本身就是 generate→verify→fix；AGENTS.md 规定"修第一个错重跑" | 无需独立 Repair Agent（单循环足够；多 agent 是规模化后话） |
| 增量验证 | P1 | 部分：`k_build M=<子系统>` 增量 + 外置 objtree 保基线 + flock 防互踩 | 测试选择（diff→关联 kselftest）未做，P2 |
| MCP Server 封装 | P2 | 未做；当前四针脚 CLI 接线（opencode/cline 经 bash）可用 | **真缺口 P2**（比 dsh-plugin 轻，先做这个） |
| 多语言插件化 | P3 | **架构已证**：rust 版 = 宿主/engines 零改动复用；新语言 = 写 tools/ + AGENTS.md | 低成本按需扩（python/go/ts） |
| 安全合规层 | P3 | 部分：rust 版 audit/miri 在金字塔；kernel 版 coccinelle 在 L2 | gitleaks/许可证扫描未做，P3 |
| 多 Agent 协作 | P4 | 部分：cascade 雏形（chat 循环 + reasoner 规划 = `deep_plan`） | sub-agent 委派（代码侦察只回结论）未做——**省 token 最大缺失**，P1 |
| 错误模式记忆 | P4 | 部分：patch_ledger 记 REJECT 原因（governance 侧） | 生成侧预警（"你上次在这犯过"）未做，P4 |

---

## 三、Cache 优化（本轮已实施，2026-08-18）

**已做**：
1. `cache_usage()` 跨家字段读取（DeepSeek `prompt_cache_hit_tokens` / OpenAI `prompt_tokens_details.cached_tokens` / 不透出则静默 N/A）
2. `run()` 逐轮 `[usage]` 遥测 + 会话结束 hit/miss/rate 落账本
3. `engine_probe.py` T4 探针：同前缀连打两次测命中
4. 布局审计：system(静态 AGENTS.md) 恒在最前、动态只追加尾部——**结构性已合规**；`maybe_compact` 触发会打断前缀（压缩固有代价，已注释说明）

**实证数据**（智谱 coding 端点，glm-5-Turbo 真实任务）：

```
turn=1 cache hit=0    miss=3236   ← 冷启动全 miss（AGENTS.md+tools schema+task）
turn=2 cache hit=3200 miss=199    ← 98.8% 命中，仅新增工具结果计 miss
```

**含义**：多轮循环下前缀缓存自动生效（智谱/DeepSeek 均磁盘缓存，hit≈1/10 计价）——AGENTS.md(539t)+工具 schema 每轮重发但**几乎不花钱**。未来优化方向：错误日志语义压缩（减 miss 侧）、子代理隔离重上下文（减母会话轮次）。

---

## 四、修订后的优先级（本仓实际路线）

| 序 | 事项 | 理由 |
|---|---|---|
| 1 | **sub-agent 委派**（代码侦察→10 行结论回传） | 省 token 最大杠杆（轮次×历史） |
| 2 | **结构化错误解析器**（checkpatch/rustc 日志→JSON） | 外部 P0 中唯一真缺口；错误定位精度决定修复轮次 |
| 3 | **MCP Server 封装** | 让任意 Agent 原生调用金字塔（四针脚的协议化升级） |
| 4 | dsh-plugin 化（Cordis 包装） | 蹭官方生态发现；等 dsh API 稳定（现在 rc 期，官方警告会 breaking） |
| 5 | 测试选择 / gitleaks / 错误预警记忆 | 按 value/effort 排 |

---

**版本**：v1.0（2026-08-18）· 备注：外部评审的价值浓缩公式 = **已做确认 + 缺口排序 + 一个被证伪的怀疑**。
