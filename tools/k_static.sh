#!/usr/bin/env bash
# k_static.sh — L2 静态分析：sparse (make C=2) + coccinelle (make coccicheck)
# 用法: k_static.sh <path/under/kernel/tree>   例: k_static.sh drivers/char/foo.c 所在目录
# 退出码: 0=过（或仅有可解释 warning 需人工看）1=失败 2=环境缺（报装法）
set -u
TARGET="${1:-}"
[ -z "$TARGET" ] && { echo "usage: $0 <kernel-relative-path>"; exit 2; }

KS="${KERNEL_SRC:-}"
[ -z "$KS" ] && [ -d ./scripts ] && KS="$PWD"
[ -z "$KS" ] && [ -d ../linux/scripts ] && KS="$(cd ../linux && pwd)"
[ -z "$KS" ] && { echo "[k_static] export KERNEL_SRC=/path/to/linux"; exit 2; }

HAVE_SPARSE=1; command -v sparse >/dev/null || HAVE_SPARSE=0
HAVE_COCC=1;   command -v spatch >/dev/null || HAVE_COCC=0
[ $HAVE_SPARSE -eq 0 ] && [ $HAVE_COCC -eq 0 ] && {
  echo "[k_static] L2 工具全缺。装法："
  echo "  apt install sparse            # sparse: 类型/地址空间检查（make C=2）"
  echo "  apt install coccinelle        # spatch: 语义 patch（make coccicheck）"
  exit 2; }

cd "$KS" || exit 2
FAIL=0

if [ $HAVE_SPARSE -eq 1 ]; then
  echo "[k_static] sparse (C=2, W=1 联合) on: $TARGET"
  # C=2: 重编全部相关 .c（含头文件依赖面）；首次跑很慢，增量续跑快
  if ! make -j"$(nproc)" C=2 W=1 M="$TARGET" 2>&1 | tee /tmp/k_sparse.log; then FAIL=1; fi
  # sparse 输出在编译流里，抽出行数提示 agent 关注度
  echo "[k_static] sparse findings: $(grep -c 'warning:' /tmp/k_sparse.log || true) (0 最好；非零须逐条给出豁免理由)"
else
  echo "[k_static] sparse 未装，跳过（apt install sparse）"
fi

if [ $HAVE_COCC -eq 1 ]; then
  echo "[k_static] coccinelle on: $TARGET"
  if ! make coccicheck M="$TARGET" MODE=report 2>&1 | tail -40; then FAIL=1; fi
else
  echo "[k_static] coccinelle 未装，跳过（apt install coccinelle）"
fi

exit $FAIL
