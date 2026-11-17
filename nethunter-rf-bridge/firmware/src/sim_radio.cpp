#include "sim_radio.h"
#include <math.h>
#include <esp_timer.h>

bool SimRadio::frequencySupported(uint32_t hz) const {
  return (hz >= 300000000UL && hz <= 348000000UL) || (hz >= 387000000UL && hz <= 464000000UL) ||
         (hz >= 779000000UL && hz <= 928000000UL);
}

float SimRadio::readRssiDbm() {
  float noise = -105.0f + (float)(esp_random() % 80) / 10.0f;
  if (state_ == RadioState::Rx && (int32_t)(next_ - millis()) < 30) noise += 40.0f;  // burst approaching
  return noise;
}

bool SimRadio::poll(RadioPacket& out) {
  if (state_ != RadioState::Rx || (int32_t)(millis() - next_) < 0) return false;
  // Alternate between a repeating "sensor" frame and random-noise frames
  // so the host-side repeat/unknown classification can be exercised.
  counter_++;
  if (counter_ % 3 != 0) {
    const uint8_t frame[] = {0xA5, 0x01, 0x42, 0x17, (uint8_t)(counter_ / 10), 0x5A};
    memcpy(out.data, frame, sizeof(frame));
    out.len = sizeof(frame);
  } else {
    out.len = 4 + esp_random() % 12;
    for (uint8_t i = 0; i < out.len; i++) out.data[i] = esp_random() & 0xFF;
  }
  out.rssiDbm = -60.0f - (float)(esp_random() % 300) / 10.0f;
  out.lqi = esp_random() % 48;
  out.crcOk = true;
  out.timestampUs = esp_timer_get_time();
  next_ = millis() + 700 + esp_random() % 1300;
  return true;
}
