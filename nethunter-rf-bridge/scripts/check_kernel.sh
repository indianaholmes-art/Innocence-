#!/usr/bin/env bash
# Report whether the running (Android) kernel can expose the RF Bridge as a tty.
# Read-only; root gives more detail but is not required.
set -u
ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✘\033[0m %s\n' "$*"; }
info() { printf '  • %s\n' "$*"; }

echo "Kernel: $(uname -r) ($(uname -m))"
CFG=""
for f in /proc/config.gz; do [ -r "$f" ] && CFG="$(zcat "$f" 2>/dev/null)"; done
check_cfg() {  # $1 symbol $2 description
  if [ -z "$CFG" ]; then info "$1: unknown (/proc/config.gz not readable)"; return; fi
  v="$(printf '%s\n' "$CFG" | grep -E "^$1=" | cut -d= -f2)"
  case "$v" in
    y) ok "$1=y ($2, built in)";;
    m) ok "$1=m ($2, module – needs modprobe/insmod)";;
    *) bad "$1 not set ($2)";;
  esac
}
echo "Kernel config:"
check_cfg CONFIG_USB_OTG "USB OTG"
check_cfg CONFIG_USB_ACM "CDC-ACM: ESP32-S3 native USB"
check_cfg CONFIG_USB_SERIAL_CH341 "CH340 bridge"
check_cfg CONFIG_USB_SERIAL_CP210X "CP210x bridge"
check_cfg CONFIG_USB_SERIAL_FTDI_SIO "FTDI bridge"

echo "Registered tty drivers:"
if [ -r /proc/tty/drivers ]; then
  grep -E 'acm|ttyUSB' /proc/tty/drivers >/dev/null && grep -E 'acm|ttyUSB' /proc/tty/drivers | sed 's/^/  /' \
    || bad "no acm/usbserial tty driver registered"
else info "/proc/tty/drivers not readable"; fi

echo "USB drivers in sysfs:"
for d in cdc_acm ch341 cp210x ftdi_sio; do
  [ -d "/sys/bus/usb/drivers/$d" ] || [ -d "/sys/bus/usb-serial/drivers/$d" ] && ok "$d registered"
done
echo "Device nodes:"
ls -l /dev/ttyACM* /dev/ttyUSB* 2>/dev/null | sed 's/^/  /' || info "none (plug in the board)"
echo "Attached Espressif devices (VID 303a):"
grep -l 303a /sys/bus/usb/devices/*/idVendor 2>/dev/null | sed 's#/idVendor##;s/^/  /' || info "none visible"
