// Host-native tests for firmware protocol + drivers (no hardware needed).
#include <cassert>
#include <iostream>
#include "protocol.h"
#include "cc1101.h"
#include "protocol.h"
#include "sim_radio.h"

static int fails = 0;
#define CHECK(c) do { if (!(c)) { std::cerr << "FAIL line " << __LINE__ << ": " #c "\n"; fails++; } } while (0)

static JsonDocument lastResponse(FakeSerial& s) {
  // scan output lines from the end for a response
  JsonDocument d;
  size_t end = s.out.size();
  while (end > 0) {
    size_t start = s.out.rfind('\n', end - 2);
    start = (start == std::string::npos) ? 0 : start + 1;
    std::string line = s.out.substr(start, end - start);
    if (!deserializeJson(d, line) && d["type"] == "response") return d;
    if (start == 0) break;
    end = start;
  }
  d.clear();
  return d;
}

static JsonDocument cmd(FakeSerial& s, ProtocolHandler& p, const std::string& line) {
  s.feed(line + "\n");
  p.loop();
  return lastResponse(s);
}

int main() {
  // --- protocol over simulated radio
  SimRadio sim;
  sim.begin();
  FakeSerial io;
  ProtocolHandler proto(io, sim);
  proto.begin();
  CHECK(io.out.find("\"type\":\"hello\"") != std::string::npos);

  auto r = cmd(io, proto, R"({"id":1,"cmd":"GET_VERSION"})");
  CHECK(r["ok"] == true);
  CHECK(r["id"] == 1);
  CHECK(r["data"]["fw"] == "nethunter-rf-bridge");

  r = cmd(io, proto, "DEVICE_INFO");  // bare-word form
  CHECK(r["ok"] == true && r["data"]["pins"]["sck"].is<int>());

  r = cmd(io, proto, R"({"id":2,"cmd":"SET_FREQUENCY","args":{"mhz":868.3}})");
  if (!(r["ok"] == true && r["data"]["frequency_hz"] == 868300000)) serializeJson(r, std::cerr);
  CHECK(r["ok"] == true && r["data"]["frequency_hz"] == 868300000);

  r = cmd(io, proto, R"({"id":3,"cmd":"SET_FREQUENCY","args":{"mhz":2400}})");
  CHECK(r["ok"] == false && r["error"]["code"] == "UNSUPPORTED_FREQUENCY");

  r = cmd(io, proto, R"({"id":4,"cmd":"SET_CONFIG","args":{"modulation":"GFSK","data_rate_kbps":38.4,"sync_word":"2DD4"}})");
  CHECK(r["ok"] == true && r["data"]["modulation"] == "GFSK" && r["data"]["sync_word"] == "2DD4");

  r = cmd(io, proto, R"({"id":5,"cmd":"SET_CONFIG","args":{"modulation":"QAM"}})");
  CHECK(r["ok"] == false && r["error"]["code"] == "BAD_ARGS");

  r = cmd(io, proto, R"({"id":6,"cmd":"TX_TEST","args":{"count":3}})");
  CHECK(r["ok"] == false && r["error"]["code"] == "NOT_AUTHORIZED");

  r = cmd(io, proto, R"({"id":7,"cmd":"NOPE"})");
  CHECK(r["error"]["code"] == "UNKNOWN_COMMAND");

  r = cmd(io, proto, R"({"id":8,"cmd":)");
  CHECK(r["error"]["code"] == "BAD_JSON");

  std::string big(600, 'x');
  r = cmd(io, proto, big);
  CHECK(r["error"]["code"] == "LINE_TOO_LONG");

  r = cmd(io, proto, R"({"id":9,"cmd":"START_RECEIVE"})");
  CHECK(r["ok"] == true && r["data"]["state"] == "receiving");
  r = cmd(io, proto, R"({"id":10,"cmd":"GET_RSSI"})");
  CHECK(r["ok"] == true && r["data"]["rssi_dbm"].as<float>() < 0);

  // --- real CC1101 driver against the emulated register file
  SPIClass spi;
  CC1101Radio cc(spi, 12, 13, 11, 10, 4, 5);
  CHECK(cc.begin());
  CHECK(cc.present() && cc.chipVersion() == 0x14);
  RadioConfig c;
  c.frequencyHz = 433920000;
  CHECK(cc.applyConfig(c));
  uint32_t f = (spi.regs[0x0D] << 16) | (spi.regs[0x0E] << 8) | spi.regs[0x0F];
  CHECK(f == 0x10B071);                     // 433.92 MHz per TI SmartRF
  CHECK((spi.regs[0x12] >> 4) == 3);        // ASK/OOK
  CHECK(spi.regs[0x11] == 0x83 && (spi.regs[0x10] & 0x0F) == 0x07);  // 4.8 kBaud: E=7 M=0x83
  CHECK(spi.patable[1] != 0 && spi.patable[0] == 0);  // OOK: PATABLE[0]=off
  c.frequencyHz = 500000000;
  CHECK(!cc.applyConfig(c));
  c.frequencyHz = 868000000; c.modulation = Modulation::GFSK; c.dataRateKbps = 38.38f;
  CHECK(cc.applyConfig(c));
  CHECK(spi.regs[0x11] == 0x83 && (spi.regs[0x10] & 0x0F) == 0x0A);  // 38.38 kBaud
  CHECK(cc.startRx() && cc.state() == RadioState::Rx);
  float rssi = cc.readRssiDbm();
  CHECK(rssi == -74.0f);

  SPIClass deadSpi;
  deadSpi.present = false;  // MISO stuck high
  CC1101Radio missing(deadSpi, 12, 13, 11, 10, 4, 5);
  CHECK(!missing.begin());
  CHECK(missing.lastError().length() > 0);

  if (fails) { std::cerr << fails << " native firmware test(s) failed\n"; return 1; }
  std::cout << "native firmware tests: all passed\n";
  return 0;
}
