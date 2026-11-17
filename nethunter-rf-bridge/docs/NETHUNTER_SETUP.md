# Kali NetHunter setup

Works on NetHunter (rooted, custom kernel), NetHunter Lite (rooted, stock
kernel) and NetHunter Rootless (Termux). Root is **not** required by the app,
but the Android kernel must expose the USB serial device to Linux.

## 1. Install the host app

In the NetHunter Kali chroot terminal (or Termux):

```bash
git clone <this repo> && cd nethunter-rf-bridge
./scripts/install.sh            # creates ~/.local/share/nethunter-rf venv + `nethunter-rf` launcher
nethunter-rf --simulate dashboard   # try without hardware
```

Dependencies are only `pyserial` and `rich` (pure Python, no compiler needed).
`install.sh` will use `apt` packages `python3-serial python3-rich` if pip is
unavailable.

## 2. Flash the firmware (from a PC, once)

```bash
pip install platformio
cd firmware
pio run -e esp32s3_devkitc -t upload     # or esp32s3_sim to test without CC1101
```

Flashing from the phone is possible (`pio` runs in the Kali chroot on arm64)
but slow; a PC is recommended for the first flash. If upload fails: hold
**BOOT**, tap **RST**, release BOOT, retry.

## 3. Connect

Plug the board's **USB** port into the phone with an OTG data cable.

```bash
nethunter-rf doctor     # checks device nodes, driver, permissions, handshake
nethunter-rf list
nethunter-rf info
nethunter-rf dashboard
```

## 4. Kernel driver (the "kernel module" part)

The ESP32-S3 native USB enumerates as a standard **CDC-ACM** device
(VID 0x303A). No custom kernel module is needed – the stock Linux `cdc_acm`
driver handles it. Bridge-chip boards need `ch341` (CH340) or `cp210x`.

Check what your kernel has:

```bash
./scripts/check_kernel.sh
```

* **Driver built in / loaded** → `/dev/ttyACM0` appears on plug-in. Done.
* **Driver missing** (common on some stock kernels; NetHunter kernels usually
  include `CONFIG_USB_ACM=y`):
  1. Prefer a NetHunter kernel for your device, or
  2. Build `cdc-acm.ko` for **your exact kernel** with
     `scripts/build_kernel_modules.sh` (needs the device's kernel source,
     its `.config`, and an aarch64 cross toolchain on a PC), then
     `adb push cdc-acm.ko /data/local/tmp && su -c insmod /data/local/tmp/cdc-acm.ko`.
     The module's vermagic must match `uname -r` exactly, and devices with
     module signature enforcement will reject unsigned modules.
  3. Rootless fallback: Android apps can talk to USB serial without kernel
     drivers via the Android USB Host API (e.g. using an app that bridges
     USB-serial to a TCP port). Run such a bridge and point the host at it by
     wrapping with `socat pty,link=/tmp/rfb,raw tcp:127.0.0.1:PORT` then
     `nethunter-rf -p /tmp/rfb dashboard`.

## 5. Permissions inside the chroot

Device nodes are created by Android with owner `root`/group `dialout`-equivalent
gid that may not map into the chroot. Options, least privilege first:

```bash
ls -l /dev/ttyACM0                       # note group id
sudo usermod -aG dialout $USER           # if the gid maps to dialout
su -c 'chmod 660 /dev/ttyACM0 && chgrp 20 /dev/ttyACM0'   # on Android side (20 = dialout in Kali)
```

`nethunter-rf list` shows `denied` and the exact mode/gid when access is
missing; the app never silently escalates privileges.

## 6. Data location

Captures default to `~/rf-captures/` (dashboard) or the working directory (CLI).
Copy to Android storage with `cp ~/rf-captures/* /sdcard/Download/` (path visible
from the chroot as `/sdcard`).
