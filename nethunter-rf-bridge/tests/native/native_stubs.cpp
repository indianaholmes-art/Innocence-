#include <chrono>
#include "Arduino.h"
#include "SPI.h"
#include "esp_timer.h"

FakeSerial Serial;
EspClass ESP;
static auto T0 = std::chrono::steady_clock::now();
static int64_t us() { return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - T0).count(); }
int64_t esp_timer_get_time() { return us(); }
uint32_t millis() { return (uint32_t)(us() / 1000); }
uint32_t micros() { return (uint32_t)us(); }
void delay(uint32_t) {}
void delayMicroseconds(uint32_t) {}
void pinMode(int, int) {}
void digitalWrite(int, int) {}
int digitalRead(int) { return 0; }
uint32_t esp_random() { return (uint32_t)rand(); }

uint8_t SPIClass::transfer(uint8_t b) {
  if (!present) return 0xFF;
  if (idx_++ == 0) { hdr_ = b; return 0x0F; }
  uint8_t addr = hdr_ & 0x3F;
  bool rd = hdr_ & 0x80, burst = hdr_ & 0x40;
  if (addr == 0x3E) { return rd ? patable[0] : (patable[(idx_ - 2) & 7] = b, 0); }
  if (addr == 0x3F) return 0;  // FIFO
  if (addr >= 0x30) {          // status regs (burst read)
    if (addr == 0x31) return version;
    if (addr == 0x35) return 0x01;  // MARCSTATE idle
    return 0;
  }
  uint8_t a = burst ? addr + idx_ - 2 : addr;
  if (rd) return regs[a];
  regs[a] = b;
  return 0;
}
