#include "cc1101.h"
#include <math.h>
#include <esp_timer.h>

namespace {
// Config registers
enum : uint8_t {
  IOCFG2 = 0x00, IOCFG0 = 0x02, FIFOTHR = 0x03, SYNC1 = 0x04, SYNC0 = 0x05, PKTLEN = 0x06,
  PKTCTRL1 = 0x07, PKTCTRL0 = 0x08, ADDR = 0x09, CHANNR = 0x0A, FSCTRL1 = 0x0B, FSCTRL0 = 0x0C,
  FREQ2 = 0x0D, FREQ1 = 0x0E, FREQ0 = 0x0F, MDMCFG4 = 0x10, MDMCFG3 = 0x11, MDMCFG2 = 0x12,
  MDMCFG1 = 0x13, MDMCFG0 = 0x14, DEVIATN = 0x15, MCSM1 = 0x17, MCSM0 = 0x18, FOCCFG = 0x19,
  BSCFG = 0x1A, AGCCTRL2 = 0x1B, AGCCTRL1 = 0x1C, AGCCTRL0 = 0x1D, FREND1 = 0x21, FREND0 = 0x22,
  FSCAL3 = 0x23, FSCAL2 = 0x24, FSCAL1 = 0x25, FSCAL0 = 0x26, TEST2 = 0x2C, TEST1 = 0x2D,
  TEST0 = 0x2E, PATABLE = 0x3E, FIFO = 0x3F
};
// Strobes
enum : uint8_t { SRES = 0x30, SCAL = 0x33, SRX = 0x34, STX = 0x35, SIDLE = 0x36, SFRX = 0x3A, SFTX = 0x3B };
// Status registers (read with burst bit)
enum : uint8_t { PARTNUM = 0x30, VERSION = 0x31, LQI_REG = 0x33, RSSI_REG = 0x34, MARCSTATE = 0x35, RXBYTES = 0x3B };
constexpr uint8_t READ = 0x80, BURST = 0x40;
constexpr double FXOSC = 26000000.0;
}  // namespace

CC1101Radio::CC1101Radio(SPIClass& spi, int sck, int miso, int mosi, int cs, int gdo0, int gdo2)
    : spi_(spi), sck_(sck), miso_(miso), mosi_(mosi), cs_(cs), gdo0_(gdo0), gdo2_(gdo2),
      settings_(RFB_SPI_HZ, MSBFIRST, SPI_MODE0) {}

void CC1101Radio::select() { spi_.beginTransaction(settings_); digitalWrite(cs_, LOW); }
void CC1101Radio::deselect() { digitalWrite(cs_, HIGH); spi_.endTransaction(); }

bool CC1101Radio::waitMisoLow(uint32_t timeoutUs) {
  uint32_t t0 = micros();
  while (digitalRead(miso_)) {
    if (micros() - t0 > timeoutUs) return false;
  }
  return true;
}

uint8_t CC1101Radio::strobe(uint8_t cmd) {
  select(); waitMisoLow();
  uint8_t s = spi_.transfer(cmd);
  deselect();
  return s;
}
void CC1101Radio::writeReg(uint8_t a, uint8_t v) {
  select(); waitMisoLow(); spi_.transfer(a); spi_.transfer(v); deselect();
}
uint8_t CC1101Radio::readReg(uint8_t a) {
  select(); waitMisoLow(); spi_.transfer(a | READ); uint8_t v = spi_.transfer(0); deselect(); return v;
}
uint8_t CC1101Radio::readStatus(uint8_t a) {
  select(); waitMisoLow(); spi_.transfer(a | READ | BURST); uint8_t v = spi_.transfer(0); deselect(); return v;
}
void CC1101Radio::writeBurst(uint8_t a, const uint8_t* b, uint8_t n) {
  select(); waitMisoLow(); spi_.transfer(a | BURST);
  for (uint8_t i = 0; i < n; i++) spi_.transfer(b[i]);
  deselect();
}
void CC1101Radio::readBurst(uint8_t a, uint8_t* b, uint8_t n) {
  select(); waitMisoLow(); spi_.transfer(a | READ | BURST);
  for (uint8_t i = 0; i < n; i++) b[i] = spi_.transfer(0);
  deselect();
}

bool CC1101Radio::begin() {
  pinMode(cs_, OUTPUT);
  digitalWrite(cs_, HIGH);
  pinMode(gdo0_, INPUT);
  if (gdo2_ >= 0) pinMode(gdo2_, INPUT);
  spi_.begin(sck_, miso_, mosi_, -1);

  // Manual power-on reset sequence (datasheet 19.1.2)
  digitalWrite(cs_, LOW); delayMicroseconds(10);
  digitalWrite(cs_, HIGH); delayMicroseconds(45);
  spi_.beginTransaction(settings_);
  digitalWrite(cs_, LOW);
  if (!waitMisoLow(50000)) {
    digitalWrite(cs_, HIGH); spi_.endTransaction();
    err_ = "CC1101 not responding (MISO stuck high): check wiring/power";
    state_ = RadioState::Error; present_ = false;
    return false;
  }
  spi_.transfer(SRES);
  waitMisoLow(50000);
  digitalWrite(cs_, HIGH);
  spi_.endTransaction();
  delay(1);

  uint8_t part = readStatus(PARTNUM);
  version_ = readStatus(VERSION);
  if (version_ == 0x00 || version_ == 0xFF) {
    err_ = "CC1101 not detected (VERSION=0x" + String(version_, HEX) + "): check SPI pins";
    state_ = RadioState::Error; present_ = false;
    return false;
  }
  if (part != 0x00) {
    err_ = "Unexpected PARTNUM 0x" + String(part, HEX) + " (clone?) - continuing";
  } else {
    err_ = "";
  }
  present_ = true;
  state_ = RadioState::Idle;
  return applyConfig(cfg_);
}

bool CC1101Radio::frequencySupported(uint32_t hz) const {
  // CC1101 synthesizer bands (datasheet table 1).
  return (hz >= 300000000UL && hz <= 348000000UL) ||
         (hz >= 387000000UL && hz <= 464000000UL) ||
         (hz >= 779000000UL && hz <= 928000000UL);
}

void CC1101Radio::setFrequency(uint32_t hz) {
  uint32_t f = (uint32_t)llround((double)hz * 65536.0 / FXOSC);
  writeReg(FREQ2, (f >> 16) & 0xFF);
  writeReg(FREQ1, (f >> 8) & 0xFF);
  writeReg(FREQ0, f & 0xFF);
}

void CC1101Radio::setDataRate(float kbps) {
  double r = kbps * 1000.0;
  if (r < 600) r = 600;
  if (r > 500000) r = 500000;
  int e = (int)floor(log2(r * 1048576.0 / FXOSC));
  int m = (int)lround(r * 268435456.0 / (FXOSC * pow(2, e)) - 256.0);
  if (m >= 256) { m = 0; e++; }
  if (e < 0) e = 0;
  if (e > 15) e = 15;
  uint8_t m4 = readReg(MDMCFG4) & 0xF0;
  writeReg(MDMCFG4, m4 | (e & 0x0F));
  writeReg(MDMCFG3, (uint8_t)m);
}

void CC1101Radio::setRxBandwidth(float khz) {
  // Pick the narrowest filter >= requested.
  int bestE = 0, bestM = 0;
  double best = 1e12;
  for (int e = 0; e < 4; e++)
    for (int m = 0; m < 4; m++) {
      double bw = FXOSC / (8.0 * (4 + m) * pow(2, e)) / 1000.0;
      if (bw >= khz && bw < best) { best = bw; bestE = e; bestM = m; }
    }
  if (best == 1e12) { bestE = 0; bestM = 0; }  // request > 812 kHz: use max
  uint8_t m4 = readReg(MDMCFG4) & 0x0F;
  writeReg(MDMCFG4, (uint8_t)((bestE << 6) | (bestM << 4) | m4));
}

void CC1101Radio::setDeviation(float khz) {
  double target = khz * 1000.0, bestErr = 1e12;
  int be = 0, bm = 0;
  for (int e = 0; e < 8; e++)
    for (int m = 0; m < 8; m++) {
      double d = FXOSC / 131072.0 * (8 + m) * pow(2, e);
      double err = fabs(d - target);
      if (err < bestErr) { bestErr = err; be = e; bm = m; }
    }
  writeReg(DEVIATN, (uint8_t)((be << 4) | bm));
}

void CC1101Radio::setPaTable(uint32_t hz) {
  // Approx. -10 dBm settings (TI DN013). Deliberately low: lab bench use only.
  uint8_t p = 0x34;
  if (hz < 400000000UL) p = 0x34;
  else if (hz < 500000000UL) p = 0x34;
  else if (hz < 900000000UL) p = 0x26;
  else p = 0x27;
  uint8_t table[8] = {0};
  if (cfg_.modulation == Modulation::ASK_OOK) { table[0] = 0x00; table[1] = p; }
  else table[0] = p;
  writeBurst(PATABLE, table, 8);
}

bool CC1101Radio::applyConfig(const RadioConfig& c) {
  if (!frequencySupported(c.frequencyHz)) { err_ = "Frequency outside CC1101 bands"; return false; }
  if (c.maxPacketLen == 0 || c.maxPacketLen > 61) { err_ = "max_packet_len must be 1..61"; return false; }
  cfg_ = c;
  if (!present_) return true;  // stored; applied on next begin()
  bool wasRx = state_ == RadioState::Rx;
  strobe(SIDLE);

  writeReg(IOCFG2, 0x29);                    // CHIP_RDYn
  writeReg(IOCFG0, 0x06);                    // sync received .. end of packet
  writeReg(FIFOTHR, 0x47);
  writeReg(SYNC1, c.syncWord[0]);
  writeReg(SYNC0, c.syncWord[1]);
  writeReg(PKTLEN, c.maxPacketLen);
  writeReg(PKTCTRL1, 0x04);                  // append RSSI/LQI status, no addr check
  writeReg(PKTCTRL0, c.crcEnabled ? 0x05 : 0x01);  // variable length
  writeReg(ADDR, 0x00);
  writeReg(CHANNR, 0x00);
  writeReg(FSCTRL1, 0x06);
  writeReg(FSCTRL0, 0x00);
  setFrequency(c.frequencyHz);
  writeReg(MDMCFG4, 0x00);
  setRxBandwidth(c.rxBandwidthKhz);
  setDataRate(c.dataRateKbps);
  uint8_t syncMode = c.syncRequired ? 0x02 : 0x04;  // 16/16 sync OR carrier-sense only
  writeReg(MDMCFG2, (uint8_t)(((uint8_t)c.modulation << 4) | syncMode));
  writeReg(MDMCFG1, 0x22);                   // 4 preamble bytes
  writeReg(MDMCFG0, 0xF8);
  setDeviation(c.deviationKhz);
  writeReg(MCSM1, 0x30);                     // CCA; RX->IDLE after packet; TX->IDLE
  writeReg(MCSM0, 0x18);                     // autocal IDLE->RX/TX
  writeReg(FOCCFG, 0x16);
  writeReg(BSCFG, 0x6C);
  writeReg(AGCCTRL2, 0x43);
  writeReg(AGCCTRL1, 0x40);
  writeReg(AGCCTRL0, 0x91);
  writeReg(FREND1, 0x56);
  writeReg(FREND0, c.modulation == Modulation::ASK_OOK ? 0x11 : 0x10);
  writeReg(FSCAL3, 0xE9);
  writeReg(FSCAL2, 0x2A);
  writeReg(FSCAL1, 0x00);
  writeReg(FSCAL0, 0x1F);
  writeReg(TEST2, 0x81);
  writeReg(TEST1, 0x35);
  writeReg(TEST0, 0x09);
  setPaTable(c.frequencyHz);
  strobe(SCAL);
  delay(1);

  // Verify a write round-trip to catch flaky SPI.
  if (readReg(PKTLEN) != c.maxPacketLen) {
    err_ = "Register verify failed (SPI integrity)";
    state_ = RadioState::Error;
    return false;
  }
  state_ = RadioState::Idle;
  if (wasRx) startRx();
  return true;
}

void CC1101Radio::flushRx() { strobe(SIDLE); strobe(SFRX); }

bool CC1101Radio::startRx() {
  if (!present_) { err_ = "Radio not present"; return false; }
  flushRx();
  strobe(SRX);
  state_ = RadioState::Rx;
  return true;
}

bool CC1101Radio::stopRx() {
  if (!present_) return false;
  flushRx();
  state_ = RadioState::Idle;
  return true;
}

float CC1101Radio::rawToDbm(uint8_t raw) {
  return raw >= 128 ? ((int)raw - 256) / 2.0f - 74.0f : raw / 2.0f - 74.0f;
}

float CC1101Radio::readRssiDbm() {
  if (!present_) return NAN;
  return rawToDbm(readStatus(RSSI_REG));
}

bool CC1101Radio::poll(RadioPacket& out) {
  if (!present_ || state_ != RadioState::Rx) return false;
  uint8_t marc = readStatus(MARCSTATE) & 0x1F;
  uint8_t rxb = readStatus(RXBYTES);
  if (rxb & 0x80 || marc == 0x11) {          // RXFIFO overflow
    flushRx(); strobe(SRX);
    return false;
  }
  uint8_t n = rxb & 0x7F;
  // Packet is complete once the radio dropped back to IDLE (MCSM1 RXOFF=IDLE).
  if (marc != 0x01 || n == 0) {
    if (marc == 0x01) strobe(SRX);           // idle with nothing: re-arm
    return false;
  }
  uint8_t len = readReg(FIFO);
  if (len == 0 || len > cfg_.maxPacketLen || len + 3 > n) {
    flushRx(); strobe(SRX);
    return false;
  }
  readBurst(FIFO, out.data, len);
  uint8_t st[2];
  readBurst(FIFO, st, 2);
  out.len = len;
  out.rssiDbm = rawToDbm(st[0]);
  out.lqi = st[1] & 0x7F;
  out.crcOk = cfg_.crcEnabled ? (st[1] & 0x80) : true;
  out.timestampUs = esp_timer_get_time();
  flushRx(); strobe(SRX);
  return true;
}

bool CC1101Radio::transmitTestPattern(uint8_t count) {
  if (!present_) { err_ = "Radio not present"; return false; }
  bool wasRx = state_ == RadioState::Rx;
  state_ = RadioState::Tx;
  for (uint8_t i = 0; i < count; i++) {
    char payload[20];
    int n = snprintf(payload, sizeof(payload), "RFB-TEST-%03u", i);
    strobe(SIDLE); strobe(SFTX);
    uint8_t len = (uint8_t)n;
    writeReg(FIFO, len);
    writeBurst(FIFO, (const uint8_t*)payload, len);
    strobe(STX);
    uint32_t t0 = millis();
    while ((readStatus(MARCSTATE) & 0x1F) != 0x01) {
      if (millis() - t0 > 500) { strobe(SIDLE); strobe(SFTX); err_ = "TX timeout"; state_ = RadioState::Idle; return false; }
      delay(1);
    }
    delay(50);
  }
  state_ = RadioState::Idle;
  if (wasRx) startRx();
  return true;
}
