# x-kernel 已实现功能审计 · 问题清单（从 Linux kernel 文档视角）

> 生成：2026-08-20 · 方法：x-kernel 12 个近期 commit（!620-!646 + 2 直提交）× 子系统结构 × **Linux kernel 对应文档语义对照**
> 性质：**审查假设清单**——每条是"从 Linux 语义看值得核查的点"，不是已证实的 bug。核查命令用本插件 tools/ 金字塔。
> 证据锚点：commit hash + 文件路径（实测自本地仓库）；Linux 文档引用为 Documentation/ 路径。

---

## 一、功能盘点（12 commit → 8 个功能域）

| 功能域 | x-kernel 实现（commit 证据） | Linux 对应文档锚点 |
|---|---|---|
| **ext4 xattr 迁移** | !624 extra isize xattr migration + external xattr hash 编码 + expansion fallback（fs/filesystems/kext4/src/extent/mutate.rs, superblock.rs）| Documentation/filesystems/ext4/inodes.rst（i_extra_isize 扩容）、attributes.rst |
| **调度器抢占** | !637 ns-slice oneshot timer 驱动抢占 + WF_SYNC 重试 + hrtick 语义（task/ktask, drivers/timer/arm_generic.rs）| Documentation/scheduler/sched-design-CFS.rst §hrtick、sched-arch.rst |
| **SMP 唤醒排队** | !637 defer SMP wake enqueue until switch-out completes（task/ktask/src/task.rs, api.rs）| kernel/sched/core.c wakeup path；Documentation/memory-barriers.txt（队列写-读序） |
| **有序关机** | !620 orderly shutdown lifecycle：process 资源先释放再发布 exit（process/, io/kfd）| Documentation/driver-api/driver-model/device-shutdown.rst |
| **VMM (kvmm)** | !603 Linux smp=1 启动 on rv64/arm64：vGIC PPI、stage2、H-ext 初始化、TCG 运行（virt/kvmm/src/{vm,vcpu}.rs, arch/）| Documentation/virt/kvm/arm/{vgic,mmio}.rst、riscv aia/h-extension |
| **网络 Router** | !640 IPv4 地址所有权移入 Router（net/knet/src/lib.rs, device/ethernet.rs）| Documentation/networking/routing semantics（addr ownership ifa→net namespace）|
| **TIPC 可中断等待** | !645 TIPC 阻塞等待可被致命信号打断（tee/tipc/src/channel.rs）| kernel 中 fatal_signal_pending() 惯例；Documentation/signals |
| **vfs 生命周期** | !634 superblock/inode 初始化对齐 + hashed inode ownership + sleepable teardown（fs/kvfs）| Documentation/filesystems/vfs.rst（evict_inode/iget 语义）、locking.rst |

---

## 二、问题假设清单（按风险排序）

### P1 · 调度器：ns-slice oneshot timer 的重编程竞态（!637）

Linux CFS 的 hrtick 有一条铁律（kernel/sched/core.c `hrtick_start_fair` 注释）：**timer 重编程与 enqueue/dequeue 必须在同一 rq lock 下决策**，否则出现"timer 按旧 slice 到期 → 抢占了一个刚被重排的任务"。

x-kernel 把抢占从周期 tick 改为 ns-slice oneshot（!637），核查点：
- [ ] oneshot 重编程时是否持有 runqueue 锁？（`grep_tree "oneshot\|reprogram"` task/ drivers/timer）
- [ ] WF_SYNC 重试路径（commit 自述 "run check_preempt_tick on due hrtick so WF_SYNC can retry"）——Linux 的 WF_SYNC 依赖**唤醒者让出 CPU 的机会窗口**，oneshot 到期时窗口是否还存在？
- **验证**：`make unittest UNITTEST_CRATE=ktask` + 手工构造"唤醒者持锁时 timer 到期"用例。

### P2 · 调度器：defer wake enqueue 的顺序性（!637）

"defer SMP wake enqueue until switch-out completes"——跨 CPU 的队列写入与 switch-out 之间需要**释放-获取序**（Documentation/memory-barriers.txt 的 release/acquire 配对）。若只有编译器屏障，弱序架构（arm64/riscv64 都是 x-kernel 目标）上 remote CPU 可能先看到"任务已在队列"而 switch-out 尚未提交现场。
- [ ] 找 enqueue 点与 switch-out 点之间的屏障对（`grep_tree "fence\|release\|acquire"` task/ktask）
- **验证**：`make unittest UNITTEST_CRATE=ktask,ksync` + kvmm smp=1 长跑（!603 已能跑 Linux guest——本身就是好的压力源）。

### P3 · ext4：extra_isize 扩容的回退语义（!624）

Linux ext4 扩 i_extra_isize 的路径（fs/ext4/inode.c `ext4_expand_extra_isize`）有个易错点：**扩容失败时必须回退到旧值且不留下半迁移的 xattr**；且 expansion 与 xattr 写入的顺序有讲究（先腾空间再挪，中途崩溃要能被 e2fsck 修复）。
- [ ] kext4 的 expansion fallback（commit 自述有 fallback）失败路径是否保证 inode 一致性？
- [ ] external xattr hash 编码（"encode ext4 external xattr hashes"）与 on-disk 格式的兼容：hash 算的是 name 还是 name+value？（Linux: `ext4_xattr_hash_entry` 只 hash name）
- **验证**：`make unittest UNITTEST_CRATE=kext4` + 写一个"扩容中途模拟崩溃→重挂载"的回归用例（e2fsck 交叉验证）。

### P4 · VMM：vGIC PPI 的 CPU 亲和（!603）

KVM 文档（Documentation/virt/kvm/arm/vgic-v3.rst）明确：**PPI 是 per-CPU 的**，vGIC 的 PPI 状态必须按 vCPU 隔离。commit "fix VGIC PPI handling" 暗示踩过这个坑；smp=1 下单 vCPU 掩盖了多 vCPU 的亲和问题（同一 commit 也含 "support multiple vCPUs"）。
- [ ] 多 vCPU 下 PPI 注入的目标 vCPU 选择逻辑（virt/kvmm/src/vcpu.rs + arch）
- [ ] RISC-V H-extension "initialize on vCPU entry"（commit 自述）——每次 entry 重复初始化 vs 只初始化一次的开销/幂等性
- **验证**：`make run` + guest 内 `cat /proc/interrupts` 观察 PPI 分布；kvmm selftest（virt/kvmm/src/selftest.rs）。

### P5 · 有序关机：资源释放与 exit 发布的序（!620）

Linux 的设备关机模型（device-shutdown.rst）核心是**自顶向下、先子后父**；进程退出（kernel/exit.c do_exit）的顺序铁律：**先释放资源（fd/内存/锁），最后才发布 exit 状态给 wait 者**——反过来就是 use-after-free 窗口（父进程 wait 到 exit 后立即读子进程的资源）。
- commit 自述 "release process-owned resources before publishing exit"——方向对，核查点：
- [ ] kfd 的 final close after flush failure 用例（commit 含 test）是否覆盖"flush 失败 + 并发 wait"组合
- **验证**：`make unittest UNITTEST_CRATE=kprocess,kfd`。

### P6 · TIPC：致命信号打断的粒度（!645）

Linux 惯例是**两类检查点**：睡眠前 `fatal_signal_pending()` 快速路径 + 等待队列的 `signal_wake_up`。只做其一要么打不断（没检查）要么打断太狠（普通信号也打断）。
- [ ] tipc channel 等待是否区分 fatal 与普通信号（tee/tipc/src/channel.rs）
- **验证**：`make unittest UNITTEST_CRATE=tipc` 或构造 guest 用例（kill -9 挂起的 TIPC 操作）。

### P7 · kvfs：hashed inode 的身份保留（!634）

"retain superblock inode key identity / align hashed inode ownership semantics"——VFS 文档（vfs.rst）的语义：**inode 身份 = (sb, ino) 二元组**，任何缓存/复活路径不得制造第二个实例。sleepable teardown context（commit 含 docs）意味着 evict 可能睡眠——与 lookup 的竞态窗口要靠锁或引用计数关闭。
- [ ] `iget` 类路径对"正在 evict 的同号 inode"的处理（fs/kvfs）
- **验证**：`make unittest UNITTEST_CRATE=kvfs` + 并发 open/unlink 压力用例。

### P8 · 工程面：fmt 债务与 clippy 逃逸（808a9fd）

直提交 808a9fd 自述：**35 文件 ±330 行 fmt 债 + `SKIP_CLIPPY=1` 豁免通道**——这是本插件 governance 三病的活案例：
- Goodhart：SKIP_CLIPPY=1 是合法豁免通道，若被常态化使用 = G5（cfg 包裹躲检查）同款病。**核查其使用频率**：`git log --grep=SKIP_CLIPPY | wc -l`
- 根因（commit 自述）：全 workspace clippy 需要 Kconfig/.config——**验证金字塔对配置有前置依赖却没把"配置就绪检查"放进 L2 前置步**，这是金字塔的盲区补验缺口（对应手册 03 章 allmodconfig 同构问题）
- **修法建议**：L2 前加 `make defconfig` 就绪探针，让 clippy 可跑而不是可逃。

### P9 · 错误码映射的边界（a1f3f23）

KeyExpired→EKEYEXPIRED 单点映射——Linux 的 errno 语义是 API 合同（man 3 errno）。核查 kerrno 的映射表是否有**一对多/多对一歧义**（同 Rust 错误在不同 syscall 语境映射不同 errno，如 EAGAIN/EWOULDBLOCK）。
- **验证**：`grep_tree "LinuxError" api/ | head` 人工过一遍映射表。

---

## 三、审计工具用法（把清单变可执行）

```bash
# 全仓扫描：crate 清单 + design/security 文档覆盖率 + TODO/FIXME/unsafe 密度
python3 knowledge/audit_kernel_features.py /data/usershare/ai/x-kernel

# 单点核查（P1 例）：
python3 deepseek_host.py --task "审计 task/ktask 中 oneshot timer 重编程是否持 runqueue 锁：\
grep oneshot/reprogram 调用点，对照锁持有范围输出证据（file:line），给出 P1 结论"
```

## 四、清单之外的持续审计入口

1. **每个新 merge commit** → 跑 `knowledge/audit_kernel_features.py --since <hash>` 提取变更域 → 对照本表 Linux 文档锚点新增假设
2. **ci/Gitee PR 评论链**（!638 建立的失败用例链接）= 现成的回归问题源
3. Linux 侧文档更新（kernel.org Documentation/ diff）→ 反向检查 x-kernel 对齐漂移

---

## 五、全仓扫描实测（2026-08-20，audit_kernel_features.py 首轮）

| 指标 | 数值 | 解读 |
|---|---|---|
| crate 总数 | **151** | workspace 级规模 |
| 总 LOC | **707,199** | — |
| docs/design.md 覆盖 | **58/151（38%）** | AGENTS.md 要求文档同步义务——**覆盖率本身就是 P10 级问题**：93 个 crate 的设计意图只存在于代码里 |
| docs/security.md 覆盖 | 57/151（38%）| 同上 |

风险指数 Top（每千行 TODO×3+unwrap×2+无SAFETY的unsafe）：
- **io/kio：85.9**（6,354 行内 270 个 unwrap——内核 I/O 路径 unwrap 密集 = panic 面）
- **xtask/xconfig 75.5 / xtask 50.4**（构建工具，panic 可容忍度高，可豁免档）
- **task/ksched：57.9**——调度器本体 99 unwrap，**P11：调度热路径的 panic 语义需专项审查**（Linux 对应纪律：内核态非 panic 即 BUG_ON 慎用）
- **mm/alloc-engine：50.3，SAFETY 缺口 19**——内存分配器是全仓 unsafe 密度最高处，**P12：alloc-engine 的 unsafe invariant 文档化优先级最高**
- kext4 1,072 unwrap（41K 行）：配合 P3 的扩容回退语义一并审

**新问题条目**：P10 文档覆盖缺口 / P11 调度器 unwrap 密度 / P12 alloc-engine SAFETY 缺口（更新本清单时并入编号）。
