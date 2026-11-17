// Minimal Arduino core stub for host-native compilation of the firmware.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <strings.h>
#include <string>
#include <deque>
#include <cmath>

#define HEX 16
#define DEC 10
#define LOW 0
#define HIGH 1
#define INPUT 0
#define OUTPUT 1
#define MSBFIRST 1
#define SPI_MODE0 0

uint32_t millis();
uint32_t micros();
void delay(uint32_t);
void delayMicroseconds(uint32_t);
void pinMode(int, int);
void digitalWrite(int, int);
int digitalRead(int);
uint32_t esp_random();

class String {
 public:
  String(const char* s = "") : s_(s ? s : "") {}
  String(const std::string& s) : s_(s) {}
  String(unsigned v, int base = DEC) { char b[34]; snprintf(b, sizeof b, base == HEX ? "%x" : "%u", v); s_ = b; }
  String(int v, int base = DEC) : String((unsigned)v, base) { if (base == DEC) s_ = std::to_string(v); }
  String(unsigned char v, int base = DEC) : String((unsigned)v, base) {}
  String(uint32_t v, int base, int) : String((unsigned)v, base) {}
  const char* c_str() const { return s_.c_str(); }
  size_t length() const { return s_.size(); }
  bool concat(const char* s, size_t n) { s_.append(s, n); return true; }
  bool concat(const char* s) { s_ += s; return true; }
  bool concat(char c) { s_.push_back(c); return true; }
  String& operator+=(const String& o) { s_ += o.s_; return *this; }
  friend String operator+(const String& a, const String& b) { return String(a.s_ + b.s_); }
  friend String operator+(const String& a, const char* b) { return String(a.s_ + b); }
  friend String operator+(const char* a, const String& b) { return String(a + b.s_); }
  bool operator==(const String& o) const { return s_ == o.s_; }
  char operator[](size_t i) const { return s_[i]; }
 private:
  std::string s_;
};

class Print {
 public:
  virtual ~Print() = default;
  virtual size_t write(uint8_t c) = 0;
  virtual size_t write(const uint8_t* b, size_t n) { for (size_t i = 0; i < n; i++) write(b[i]); return n; }
  size_t write(const char* s) { return write((const uint8_t*)s, strlen(s)); }
  virtual void flush() {}
};

class Printable {
 public:
  virtual ~Printable() = default;
  virtual size_t printTo(Print& p) const = 0;
};

class Stream : public Print {
 public:
  virtual int available() = 0;
  virtual int read() = 0;
  virtual int peek() { return -1; }
  size_t readBytes(char* b, size_t n) { size_t i = 0; for (; i < n; i++) { int c = read(); if (c < 0) break; b[i] = c; } return i; }
  void setTimeout(unsigned long) {}
};

// Fake serial: input queue + captured output (tests drive it directly).
class FakeSerial : public Stream {
 public:
  std::deque<uint8_t> in;
  std::string out;
  int available() override { return (int)in.size(); }
  int read() override { if (in.empty()) return -1; int c = in.front(); in.pop_front(); return c; }
  size_t write(uint8_t c) override { out.push_back((char)c); return 1; }
  using Print::write;
  void feed(const std::string& s) { for (char c : s) in.push_back((uint8_t)c); }
  void begin(unsigned long) {}
  void setRxBufferSize(size_t) {}
  explicit operator bool() const { return true; }
};
extern FakeSerial Serial;

struct EspClass {
  const char* getChipModel() { return "ESP32-S3 (native-test)"; }
  uint8_t getChipRevision() { return 0; }
  uint64_t getEfuseMac() { return 0x0000AABBCCDDEEFFULL; }
  uint32_t getFlashChipSize() { return 8u << 20; }
  uint32_t getPsramSize() { return 0; }
  uint32_t getFreeHeap() { return 123456; }
  void restart() { std::exit(0); }
};
extern EspClass ESP;
