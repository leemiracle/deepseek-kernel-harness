#!/usr/bin/env bash
# k_build.sh — L3 构建验证：make W=1 增量编译（objtree 外置 + flock 互斥）
# 设计点：多 agent/多会话共用同一 objtree 会互踩产物 —— flock 是 graph 层
#         "冲突"治理在执行端的落点（governance/patch_queue.py 在补丁层治，本脚本在构建层治）。
# 用法: k_build.sh <kernel-relative-path>   例: k_build.sh drivers/char
# 退出码: 0=过  1=失败  2=环境缺
set -u
TARGET="${1:-}"
[ -z "$TARGET" ] && { echo "usage: $0 <kernel-relative-path>"; exit 2; }

KS="${KERNEL_SRC:-}"
[ -z "$KS" ] && [ -d ./scripts ] && KS="$PWD"
[ -z "$KS" ] && [ -d ../linux/scripts ] && KS="$(cd ../linux && pwd)"
[ -z "$KS" ] && { echo "[k_build] export KERNEL_SRC=/path/to/linux"; exit 2; }
command -v gcc >/dev/null || { echo "[k_build] missing gcc"; exit 2; }
command -v make >/dev/null || { echo "[k_build] missing make"; exit 2; }

# 外置 objtree：源码树只读，产物集中（也便于 CI 清理与并行系列隔离）
KOUT="${KOUT:-$KS/.kout}"
mkdir -p "$KOUT"
LOCK="$KOUT/.build.lock"

echo "[k_build] L3: make W=1 M=$TARGET (objtree=$KOUT, locked)"
# flock -w 900：等锁最多 15 分钟；抢不到锁说明有并行构建在跑——排队而非互踩
exec 9>"$LOCK"
if ! flock -w 900 9; then
  echo "[k_build] 构建锁 15 分钟超时：objtree 正被长构建占用。检查是否有失控会话（graph 层冲突的执行端症状）" >&2
  exit 1
fi

cd "$KS" || exit 2
# O= 外置 + W=1 额外警告 + M= 只编目标子系统；首跑需先有 .config
if [ ! -f "$KOUT/.config" ]; then
  echo "[k_build] 首次构建：生成默认 defconfig"
  make -s O="$KOUT" defconfig || exit 2
fi
LOG="$KOUT/build.log"
if make -j"$(nproc)" O="$KOUT" W=1 M="$TARGET" 2>&1 | tee "$LOG"; then
  W=$(grep -cE 'warning:' "$LOG" || true)
  echo "[k_build] PASS — warnings=$W （AGENTS.md：警告=失败心态；非零须逐条解释）"
  exit 0
else
  echo "[k_build] FAIL — 修第一个 error 后重跑（报错即导航）"
  exit 1
fi
