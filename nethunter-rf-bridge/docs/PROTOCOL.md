# RF Bridge serial protocol (v1)

Transport: USB CDC-ACM (ESP32-S3 native USB → `/dev/ttyACM*`) or a USB-UART
bridge (`/dev/ttyUSB*`). Baud rate is ignored on native USB; use 115200 on
bridges. Framing: **one UTF-8 JSON object per line, `\n`-terminated**, max 511
bytes per request line.

## Requests

```json
{"id": 7, "cmd": "SET_FREQUENCY", "args": {"hz": 433920000}}
```

* `id` (optional int ≥ 0) is echoed back so the host can match responses.
* `cmd` is required. A bare word line (`GET_VERSION\n`) is accepted as a
  shortcut for `{"cmd":"GET_VERSION"}`; handy from `screen`/`picocom`.

## Responses

```json
{"type":"response","id":7,"cmd":"SET_FREQUENCY","ok":true,"data":{"frequency_hz":433920000},"seq":12}
{"type":"response","id":8,"cmd":"SET_FREQUENCY","ok":false,"error":{"code":"UNSUPPORTED_FREQUENCY","message":"..."},"seq":13}
```

`seq` increments on every line the device sends; gaps indicate dropped output.

## Commands

| cmd | args | data |
|---|---|---|
| `PING` | – | `pong` |
| `GET_VERSION` | – | `fw`, `version`, `proto`, `build` |
| `DEVICE_INFO` | – | board, chip model/rev, MAC, flash/PSRAM, heap, uptime, radio chip/version, `simulation`, `pins`, `reset_reason` |
| `RADIO_STATUS` | – | chip, present, state, frequency_hz, modulation, data_rate_kbps, deviation_khz, rx_bandwidth_khz, sync_word, sync_required, crc, max_packet_len, packets, crc_errors, rssi_stream_ms, last_error |
| `SET_FREQUENCY` | `hz` (int, exact) **or** `mhz` (number, rounded to 100 Hz) | `frequency_hz` |
| `SET_CONFIG` | any of: `frequency_hz`, `frequency_mhz`, `modulation`, `data_rate_kbps` (0.6–500), `deviation_khz` (1.5–381), `rx_bandwidth_khz` (58–812), `sync_word` ("D391"), `sync_required` (bool), `crc` (bool), `max_packet_len` (1–61) | full radio status |
| `SET_MODULATION` | alias of `SET_CONFIG` | full radio status |
| `START_RECEIVE` | – | `state` |
| `STOP_RECEIVE` | – | `state` |
| `GET_RSSI` | – | `rssi_dbm`, `frequency_hz` |
| `RSSI_STREAM` | `interval_ms` 0 (off) or 20–10000 | `interval_ms` |
| `RESET_RADIO` | – | full radio status (re-detects CC1101, re-applies config) |
| `TX_TEST` | `count` 1–10, `confirm_authorized: true` | `sent` |
| `REBOOT` | – | `rebooting` (then the device resets) |

Modulation names: `2-FSK`, `GFSK`, `ASK/OOK` (`OOK`, `ASK`), `4-FSK`, `MSK`.
Supported CC1101 frequency bands: **300–348, 387–464, 779–928 MHz**. Your
module's matching network/antenna is usually tuned for only one of these; check
the module marking (315/433/868/915).

### TX_TEST

Transmits a fixed `RFB-TEST-nnn` frame at roughly −10 dBm, at most 10 per call.
There is deliberately no command to transmit arbitrary or captured payloads:
no replay, no key/rolling-code functionality. Use it only on frequencies and
power levels you are permitted to use (e.g. into a dummy load, shielded box, or
an ISM band with your own receiver).

## Events (unsolicited)

| type | fields |
|---|---|
| `hello` | sent at boot: `fw`, `version`, `proto`, `radio`, `radio_present`, `warning?` |
| `packet` | `n`, `ts_us` (device µs since boot), `frequency_hz`, `modulation`, `len`, `rssi_dbm`, `lqi` (0–127, lower = better), `crc_ok`, `data` (hex) |
| `rssi` | `rssi_dbm`, `frequency_hz` (when `RSSI_STREAM` > 0) |
| `heartbeat` | every 5 s: `state`, `packets`, `free_heap` |

All events also carry `t_us` and `seq`.

## Error codes

`BAD_JSON`, `LINE_TOO_LONG`, `BAD_ARGS`, `UNKNOWN_COMMAND`,
`UNSUPPORTED_FREQUENCY`, `NO_RADIO`, `RADIO_ERROR`, `NOT_AUTHORIZED`.
Host-side only: `TIMEOUT`, `DISCONNECTED`.

## Connection recovery

* The host ignores non-JSON lines (ROM boot banner, IDF logs).
* A `hello` event after start-up means the device rebooted; the host
  re-applies receive state.
* On USB disconnect the host app polls for the port to return (same path
  first, then any RF Bridge) for ~60 s and restores receive mode.
* Missing heartbeats for > 10 s indicate a stalled link.

## What a packet is (and is not)

The CC1101 demodulates in hardware and only delivers frames that match the
configured modulation, data rate, preamble/sync word and length. `data` is the
demodulated payload, **not** a raw RF/IQ recording. Signals that use another
modulation, rate, or no sync word will not appear (or appear as garbage with
`sync_required=false`). For waveform capture use an SDR (see ARCHITECTURE.md).
