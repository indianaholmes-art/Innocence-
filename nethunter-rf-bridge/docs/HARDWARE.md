# Hardware, wiring and GPIO

## Bill of materials

| Part | Notes |
|---|---|
| ESP32-S3 dev board with a **native USB** USB-C port | e.g. Espressif ESP32-S3-DevKitC-1 (use the port labelled **USB**, not UART) |
| CC1101 module | common green "E07-M1101D" / blue 8-pin boards. Check marking: 315, 433, 868 or 915 MHz – the RF matching network is band-specific |
| Antenna | matched to the module band (e.g. 17.3 cm quarter-wave at 433 MHz, 8.6 cm at 868 MHz) |
| USB-C OTG cable / adapter | must be a **data** cable |
| Optional SSD1306 128×64 I²C OLED | reserved pins below (driver not enabled by default) |

CC1101 is a **3.3 V** part (abs. max 3.9 V). Never feed it 5 V on VCC or any IO.

## Default wiring – ESP32-S3-DevKitC-1 (`esp32s3_devkitc` env)

```
 ESP32-S3-DevKitC-1                       CC1101 module
 ┌──────────────────┐                    ┌──────────────┐
 │ 3V3 ─────────────┼────────────────────┤ VCC          │
 │ GND ─────────────┼────────────────────┤ GND          │
 │ GPIO12 (SCK)  ───┼────────────────────┤ SCK  / SCLK  │
 │ GPIO11 (MOSI) ───┼────────────────────┤ MOSI / SI    │
 │ GPIO13 (MISO) ───┼────────────────────┤ MISO / SO    │  (also GDO1)
 │ GPIO10 (CS)   ───┼────────────────────┤ CSN          │
 │ GPIO4         ───┼────────────────────┤ GDO0         │
 │ GPIO5         ───┼────────────────────┤ GDO2         │
 │                  │                    │ ANT ── antenna
 │ GPIO8  (SDA) ──┐ │  optional OLED     └──────────────┘
 │ GPIO9  (SCL) ──┤ │
 │ USB-C "USB" ═══╪═╪══ OTG ══ Android phone (NetHunter)
 └────────────────┘ │
```

| Signal | ESP32-S3 GPIO | CC1101 pin | Direction | Notes |
|---|---|---|---|---|
| SCK | 12 | SCLK | out | FSPI default pin, routed via GPIO matrix |
| MOSI | 11 | SI | out | |
| MISO | 13 | SO/GDO1 | in | also polled for CHIP_RDYn during reset |
| CS | 10 | CSn | out | active low, driven manually |
| GDO0 | 4 | GDO0 | in | asserts on sync word, de-asserts at end of packet (IOCFG0=0x06) |
| GDO2 | 5 | GDO2 | in | CHIP_RDYn (IOCFG2=0x29) — diagnostic only |
| OLED SDA | 8 | – | i/o | reserved |
| OLED SCL | 9 | – | out | reserved |
| 3V3 | 3V3 | VCC | power | board LDO supplies ≤ ~500 mA; CC1101 needs ≤ 35 mA |
| GND | GND | GND | – | |
| USB D-/D+ | 19 / 20 | – | – | **native USB – never reassign** |

### Pins avoided on ESP32-S3 (verified per datasheet)

* GPIO0, 3, 45, 46 – strapping pins
* GPIO19, 20 – USB D-/D+ (our link to the phone)
* GPIO26–32 – SPI flash; GPIO33–37 – octal PSRAM on **N8R8 / N16R8** modules
* GPIO43/44 – UART0 (console on bridge port)
* GPIO38 (DevKitC v1.0) / GPIO48 (v1.1) – on-board RGB LED

`firmware/include/board_config.h` contains a `static_assert` that refuses to
compile if a radio pin is assigned to a strapping, USB or flash pin.

## Changing pins

Each board has its own block in `board_config.h`. Override any pin without
editing code:

```ini
; firmware/platformio.ini
[env:my_board]
board = esp32-s3-devkitc-1
build_flags = ${env.build_flags} -DRFB_BOARD_GENERIC_S3 -DRFB_PIN_CS=14 -DRFB_PIN_GDO0=6
```

**Before compiling for a different board**, check its schematic: many clone
boards wire an LED, button, SD card or camera to "free" pins. `DEVICE_INFO`
reports the compiled pin map so you can confirm what is running.

## Board compatibility

| Board | Status | Notes |
|---|---|---|
| ESP32-S3-DevKitC-1 (N8, N8R2, N8R8, N16R8) | supported (`esp32s3_devkitc`) | use the "USB" port |
| Generic ESP32-S3 "N16R8" / YD-ESP32-S3 | supported (`esp32s3_generic`) | same pins; some have a solder jumper for USB-OTG power – verify 5 V input |
| ESP32-S3 boards with only a CH340/CP2102 USB-C | works | shows up as `/dev/ttyUSB0`; kernel needs `ch341`/`cp210x` |
| Seeed XIAO ESP32-S3 | possible | only 11 GPIOs; define a custom pin set (e.g. SCK=7 MISO=8 MOSI=9 CS=2 GDO0=3 GDO2=4) |
| LilyGO T-Display-S3 / touchscreen S3 boards | possible | display occupies many pins; custom pin block needed |
| ESP32-C3-DevKitM-1 | compiles (`esp32c3_devkitm`) | single-core, USB-Serial-JTAG; pins in board_config.h |
| Original ESP32 / ESP32-S2 | not targeted | no CDC on ESP32; S2 untested |

## Power

The phone powers everything through OTG (typ. ≤ 500 mA available). Idle
ESP32-S3 + CC1101 RX draws ~60–100 mA. If the phone refuses to power the board,
use a powered OTG Y-cable.
