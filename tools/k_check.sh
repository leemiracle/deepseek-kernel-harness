#!/usr/bin/env bash
# k_check.sh — L1 风格验证：checkpatch.pl --strict
# 用法: k_check.sh <file.c|patch.diff>
# 退出码: 0=过  1=有 ERROR  2=环境缺（报装法）
set -u
F="${1:-}"
[ -z "$F" ] && { echo "usage: $0 <file.c|patch.diff>"; exit 2; }
[ -f "$F" ] || { echo "no such file: $F"; exit 2; }

# --- 内核树探测（与所有 k_* 脚本一致的顺序）---
KS="${KERNEL_SRC:-}"
if [ -z "$KS" ]; then
  for cand in ./linux ../linux "/lib/modules/$(uname -r)/source" "/lib/modules/$(uname -r)/build"; do
    [ -d "$cand/scripts" ] && KS="$cand" && break
  done
fi
[ -z "$KS" ] && {
  echo "[k_check] KERNEL_SRC not found. export KERNEL_SRC=/path/to/linux (需含 scripts/checkpatch.pl)"; exit 2; }

CP="$KS/scripts/checkpatch.pl"
[ -x "$CP" ] || { echo "[k_check] missing $CP — 你的内核树不完整（git clone 后需完整 checkout）"; exit 2; }
command -v perl >/dev/null || { echo "[k_check] missing perl. apt install perl"; exit 2; }

# diff 走补丁模式，源文件走 file 模式（--no-tree 允许脱离内核树单文件检查）
case "$F" in
  *.diff|*.patch) MODE=(--strict -q "$F");;
  *)              MODE=(--strict --no-tree --file "$F");;
esac
echo "[k_check] L1 on: $F"
perl "$CP" "${MODE[@]}"
rc=$?
# checkpatch 退出码: 0=干净 1=有 ERROR 2=脚本自身致命错
[ $rc -eq 2 ] && echo "[k_check] checkpatch 自身出错，检查补丁格式是否完整" >&2
# 第一个 ERROR 就是下一步导航：修它，重跑，别攒着
exit $rc
