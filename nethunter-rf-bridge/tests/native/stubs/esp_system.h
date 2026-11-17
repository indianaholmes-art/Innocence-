#pragma once
typedef enum { ESP_RST_POWERON = 1 } esp_reset_reason_t;
inline esp_reset_reason_t esp_reset_reason() { return ESP_RST_POWERON; }
