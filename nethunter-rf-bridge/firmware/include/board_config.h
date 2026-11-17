// GPIO configuration. EVERY pin is defined per board; nothing is assumed
// to be identical across ESP32 models. Override any value with -D flags.
//
// ESP32-S3 pins to AVOID:
//   GPIO0, 3, 45, 46       strapping pins
//   GPIO19, 20             native USB D-/D+ (our USB-C link!)
//   GPIO26-32              SPI flash
//   GPIO33-37              octal PSRAM on N8R8/N16R8 modules
//   GPIO43, 44             UART0 TX/RX
//   GPIO48 (DevKitC v1.1)  / GPIO38 (v1.0): onboard RGB LED
#pragma once

#ifndef RFB_SIMULATION
#define RFB_SIMULATION 0
#endif

#if defined(RFB_BOARD_DEVKITC1) || defined(RFB_BOARD_GENERIC_S3)
  #define RFB_BOARD_NAME "ESP32-S3-DevKitC-1"
  // FSPI (SPI2) via GPIO matrix
  #ifndef RFB_PIN_SCK
    #define RFB_PIN_SCK   12
  #endif
  #ifndef RFB_PIN_MOSI
    #define RFB_PIN_MOSI  11
  #endif
  #ifndef RFB_PIN_MISO
    #define RFB_PIN_MISO  13
  #endif
  #ifndef RFB_PIN_CS
    #define RFB_PIN_CS    10
  #endif
  #ifndef RFB_PIN_GDO0
    #define RFB_PIN_GDO0  4
  #endif
  #ifndef RFB_PIN_GDO2
    #define RFB_PIN_GDO2  5
  #endif
  #ifndef RFB_PIN_OLED_SDA
    #define RFB_PIN_OLED_SDA 8
  #endif
  #ifndef RFB_PIN_OLED_SCL
    #define RFB_PIN_OLED_SCL 9
  #endif
#elif defined(RFB_BOARD_C3_DEVKITM)
  #define RFB_BOARD_NAME "ESP32-C3-DevKitM-1"
  // C3: avoid GPIO2/8/9 (strapping), 11-17 (flash), 18/19 (USB)
  #ifndef RFB_PIN_SCK
    #define RFB_PIN_SCK   6
  #endif
  #ifndef RFB_PIN_MOSI
    #define RFB_PIN_MOSI  7
  #endif
  #ifndef RFB_PIN_MISO
    #define RFB_PIN_MISO  5
  #endif
  #ifndef RFB_PIN_CS
    #define RFB_PIN_CS    10
  #endif
  #ifndef RFB_PIN_GDO0
    #define RFB_PIN_GDO0  3
  #endif
  #ifndef RFB_PIN_GDO2
    #define RFB_PIN_GDO2  4
  #endif
  #ifndef RFB_PIN_OLED_SDA
    #define RFB_PIN_OLED_SDA 1
  #endif
  #ifndef RFB_PIN_OLED_SCL
    #define RFB_PIN_OLED_SCL 0
  #endif
#else
  #error "No board selected: define RFB_BOARD_DEVKITC1, RFB_BOARD_GENERIC_S3 or RFB_BOARD_C3_DEVKITM"
#endif

#define RFB_SPI_HZ 4000000   // CC1101 max 10 MHz (6.5 MHz burst); 4 MHz is safe on jumper wires

#if defined(CONFIG_IDF_TARGET_ESP32S3)
  // Compile-time guard against the pins that would break USB, flash or boot.
  #define RFB_BAD_PIN(p) ((p)==0||(p)==3||(p)==19||(p)==20||(p)==45||(p)==46||((p)>=26&&(p)<=32)||(p)>48)
  static_assert(!RFB_BAD_PIN(RFB_PIN_SCK),  "SCK on reserved pin");
  static_assert(!RFB_BAD_PIN(RFB_PIN_MOSI), "MOSI on reserved pin");
  static_assert(!RFB_BAD_PIN(RFB_PIN_MISO), "MISO on reserved pin");
  static_assert(!RFB_BAD_PIN(RFB_PIN_CS),   "CS on reserved pin");
  static_assert(!RFB_BAD_PIN(RFB_PIN_GDO0), "GDO0 on reserved pin");
  static_assert(!RFB_BAD_PIN(RFB_PIN_GDO2), "GDO2 on reserved pin");
#endif
