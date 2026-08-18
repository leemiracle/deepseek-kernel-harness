#!/usr/bin/env bash
# k_maintainer.sh — LKML 收件人解析：get_maintainer.pl
# 用法: k_maintainer.sh <file.c 或 patch.diff>
# 退出码: 0=解析成功  2=环境缺
set -u
F="${1:-}"
[ -z "$F" ] && { echo "usage: $0 <file.c|patch.diff>"; exit 2; }
[ -f "$F" ] || { echo "no such file: $F"; exit 2; }

KS="${KERNEL_SRC:-}"
[ -z "$KS" ] && [ -d ./scripts ] && KS="$PWD"
[ -z "$KS" ] && [ -d ../linux/scripts ] && KS="$(cd ../linux && pwd)"
[ -z "$KS" ] && { echo "[k_maint] export KERNEL_SRC=/path/to/linux"; exit 2; }
GM="$KS/scripts/get_maintainer.pl"
[ -x "$GM" ] || { echo "[k_maint] missing $GM"; exit 2; }
command -v perl >/dev/null || { echo "[k_maint] missing perl"; exit 2; }

echo "[k_maint] 收件人（邮寄对象由脚本定，agent 不自选——AGENTS.md 契约）:"
case "$F" in
  *.diff|*.patch) exec perl "$GM" --noroles --nogit "$F";;
  *)              exec perl "$GM" --noroles --nogit -f "$F";;
esac
