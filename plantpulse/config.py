"""Shared settings for every PlantPulse program.

Values come from environment variables or from a local ``.env`` file at the
repository root. The defaults match the project plan, so a standard install
needs no configuration. Import from here instead of repeating a topic name,
a pin number or a path in each program.
"""

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path):
    """Copy KEY=VALUE lines from ``path`` into the environment.

    Variables that are already set win, so systemd or the shell can override
    the file.
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _env_int(name, default):
    """Read an integer setting; accepts decimal or 0x-prefixed values."""
    return int(os.environ.get(name, str(default)), 0)


_load_env_file(ROOT_DIR / ".env")

# Identity
DEVICE_ID = os.environ.get("PLANTPULSE_DEVICE_ID", "plantpulse-school01-plant01")

# MQTT: the broker runs on the Pi itself
MQTT_HOST = os.environ.get("PLANTPULSE_MQTT_HOST", "localhost")
MQTT_PORT = _env_int("PLANTPULSE_MQTT_PORT", 1883)
TOPIC_BASE = "plantpulse/school01/plant01"
TOPIC_TELEMETRY = TOPIC_BASE + "/telemetry"  # one reading, not retained
TOPIC_STATE = TOPIC_BASE + "/state"          # state and reason, retained
TOPIC_STATUS = TOPIC_BASE + "/status"        # online / offline, retained

# Acquisition
READ_INTERVAL_S = _env_int("PLANTPULSE_READ_INTERVAL_S", 300)
# A relative path is taken from the repository root, not the current directory.
DATA_DIR = ROOT_DIR / os.environ.get("PLANTPULSE_DATA_DIR", "data")
READINGS_CSV = DATA_DIR / "readings.csv"

# Grove ports on the Base HAT (confirm against the wiring, T-05)
ADC_I2C_ADDRESS = _env_int("PLANTPULSE_ADC_I2C_ADDRESS", 0x08)
SOIL_ADC_CHANNEL = _env_int("PLANTPULSE_SOIL_ADC_CHANNEL", 0)    # port A0
LIGHT_ADC_CHANNEL = _env_int("PLANTPULSE_LIGHT_ADC_CHANNEL", 2)  # port A2
DHT_TYPE = os.environ.get("PLANTPULSE_DHT_TYPE", "11")  # "11" digital, "20" I2C
DHT_PIN = _env_int("PLANTPULSE_DHT_PIN", 5)             # port D5, DHT11 only
LED_BAR_PIN = _env_int("PLANTPULSE_LED_BAR_PIN", 16)    # port D16
