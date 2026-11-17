# NetHunter RF Bridge

ESP32-S3 + CC1101 sub-GHz packet receiver that plugs into an Android phone over
USB-C and is driven entirely from Kali NetHunter.

```
[CC1101]──SPI──[ESP32-S3]══USB-C OTG══[Phone: NetHunter → nethunter-rf dashboard]
```

**What it is:** a portable packet-level RF analysis tool – demodulated frames,
per-packet RSSI/LQI, live RSSI, timing, repeat/variation analysis, protocol
signatures, JSON/CSV export.
**What it is not:** an SDR. The CC1101 only outputs frames that match its
configured modulation/data-rate/sync word; it does not record raw RF/IQ.
Transmit is limited to a fixed, low-power lab test pattern; there is no replay,
cloning or rolling-code functionality.

## Repository layout

```
firmware/            PlatformIO (Arduino on ESP-IDF) firmware
  include/           board_config.h (all GPIOs), radio_hal.h, cc1101.h, protocol.h …
  src/               main.cpp, cc1101.cpp (register-level driver), sim_radio.cpp, protocol.cpp
host/nethunter_rf/   Python 3 app: transport, client, simulator, analysis, export, dashboard, cli
config/              example radio profiles + protocol signature file
docs/                PROTOCOL, HARDWARE (wiring/GPIO/compat), NETHUNTER_SETUP, USB_TROUBLESHOOTING, ARCHITECTURE
tests/               pytest suite + tests/native (firmware compiled & tested on the host)
scripts/             install.sh, flash.sh, check_kernel.sh, build_kernel_modules.sh, run_tests.sh
```

## Quick start

1. **Wire** the CC1101 per [docs/HARDWARE.md](docs/HARDWARE.md) (default: SCK 12, MOSI 11, MISO 13, CS 10, GDO0 4, GDO2 5, 3V3, GND).
2. **Flash** (from a PC): `pip install platformio && scripts/flash.sh esp32s3_devkitc`
   – no CC1101 yet? flash `esp32s3_sim` for a fully simulated radio.
3. **Install on the phone** (NetHunter terminal): `scripts/install.sh`
4. **Connect** via OTG and run:

```bash
nethunter-rf doctor                    # USB/driver/permission checks
nethunter-rf info                      # firmware + board + pin map
nethunter-rf dashboard                 # interactive UI (r=rx, f=freq, m=mod, s=save, q=quit)
nethunter-rf rx --freq 433.92 -d 60 -o cap.json    # capture to JSON + CSV
nethunter-rf analyze cap.json --length 6           # offline analysis
nethunter-rf rssi --freq 868.3 -n 50               # RSSI probe
nethunter-rf config -f config/example_868_gfsk.json
nethunter-rf --json status                         # machine-readable output
```

Everything also works without hardware: add `--simulate`.

## Build & test

```bash
cd firmware && pio run                  # builds all envs (CI does this on every push)
scripts/run_tests.sh                    # pytest + native firmware tests
```

The native tests compile the real firmware sources with g++ against a stub
Arduino core and an emulated CC1101 register file, verifying the JSON protocol
and the register values the driver writes (frequency word, data rate,
modulation, PATABLE) against TI reference values.

## Kernel driver

ESP32-S3 native USB is a standard CDC-ACM device – the stock Linux `cdc_acm`
driver is all that is needed, no custom kernel module. If your Android kernel
lacks it, see [docs/NETHUNTER_SETUP.md §4](docs/NETHUNTER_SETUP.md) and
`scripts/build_kernel_modules.sh`.

## Legal

Receiving and transmitting radio signals is regulated. Only monitor and
transmit where you are permitted, and only analyze devices you own or are
authorized to test.
