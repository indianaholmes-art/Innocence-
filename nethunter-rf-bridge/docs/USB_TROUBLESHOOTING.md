# USB troubleshooting

Run `nethunter-rf doctor` first; it reports most of the items below.

| Symptom | Likely cause | Fix |
|---|---|---|
| Nothing in `/dev/ttyACM*` or `/dev/ttyUSB*`, board LED off | phone not supplying OTG power | enable OTG in Android settings (some phones auto-disable it after 10 min), try powered OTG Y-cable |
| Board powered, still no device node | charge-only cable, wrong port (UART vs USB), missing driver | use a data cable; use the **USB** port; `scripts/check_kernel.sh` |
| `dmesg` shows `new full-speed USB device ... idVendor=303a` but no ttyACM | `cdc_acm` missing | see NETHUNTER_SETUP.md §4 |
| `permission denied` / `list` shows `denied` | device node gid not accessible in chroot | NETHUNTER_SETUP.md §5 <a id="permissions"></a> |
| `Device busy` | another app (e.g. a USB serial terminal app) has claimed the interface | close it; Android may also show a "open with" dialog – dismiss it |
| Port appears then vanishes in a loop | brown-out: CC1101 + ESP32 inrush on weak OTG | powered OTG hub; add 10 µF + 100 nF at CC1101 VCC |
| `TIMEOUT` on every command | wrong firmware / board in download mode | reflash; press RST; `nethunter-rf raw PING` |
| `not an RF Bridge` | another CDC device (Arduino, modem) was picked | pass `-p /dev/ttyACM1` |
| `CC1101 not responding (MISO stuck high)` | wiring, no 3.3 V, swapped MISO/MOSI | check wiring table in HARDWARE.md |
| `CC1101 not detected (VERSION=0x0/0xff)` | SPI pins wrong / module dead | verify pins in `nethunter-rf info` match wiring |
| `Register verify failed` | SPI signal integrity | shorter wires (< 10 cm), lower `RFB_SPI_HZ` |
| Packets never arrive though RSSI rises | modulation / data rate / sync word mismatch – CC1101 only outputs matching frames | match the transmitter's parameters; try `config --sync-required off` (carrier-sense mode, noisier) |
| Random junk packets | `sync_required off` in a noisy band | turn sync back on; use CRC |
| Port name changes after replug (`ttyACM0`→`ttyACM1`) | old node still open | the app reconnects automatically; otherwise close and reopen |

Useful commands (root shell on Android side):

```bash
su -c dmesg | grep -iE 'usb|acm|303a' | tail
su -c 'ls -l /dev/ttyACM* /dev/ttyUSB*'
cat /proc/tty/drivers | grep -E 'acm|ttyUSB'
```
