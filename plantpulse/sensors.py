"""Read the four PlantPulse sensors and validate every value.

A read that fails, or a value outside its physical range, is returned as
``None`` (JSON ``null``). It is never replaced by zero or by an older value,
so the rule engine can tell "no data" apart from a real measurement.

Run ``python -m plantpulse.sensors`` on the Pi to print one reading.
"""

from __future__ import annotations

import json
import logging
import math

from plantpulse import config

log = logging.getLogger(__name__)

# Physical limits of each value. Anything outside means a broken read.
VALID_RANGES = {
    "temperature_c": (-40.0, 80.0),
    "humidity_pct": (0.0, 100.0),
    "soil_moisture_raw": (0, 3300),  # mV on the 3.3 V ADC
    "light_pct": (0.0, 100.0),
}

DHT_ATTEMPTS = 15  # a DHT11 often needs several tries for one valid frame


class SensorReadError(Exception):
    """A sensor did not answer or sent an unusable frame."""


def validate(name, value):
    """Return ``value`` if it is a finite number inside its range, else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    low, high = VALID_RANGES[name]
    if not low <= value <= high:
        return None
    return value


class GroveSensors:
    """The real sensors on the Grove Base HAT.

    The Grove libraries are imported here, not at module level, so the rest
    of this module also works on a laptop. Each device is opened on its first
    read: a sensor that is unplugged at start-up gives None for that cycle
    and is tried again on the next one.
    """

    def __init__(
        self,
        adc_address=config.ADC_I2C_ADDRESS,
        soil_channel=config.SOIL_ADC_CHANNEL,
        light_channel=config.LIGHT_ADC_CHANNEL,
        dht_type=config.DHT_TYPE,
        dht_pin=config.DHT_PIN,
    ):
        if dht_type not in ("11", "20"):
            raise ValueError(f"DHT type must be '11' or '20', not {dht_type!r}")

        from grove.adc import ADC

        if dht_type == "20":
            from grove.grove_temperature_humidity_aht20 import (
                GroveTemperatureHumidityAHT20 as dht_class,
            )
        else:
            from seeed_dht import DHT as dht_class

        self._adc_class = ADC
        self._dht_class = dht_class
        self._adc_address = adc_address
        self._soil_channel = soil_channel
        self._light_channel = light_channel
        self._dht_type = dht_type
        self._dht_pin = dht_pin
        self._adc = None
        self._dht = None

    def soil_moisture_raw(self):
        """Soil probe voltage in mV. Calibration turns it into a percentage."""
        return self._read_adc("read_voltage", self._soil_channel)

    def light_pct(self):
        """Relative light level, 0 to 100."""
        # The ADC reports the ratio to the supply voltage in steps of 0.1 %.
        return self._read_adc("read", self._light_channel) / 10.0

    def temperature_humidity(self):
        """Air temperature in degrees C and relative humidity in %."""
        if self._dht_type == "20":
            return self._read_dht20()
        return self._read_dht11()

    def _read_adc(self, method, channel):
        # grove.adc calls sys.exit() when the HAT does not answer on I2C;
        # turn that into a failed read instead of stopping the program.
        try:
            if self._adc is None:
                self._adc = self._adc_class(address=self._adc_address)
            return getattr(self._adc, method)(channel)
        except SystemExit as exc:
            raise SensorReadError("ADC does not answer on I2C") from exc

    def _read_dht11(self):
        if self._dht is None:
            self._dht = self._dht_class(self._dht_type, self._dht_pin)
        # Not DHT.read(): when every retry fails it returns the last good
        # value (0.0 at start-up), which would pass as a fresh measurement.
        for _ in range(DHT_ATTEMPTS):
            humidity, temperature = self._dht._read()
            if humidity is not None:
                return temperature, humidity
        raise SensorReadError(f"DHT11 sent no valid frame in {DHT_ATTEMPTS} tries")

    def _read_dht20(self):
        try:
            if self._dht is None:
                self._dht = self._dht_class()
            return self._dht.read()
        except Exception:
            self._dht = None  # send the start-up command again next time
            raise


_default_sensors = None


def _get_default_sensors():
    global _default_sensors
    if _default_sensors is None:
        _default_sensors = GroveSensors()
    return _default_sensors


def _try_read(label, read):
    try:
        return read()
    except Exception as exc:
        log.warning("%s read failed: %s", label, exc)
        return None


def _clean(name, value):
    """Validate one value and log when it is rejected."""
    checked = validate(name, value)
    if checked is None:
        if value is not None:
            log.warning("%s value %r is out of range, stored as missing", name, value)
        return None
    if isinstance(checked, float):
        return round(checked, 1)
    return checked


def read_all(sensors=None):
    """Read every sensor once.

    Returns a dict with the four telemetry keys. A value is None when its
    sensor failed or reported something outside ``VALID_RANGES``; the other
    sensors are still read.
    """
    if sensors is None:
        sensors = _get_default_sensors()

    soil = _try_read("soil moisture", sensors.soil_moisture_raw)
    light = _try_read("light", sensors.light_pct)
    try:
        temperature, humidity = sensors.temperature_humidity()
    except Exception as exc:
        log.warning("temperature/humidity read failed: %s", exc)
        temperature = humidity = None

    return {
        "temperature_c": _clean("temperature_c", temperature),
        "humidity_pct": _clean("humidity_pct", humidity),
        "soil_moisture_raw": _clean("soil_moisture_raw", soil),
        "light_pct": _clean("light_pct", light),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(json.dumps(read_all(), indent=2))
