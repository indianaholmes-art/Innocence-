// Radio hardware abstraction layer. Every radio (CC1101, simulator, future
// SX127x/LoRa, second CC1101...) implements this interface; protocol code
// never touches registers directly.
#pragma once
#include <Arduino.h>

enum class Modulation : uint8_t { FSK2 = 0, GFSK = 1, ASK_OOK = 3, FSK4 = 4, MSK = 7 };

const char* modulationName(Modulation m);
bool modulationFromName(const char* s, Modulation& out);

struct RadioConfig {
  uint32_t frequencyHz = 433920000;
  Modulation modulation = Modulation::ASK_OOK;
  float dataRateKbps = 4.8f;
  float deviationKhz = 47.6f;
  float rxBandwidthKhz = 203.0f;
  uint8_t syncWord[2] = {0xD3, 0x91};
  bool syncRequired = true;     // false => carrier-sense mode (noisier)
  uint8_t maxPacketLen = 61;    // variable-length packets
  bool crcEnabled = false;
};

struct RadioPacket {
  uint8_t data[64];
  uint8_t len = 0;
  float rssiDbm = 0;
  uint8_t lqi = 0;
  bool crcOk = false;
  uint64_t timestampUs = 0;
};

enum class RadioState : uint8_t { Uninit, Idle, Rx, Tx, Error };
const char* radioStateName(RadioState s);

class RadioHAL {
 public:
  virtual ~RadioHAL() = default;
  virtual const char* chipName() const = 0;
  virtual bool begin() = 0;                       // detect + reset
  virtual bool present() const = 0;
  virtual String lastError() const = 0;
  virtual uint8_t chipVersion() const = 0;
  virtual bool applyConfig(const RadioConfig& c) = 0;
  virtual const RadioConfig& config() const = 0;
  virtual bool frequencySupported(uint32_t hz) const = 0;
  virtual bool startRx() = 0;
  virtual bool stopRx() = 0;
  virtual RadioState state() const = 0;
  virtual float readRssiDbm() = 0;
  virtual bool poll(RadioPacket& out) = 0;        // true when packet available
  // Lab test signal only: fixed, non-replay pattern, capped length.
  virtual bool transmitTestPattern(uint8_t count) = 0;
};
