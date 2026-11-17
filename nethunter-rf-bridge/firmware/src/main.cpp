// NetHunter RF Bridge - ESP32-S3 + CC1101 USB-C firmware
#include <Arduino.h>
#include <SPI.h>
#include "board_config.h"
#include "protocol.h"
#include "version.h"

#ifndef RFB_SIMULATION
#define RFB_SIMULATION 0
#endif

#if RFB_SIMULATION
  #include "sim_radio.h"
  static SimRadio radio;
#else
  #include "cc1101.h"
  static SPIClass rfSpi(FSPI);
  static CC1101Radio radio(rfSpi, RFB_PIN_SCK, RFB_PIN_MISO, RFB_PIN_MOSI, RFB_PIN_CS,
                           RFB_PIN_GDO0, RFB_PIN_GDO2);
#endif

static ProtocolHandler proto(Serial, radio);

void setup() {
  Serial.setRxBufferSize(1024);
  Serial.begin(115200);  // baud ignored on native USB CDC
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 1500) delay(10);
  radio.begin();  // failure is reported via hello/RADIO_STATUS, not fatal
  proto.begin();
}

void loop() {
  proto.loop();
  delay(1);
}
