# Linux Kernel 文档地图 · x-kernel 审查入口

> 用途：`xkernel_feature_audit.md` 的 P1-P9 假设各锚定一份 Linux 文档；本表是"从功能域 → 文档语义 → x-kernel 对应 crate"的查询表。
> 原则（手册 04 章）：**这里只放"去哪查 + 查什么"，不抄文档**。

## 子系统对照表

| 功能域 | Linux 文档（Documentation/ 路径） | 核心语义（审查时问的问题） | x-kernel crate |
|---|---|---|---|
| CFS/调度 | `scheduler/sched-design-CFS.rst`、`scheduler/sched-arch.rst` | hrtick 重编程与 rq 锁的配对；WF_SYNC 窗口语义；enqueue/dequeue 与 timer 的序 | task/ktask、task/ksched |
| 实时/定时器 | `timer/hrtimers.rst`、`core-api/timekeeping.rst` | oneshot 重编程的 CPU 迁移；到期与回调的锁上下文 | drivers/timer |
| ext4 | `filesystems/ext4/{inodes,attributes,journal}.rst` | i_extra_isize 扩容回退；xattr hash 只算 name；崩溃一致性 | fs/filesystems/kext4 |
| VFS | `filesystems/vfs.rst`、`filesystems/locking.rst` | inode 身份=(sb,ino)；evict 可睡眠与 lookup 竞态 | fs/kvfs |
| 关机 | `driver-api/driver-model/device-shutdown.rst` | 自顶向下先子后父；进程先释放后发布 exit | process/、io/kfd |
| KVM/mm | `virt/kvm/{arm/vgic-v3,mmio}.rst`、powerpc/api | PPI per-CPU；stage2 属性；mmio 路由注册 | virt/kvmm |
| RISC-V 虚拟化 | `virt/kvm/riscv/*`（H-ext, AIA） | vCPU entry 初始化幂等性；SBI 转发 | virt/kvmm/src/arch/riscv64 |
| 网络 | `networking/{routing,netdevices}.rst` | 地址所有权归属 netns/设备；下线时地址去留 | net/knet |
| 信号 | `accounting/..`、kernel/signal.c 注释惯例 | fatal_signal_pending 快速路径 + 唤醒两类检查点 | tee/tipc、process/ksignal |
| IRQ | `core-api/genericirq.rst` | 线程化 IRQ；上下文限制（哪些函数不能在硬 IRQ 调） | arch/kirq |
| 内存屏障 | `memory-barriers.txt`（必读） | release/acquire 配对；缓存行伪共享 | 全仓（SMP 路径） |
| 锁 | `locking/locktypes.rst`、`locking/spinlocks.rst` | 持有顺序文档化；sleepable 上下文约束 | task/kspin、task/ksync |

## 审查时的三条 Linux 铁律（跨子系统适用）

1. **锁内不做可睡眠操作**（spinlock 区禁 alloc/IO）——x-kernel 的 kspin 若无静态检查，靠 review 纪律补。
2. **身份/状态先于可见性**：先构造完整再发布（inode、exit 状态、模块 init 同理）。
3. ** errno / on-disk 格式是 API 合同**：错误码映射与磁盘布局变更的兼容性优先于优雅。

## 扩展纪律

- 新子系统进入 x-kernel → 本表加一行（文档路径 + 核心语义 + crate 三元组），同步在 `xkernel_feature_audit.md` 开新问题域
- Linux 文档以 kernel.org master 为准；x-kernel 明确声明"受 Linux 语义启发"（README 自述对齐 Linux），对齐漂移即问题
