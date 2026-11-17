#pragma once
#include <SPI.h>
#include "board_config.h"
#include "radio_hal.h"

// Register-level CC1101 driver (TI SWRS061I).
class CC1101Radio : public RadioHAL {
 public:
  CC1101Radio(SPIClass& spi, int sck, int miso, int mosi, int cs, int gdo0, int gdo2);
  const char* chipName() const override { return "CC1101"; }
  bool begin() override;
  bool present() const override { return present_; }
  String lastError() const override { return err_; }
  uint8_t chipVersion() const override { return version_; }
  bool applyConfig(const RadioConfig& c) override;
  const RadioConfig& config() const override { return cfg_; }
  bool frequencySupported(uint32_t hz) const override;
  bool startRx() override;
  bool stopRx() override;
  RadioState state() const override { return state_; }
  float readRssiDbm() override;
  bool poll(RadioPacket& out) override;
  bool transmitTestPattern(uint8_t count) override;

 private:
  void select();
  void deselect();
  bool waitMisoLow(uint32_t timeoutUs = 20000);
  uint8_t strobe(uint8_t cmd);
  void writeReg(uint8_t addr, uint8_t v);
  uint8_t readReg(uint8_t addr);
  uint8_t readStatus(uint8_t addr);
  void writeBurst(uint8_t addr, const uint8_t* buf, uint8_t n);
  void readBurst(uint8_t addr, uint8_t* buf, uint8_t n);
  void setFrequency(uint32_t hz);
  void setDataRate(float kbps);
  void setRxBandwidth(float khz);
  void setDeviation(float khz);
  void setPaTable(uint32_t hz);
  void flushRx();
  static float rawToDbm(uint8_t raw);

  SPIClass& spi_;
  int sck_, miso_, mosi_, cs_, gdo0_, gdo2_;
  SPISettings settings_;
  RadioConfig cfg_;
  RadioState state_ = RadioState::Uninit;
  bool present_ = false;
  uint8_t version_ = 0;
  String err_;
};
