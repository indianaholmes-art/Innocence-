# subGdev (Android app)

Standalone Android app for the ESP32-S3 + CC1101 RF Bridge.

* Talks to the board over **USB-C OTG through the Android USB Host API**:
  no root, no NetHunter chroot, no kernel `cdc_acm` driver needed.
* Auto-opens when the board (Espressif VID 0x303A) is plugged in.
* Live RSSI graph, frequency/modulation control, start/stop receive, packet
  list with protocol/class tags, lab TX test (with confirmation), diagnostics.
* Saves captures to `Download/subGdev/` as JSON + CSV in **the same format as
  the NetHunter CLI**, so `nethunter-rf analyze capture-….json` works on them
  inside the chroot.
* Built-in **Simulator** button for use without hardware.

Supports CDC-ACM devices (ESP32-S3 native "USB" port). Boards that only have a
CH340/CP210x USB-UART chip are not supported by the app (they are supported by
the NetHunter CLI with the kernel fragment in `../kernel/`).

Note: Android allows one owner of a USB device at a time. While subGdev has the
board open, the chroot's `/dev/ttyACM0` is unavailable, and vice versa.

## Get the APK

* **CI:** every push builds `subGdev-release.apk` (GitHub → Actions →
  nethunter-rf-bridge → artifact `subGdev-apk`).
* **Local:** Android Studio, or with the Android SDK installed:
  ```bash
  cd android && ./gradlew assembleRelease
  # → app/build/outputs/apk/release/app-release.apk
  adb install -r app/build/outputs/apk/release/app-release.apk
  ```
The release build is signed with the debug key so it installs directly;
use your own keystore before distributing it.
