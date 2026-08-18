#!/usr/bin/env bash
# k_boot.sh — L4 冒烟验证：virtme 优先，QEMU 兜底
# 用法: k_boot.sh [kernel-image]   缺省用 KOUT 里刚编的 bzImage
# 退出码: 0=启动且到 login  1=启动失败/panic  2=环境缺（报装法）
set -u

KS="${KERNEL_SRC:-}"
[ -z "$KS" ] && [ -d ./scripts ] && KS="$PWD"
[ -z "$KS" ] && [ -d ../linux/scripts ] && KS="$(cd ../linux && pwd)"
KOUT="${KOUT:-$KS/.kout}"
IMG="${1:-$KOUT/arch/x86/boot/bzImage}"

# --- virtme 路线：宿主用户态 + 新内核，最贴近"驱动加载即可用" ---
if command -v virtme-run >/dev/null 2>&1; then
  echo "[k_boot] L4 via virtme: $IMG"
  # --kconfig 附带常用 debug 选项；60s 硬超时；成功标志 = init 完成返回
  timeout 120 virtme-run --kdir "$KS" --kimg "$IMG" --kconfig \
    --script-sh 'echo BOOT_OK; dmesg | grep -iE "bug|oops|panic" && exit 1 || exit 0'
  rc=$?
  [ $rc -eq 0 ] && echo "[k_boot] PASS" || echo "[k_boot] FAIL(rc=$rc)：看上面 dmesg 摘要，定位到具体 subsytem" >&2
  exit $rc
fi

# --- QEMU 兜底：bzImage + initrd（无 initrd 则纯启动到 panic=VFS 也算内核本体健康）---
if command -v qemu-system-x86_64 >/dev/null 2>&1; then
  [ -f "$IMG" ] || { echo "[k_boot] missing $IMG — 先跑 k_build.sh"; exit 2; }
  echo "[k_boot] L4 via qemu (无 rootfs，看早期启动 + 内核日志)"
  timeout 90 qemu-system-x86_64 -m 512M -kernel "$IMG" -append 'console=ttyS0 panic=-1' \
    -nographic -no-reboot 2>&1 | tee /tmp/k_boot.log
  # panic=-1: 出 panic 立即退出；正常路径由 timeout 截断
  if grep -qiE 'Kernel panic' /tmp/k_boot.log; then
    echo "[k_boot] FAIL: kernel panic — 看 /tmp/k_boot.log 最后 30 行" >&2; exit 1
  fi
  if grep -q 'Freeing unused kernel memory' /tmp/k_boot.log; then
    echo "[k_boot] PASS (早期启动健康；驱动级冒烟建议装 virtme)"; exit 0
  fi
  echo "[k_boot] FAIL: 未达 Freeing unused kernel memory" >&2; exit 1
fi

echo "[k_boot] L4 工具全缺。装法（推荐 virtme，免做 rootfs）："
echo "  pip install virtme            # 或 apt install virtme"
echo "  apt install qemu-system-x86   # 兜底路线"
exit 2
