#pragma once
#include <ArduinoJson.h>
#include "radio_hal.h"

// Newline-delimited JSON over USB CDC. See docs/PROTOCOL.md.
class ProtocolHandler {
 public:
  ProtocolHandler(Stream& io, RadioHAL& radio);
  void begin();
  void loop();
 private:
  void handleLine(const char* line);
  void dispatch(JsonDocument& req, JsonDocument& resp);
  void sendEvent(const char* type, JsonDocument& doc);
  void sendError(int id, const char* code, const char* msg);
  void emit(JsonDocument& doc);
  void fillStatus(JsonObject o);

  Stream& io_;
  RadioHAL& radio_;
  char buf_[512];
  size_t len_ = 0;
  bool overflow_ = false;
  uint32_t packets_ = 0, crcErrors_ = 0, cmdErrors_ = 0;
  uint32_t rssiStreamMs_ = 0, lastRssi_ = 0, lastHeartbeat_ = 0;
  uint32_t seq_ = 0;
};
