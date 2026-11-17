#pragma once
#include "radio_hal.h"

// Simulated radio: lets the whole stack run without a CC1101 attached.
class SimRadio : public RadioHAL {
 public:
  const char* chipName() const override { return "SIM-CC1101"; }
  bool begin() override { state_ = RadioState::Idle; return true; }
  bool present() const override { return true; }
  String lastError() const override { return ""; }
  uint8_t chipVersion() const override { return 0x14; }
  bool applyConfig(const RadioConfig& c) override { cfg_ = c; return true; }
  const RadioConfig& config() const override { return cfg_; }
  bool frequencySupported(uint32_t hz) const override;
  bool startRx() override { state_ = RadioState::Rx; next_ = millis() + 500; return true; }
  bool stopRx() override { state_ = RadioState::Idle; return true; }
  RadioState state() const override { return state_; }
  float readRssiDbm() override;
  bool poll(RadioPacket& out) override;
  bool transmitTestPattern(uint8_t) override { return true; }
 private:
  RadioConfig cfg_;
  RadioState state_ = RadioState::Uninit;
  uint32_t next_ = 0;
  uint32_t counter_ = 0;
};
