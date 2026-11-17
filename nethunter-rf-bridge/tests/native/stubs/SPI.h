#pragma once
#include "Arduino.h"
#define FSPI 0
struct SPISettings { SPISettings(uint32_t, int, int) {} SPISettings() {} };
// Emulates the CC1101 register file so the real driver can be exercised.
class SPIClass {
 public:
  explicit SPIClass(int = 0) {}
  void begin(int, int, int, int) {}
  void beginTransaction(const SPISettings&) { idx_ = 0; }
  void endTransaction() {}
  uint8_t transfer(uint8_t b);
  uint8_t regs[0x30] = {0};
  uint8_t patable[8] = {0};
  uint8_t version = 0x14;
  bool present = true;
 private:
  int idx_ = 0;
  uint8_t hdr_ = 0;
};
