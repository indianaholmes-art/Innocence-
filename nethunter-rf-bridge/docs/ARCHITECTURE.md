# Architecture & extension guide

```
 Android phone (Kali NetHunter chroot / Termux)          ESP32-S3
 ┌─────────────────────────────────────────────┐        ┌────────────────────────────┐
 │ cli.py / dashboard.py   (UI)                │        │ main.cpp                   │
 │ analysis.py  export.py  config.py  (logic)  │        │ protocol.cpp  (JSON lines) │
 │ client.py   (request/response, events,      │  USB   │ radio_hal.h   (interface)  │
 │              reconnect)                     │◄──────►│ ├─ cc1101.cpp (SPI driver) │
 │ transport.py│simulator.py (byte transport)  │  CDC   │ └─ sim_radio.cpp           │
 └─────────────────────────────────────────────┘        └──────────────┬─────────────┘
                                                                        │ SPI
                                                                     CC1101
```

Layering rules:

* **The host never knows radio registers.** It speaks protocol v1 only. All
  radio specifics live in firmware drivers behind `RadioHAL`.
* **Transport is swappable.** Anything with `open/close/read_line/write_line/
  connected` works: `SerialTransport`, `SimulatedTransport`, or a future TCP /
  BLE transport.
* **Analysis works on `Packet` objects**, so captures from other sources can be
  fed in as long as they are converted to `Packet`.

## Adding hardware

| Target | Where | How |
|---|---|---|
| Second CC1101 | firmware | instantiate a second `CC1101Radio` on its own CS pin (shared SCK/MOSI/MISO); add `"radio": 0/1` to protocol args |
| ESP32-C3 | firmware | `esp32c3_devkitm` env already exists; pin block in `board_config.h` |
| S3 touchscreen UI | firmware | add a display task that reads `RadioHAL::config()` and packet counters; keep protocol on USB |
| LoRa (SX127x/SX126x) | firmware | implement `RadioHAL` (`chipName`, `applyConfig`, `poll` …); map `modulation:"LORA"` + SF/BW/CR args |
| RTL-SDR | host | separate transport-less source: run `rtl_power`/`rtl_433 -F json` and convert lines into `Packet`/RSSI samples – this is where real wideband/IQ capture belongs |
| USB CAN adapters | host | new package module using SocketCAN (`python-can`) – independent of `RFBridgeClient` |
| Other USB serial gear | host | add VID to `transport.KNOWN_VIDS`; reuse `SerialTransport` |

## Packet reception vs raw RF capture

The CC1101 is a packet radio with on-chip demodulation. The bridge reports
demodulated bytes and per-packet RSSI/LQI plus polled RSSI. It **cannot**
produce IQ samples, spectrum waterfalls or waveform recordings, and the tools
here never claim to. Use an RTL-SDR/HackRF/etc. for that.
