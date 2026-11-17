#!/usr/bin/env bash
# Cross-build USB serial driver modules (cdc-acm, ch341, cp210x) for an Android
# kernel that lacks them. Run on a Linux PC, NOT on the phone.
#
#   KERNEL_SRC=~/android/kernel  KERNEL_CONFIG=/path/to/device.config \
#   CROSS_COMPILE=aarch64-linux-gnu-  [CLANG=1] scripts/build_kernel_modules.sh
#
# KERNEL_SRC must be the exact source your phone's kernel was built from and
# KERNEL_CONFIG its config (adb pull /proc/config.gz && gunzip). Otherwise the
# module will fail to load ("Exec format error" / vermagic mismatch).
set -euo pipefail
: "${KERNEL_SRC:?path to the device kernel source}"
: "${KERNEL_CONFIG:?device kernel .config (from /proc/config.gz)}"
CROSS_COMPILE="${CROSS_COMPILE:-aarch64-linux-gnu-}"
OUT="${OUT:-$PWD/kmod-out}"
MAKEARGS=(ARCH=arm64 CROSS_COMPILE="$CROSS_COMPILE" O="$OUT")
[ "${CLANG:-0}" = 1 ] && MAKEARGS+=(LLVM=1 CC=clang)

mkdir -p "$OUT"
cp "$KERNEL_CONFIG" "$OUT/.config"
# Enable drivers as modules without touching anything else.
"$KERNEL_SRC/scripts/config" --file "$OUT/.config" \
  -m USB_ACM -m USB_SERIAL -m USB_SERIAL_CH341 -m USB_SERIAL_CP210X
make -C "$KERNEL_SRC" "${MAKEARGS[@]}" olddefconfig
make -C "$KERNEL_SRC" "${MAKEARGS[@]}" modules_prepare
make -C "$KERNEL_SRC" "${MAKEARGS[@]}" M=drivers/usb/class modules
make -C "$KERNEL_SRC" "${MAKEARGS[@]}" M=drivers/usb/serial modules

echo "Built modules:"
find "$OUT/drivers/usb/class" "$OUT/drivers/usb/serial" -name '*.ko' -print
cat <<MSG

Install on the phone (root):
  adb push $OUT/drivers/usb/class/cdc-acm.ko /data/local/tmp/
  adb shell su -c 'insmod /data/local/tmp/cdc-acm.ko'
  # bridge boards: insmod usbserial.ko first, then ch341.ko / cp210x.ko
Check: adb shell su -c 'dmesg | tail'  -> "cdc_acm ...: ttyACM0: USB ACM device"
Verify vermagic first:  modinfo cdc-acm.ko | grep vermagic   vs   adb shell uname -r
MSG
