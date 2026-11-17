"""Configuration file loading/validation (config/*.json)."""
from __future__ import annotations

import json
from pathlib import Path

ALLOWED_RADIO_KEYS = {"frequency_mhz", "frequency_hz", "modulation", "data_rate_kbps", "deviation_khz",
                      "rx_bandwidth_khz", "sync_word", "sync_required", "crc", "max_packet_len"}


class ConfigError(ValueError):
    pass


def load_config(path: Path) -> dict:
    try:
        cfg = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"cannot read config {path}: {e}") from e
    radio = cfg.get("radio", {})
    unknown = set(radio) - ALLOWED_RADIO_KEYS
    if unknown:
        raise ConfigError(f"unknown radio keys: {sorted(unknown)}")
    return cfg
