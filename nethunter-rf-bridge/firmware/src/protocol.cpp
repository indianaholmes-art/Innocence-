#include "protocol.h"
#include <math.h>
#include <esp_system.h>
#include <esp_timer.h>
#include "board_config.h"
#include "version.h"

static const uint8_t kMaxTestPackets = 10;

// ArduinoJson 7 stores short decimals (e.g. 868.3) as 32-bit float, which is
// off by up to ~30 Hz. CC1101 resolution is ~397 Hz, so round to 100 Hz.
// Hosts wanting exact values send integer "hz" instead.
static uint32_t mhzToHz(double mhz) { return (uint32_t)(llround(mhz * 1e4) * 100); }

ProtocolHandler::ProtocolHandler(Stream& io, RadioHAL& radio) : io_(io), radio_(radio) {}

void ProtocolHandler::emit(JsonDocument& doc) {
  doc["seq"] = seq_++;
  serializeJson(doc, io_);
  io_.write('\n');
}

void ProtocolHandler::sendEvent(const char* type, JsonDocument& doc) {
  doc["type"] = type;
  doc["t_us"] = esp_timer_get_time();
  emit(doc);
}

void ProtocolHandler::sendError(int id, const char* code, const char* msg) {
  JsonDocument d;
  d["type"] = "response";
  if (id >= 0) d["id"] = id;
  d["ok"] = false;
  d["error"]["code"] = code;
  d["error"]["message"] = msg;
  cmdErrors_++;
  emit(d);
}

void ProtocolHandler::begin() {
  JsonDocument d;
  d["fw"] = RFB_FW_NAME;
  d["version"] = RFB_FW_VERSION;
  d["proto"] = RFB_PROTO_VERSION;
  d["radio"] = radio_.chipName();
  d["radio_present"] = radio_.present();
  if (radio_.lastError().length()) d["warning"] = radio_.lastError();
  sendEvent("hello", d);
}

void ProtocolHandler::fillStatus(JsonObject o) {
  const RadioConfig& c = radio_.config();
  o["chip"] = radio_.chipName();
  o["present"] = radio_.present();
  o["state"] = radioStateName(radio_.state());
  o["frequency_hz"] = c.frequencyHz;
  o["modulation"] = modulationName(c.modulation);
  o["data_rate_kbps"] = c.dataRateKbps;
  o["deviation_khz"] = c.deviationKhz;
  o["rx_bandwidth_khz"] = c.rxBandwidthKhz;
  char sw[5];
  snprintf(sw, sizeof(sw), "%02X%02X", c.syncWord[0], c.syncWord[1]);
  o["sync_word"] = sw;
  o["sync_required"] = c.syncRequired;
  o["crc"] = c.crcEnabled;
  o["max_packet_len"] = c.maxPacketLen;
  o["packets"] = packets_;
  o["crc_errors"] = crcErrors_;
  o["rssi_stream_ms"] = rssiStreamMs_;
  if (radio_.lastError().length()) o["last_error"] = radio_.lastError();
}

static bool applyConfigArgs(JsonObjectConst a, RadioConfig& c, String& err) {
  if (a["frequency_hz"].is<uint32_t>()) c.frequencyHz = a["frequency_hz"];
  if (a["frequency_mhz"].is<float>()) c.frequencyHz = mhzToHz(a["frequency_mhz"].as<double>());
  if (a["modulation"].is<const char*>()) {
    if (!modulationFromName(a["modulation"], c.modulation)) { err = "unknown modulation"; return false; }
  }
  if (a["data_rate_kbps"].is<float>()) {
    float r = a["data_rate_kbps"];
    if (r < 0.6f || r > 500.0f) { err = "data_rate_kbps must be 0.6..500"; return false; }
    c.dataRateKbps = r;
  }
  if (a["deviation_khz"].is<float>()) {
    float d = a["deviation_khz"];
    if (d < 1.5f || d > 381.0f) { err = "deviation_khz must be 1.5..381"; return false; }
    c.deviationKhz = d;
  }
  if (a["rx_bandwidth_khz"].is<float>()) {
    float b = a["rx_bandwidth_khz"];
    if (b < 58.0f || b > 812.0f) { err = "rx_bandwidth_khz must be 58..812"; return false; }
    c.rxBandwidthKhz = b;
  }
  if (a["sync_word"].is<const char*>()) {
    const char* s = a["sync_word"];
    unsigned v;
    if (strlen(s) != 4 || sscanf(s, "%4x", &v) != 1) { err = "sync_word must be 4 hex digits"; return false; }
    c.syncWord[0] = v >> 8; c.syncWord[1] = v & 0xFF;
  }
  if (a["sync_required"].is<bool>()) c.syncRequired = a["sync_required"];
  if (a["crc"].is<bool>()) c.crcEnabled = a["crc"];
  if (a["max_packet_len"].is<int>()) {
    int l = a["max_packet_len"];
    if (l < 1 || l > 61) { err = "max_packet_len must be 1..61"; return false; }
    c.maxPacketLen = l;
  }
  return true;
}

void ProtocolHandler::dispatch(JsonDocument& req, JsonDocument& resp) {
  const char* cmd = req["cmd"] | "";
  JsonObjectConst args = req["args"].as<JsonObjectConst>();
  JsonObject data = resp["data"].to<JsonObject>();
  resp["ok"] = true;

  auto fail = [&](const char* code, const String& msg) {
    resp["ok"] = false;
    resp.remove("data");
    resp["error"]["code"] = code;
    resp["error"]["message"] = msg;
    cmdErrors_++;
  };

  if (!strcmp(cmd, "PING")) {
    data["pong"] = true;
  } else if (!strcmp(cmd, "GET_VERSION")) {
    data["fw"] = RFB_FW_NAME;
    data["version"] = RFB_FW_VERSION;
    data["proto"] = RFB_PROTO_VERSION;
    data["build"] = __DATE__ " " __TIME__;
  } else if (!strcmp(cmd, "DEVICE_INFO")) {
    data["fw"] = RFB_FW_NAME;
    data["version"] = RFB_FW_VERSION;
    data["proto"] = RFB_PROTO_VERSION;
    data["board"] = RFB_BOARD_NAME;
    data["chip_model"] = ESP.getChipModel();
    data["chip_rev"] = ESP.getChipRevision();
    data["mac"] = String((uint32_t)(ESP.getEfuseMac() >> 32), HEX) + String((uint32_t)ESP.getEfuseMac(), HEX);
    data["flash_bytes"] = ESP.getFlashChipSize();
    data["psram_bytes"] = ESP.getPsramSize();
    data["free_heap"] = ESP.getFreeHeap();
    data["uptime_ms"] = millis();
    data["radio"] = radio_.chipName();
    data["radio_version"] = radio_.chipVersion();
    data["simulation"] = (bool)RFB_SIMULATION;
    JsonObject p = data["pins"].to<JsonObject>();
    p["sck"] = RFB_PIN_SCK; p["mosi"] = RFB_PIN_MOSI; p["miso"] = RFB_PIN_MISO;
    p["cs"] = RFB_PIN_CS; p["gdo0"] = RFB_PIN_GDO0; p["gdo2"] = RFB_PIN_GDO2;
    data["reset_reason"] = (int)esp_reset_reason();
  } else if (!strcmp(cmd, "RADIO_STATUS")) {
    fillStatus(data);
  } else if (!strcmp(cmd, "SET_FREQUENCY")) {
    RadioConfig c = radio_.config();
    uint32_t hz = 0;
    if (args["hz"].is<uint32_t>()) hz = args["hz"];
    else if (args["mhz"].is<float>()) hz = mhzToHz(args["mhz"].as<double>());
    if (!hz) return fail("BAD_ARGS", "SET_FREQUENCY requires args.hz or args.mhz");
    if (!radio_.frequencySupported(hz)) return fail("UNSUPPORTED_FREQUENCY", "CC1101 bands: 300-348, 387-464, 779-928 MHz");
    c.frequencyHz = hz;
    if (!radio_.applyConfig(c)) return fail("RADIO_ERROR", radio_.lastError());
    data["frequency_hz"] = hz;
  } else if (!strcmp(cmd, "SET_MODULATION") || !strcmp(cmd, "SET_CONFIG")) {
    RadioConfig c = radio_.config();
    String err;
    if (args.isNull()) return fail("BAD_ARGS", "args object required");
    if (!applyConfigArgs(args, c, err)) return fail("BAD_ARGS", err);
    if (!radio_.frequencySupported(c.frequencyHz)) return fail("UNSUPPORTED_FREQUENCY", "frequency outside CC1101 bands");
    if (c.modulation == Modulation::FSK4 && c.dataRateKbps > 300) return fail("BAD_ARGS", "4-FSK max 300 kBaud");
    if (!radio_.applyConfig(c)) return fail("RADIO_ERROR", radio_.lastError());
    fillStatus(data);
  } else if (!strcmp(cmd, "START_RECEIVE")) {
    if (!radio_.present()) return fail("NO_RADIO", radio_.lastError());
    if (!radio_.startRx()) return fail("RADIO_ERROR", radio_.lastError());
    data["state"] = radioStateName(radio_.state());
  } else if (!strcmp(cmd, "STOP_RECEIVE")) {
    radio_.stopRx();
    data["state"] = radioStateName(radio_.state());
  } else if (!strcmp(cmd, "GET_RSSI")) {
    if (!radio_.present()) return fail("NO_RADIO", radio_.lastError());
    data["rssi_dbm"] = radio_.readRssiDbm();
    data["frequency_hz"] = radio_.config().frequencyHz;
  } else if (!strcmp(cmd, "RSSI_STREAM")) {
    int ms = args["interval_ms"] | 0;
    if (ms != 0 && (ms < 20 || ms > 10000)) return fail("BAD_ARGS", "interval_ms 0 (off) or 20..10000");
    rssiStreamMs_ = ms;
    data["interval_ms"] = ms;
  } else if (!strcmp(cmd, "RESET_RADIO")) {
    RadioConfig keep = radio_.config();
    bool ok = radio_.begin() && radio_.applyConfig(keep);
    if (!ok) return fail("RADIO_ERROR", radio_.lastError());
    fillStatus(data);
  } else if (!strcmp(cmd, "TX_TEST")) {
    // Controlled lab test signal: fixed "RFB-TEST-nnn" payload at ~-10 dBm.
    // No arbitrary payloads, no replay of captured data.
    if (!(args["confirm_authorized"] | false))
      return fail("NOT_AUTHORIZED", "set args.confirm_authorized=true to confirm lab use on a frequency you are licensed/permitted to use");
    int n = args["count"] | 1;
    if (n < 1 || n > kMaxTestPackets) return fail("BAD_ARGS", "count must be 1..10");
    if (!radio_.transmitTestPattern((uint8_t)n)) return fail("RADIO_ERROR", radio_.lastError());
    data["sent"] = n;
  } else if (!strcmp(cmd, "REBOOT")) {
    data["rebooting"] = true;
    emit(resp);
    io_.flush();
    delay(100);
    ESP.restart();
  } else {
    fail("UNKNOWN_COMMAND", String("unknown cmd: ") + cmd);
  }
}

void ProtocolHandler::handleLine(const char* line) {
  JsonDocument req;
  DeserializationError e = deserializeJson(req, line);
  if (e) { sendError(-1, "BAD_JSON", e.c_str()); return; }
  // Accept bare-word commands too, e.g. "DEVICE_INFO"
  if (!req.is<JsonObject>()) { sendError(-1, "BAD_JSON", "expected object"); return; }
  int id = req["id"] | -1;
  if (!req["cmd"].is<const char*>()) { sendError(id, "BAD_ARGS", "missing cmd"); return; }
  JsonDocument resp;
  resp["type"] = "response";
  if (id >= 0) resp["id"] = id;
  resp["cmd"] = req["cmd"].as<const char*>();
  dispatch(req, resp);
  emit(resp);
}

void ProtocolHandler::loop() {
  while (io_.available()) {
    int ch = io_.read();
    if (ch < 0) break;
    if (ch == '\r') continue;
    if (ch == '\n') {
      buf_[len_] = 0;
      if (overflow_) sendError(-1, "LINE_TOO_LONG", "max 511 bytes");
      else if (len_ > 0) {
        if (buf_[0] != '{') {           // plain-text convenience: "GET_VERSION"
          char tmp[sizeof(buf_) + 16];
          snprintf(tmp, sizeof(tmp), "{\"cmd\":\"%s\"}", buf_);
          handleLine(tmp);
        } else handleLine(buf_);
      }
      len_ = 0; overflow_ = false;
      continue;
    }
    if (len_ < sizeof(buf_) - 1) buf_[len_++] = (char)ch;
    else overflow_ = true;
  }

  RadioPacket p;
  if (radio_.poll(p)) {
    if (!p.crcOk) crcErrors_++;
    packets_++;
    JsonDocument d;
    d["n"] = packets_;
    d["ts_us"] = p.timestampUs;
    d["frequency_hz"] = radio_.config().frequencyHz;
    d["modulation"] = modulationName(radio_.config().modulation);
    d["len"] = p.len;
    d["rssi_dbm"] = p.rssiDbm;
    d["lqi"] = p.lqi;
    d["crc_ok"] = p.crcOk;
    char hex[64 * 2 + 1];
    for (uint8_t i = 0; i < p.len; i++) sprintf(hex + i * 2, "%02X", p.data[i]);
    hex[p.len * 2] = 0;
    d["data"] = hex;
    sendEvent("packet", d);
  }

  uint32_t now = millis();
  if (rssiStreamMs_ && now - lastRssi_ >= rssiStreamMs_ && radio_.present()) {
    lastRssi_ = now;
    JsonDocument d;
    d["rssi_dbm"] = radio_.readRssiDbm();
    d["frequency_hz"] = radio_.config().frequencyHz;
    sendEvent("rssi", d);
  }
  if (now - lastHeartbeat_ >= 5000) {
    lastHeartbeat_ = now;
    JsonDocument d;
    d["state"] = radioStateName(radio_.state());
    d["packets"] = packets_;
    d["free_heap"] = ESP.getFreeHeap();
    sendEvent("heartbeat", d);
  }
}
