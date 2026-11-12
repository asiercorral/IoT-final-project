"""Tests for plantpulse.sensors. They run on a laptop: no Pi, no Grove library."""

import sys
import types

import pytest

from plantpulse import sensors

GOOD = {
    "temperature_c": 19.5,
    "humidity_pct": 78.0,
    "soil_moisture_raw": 420,
    "light_pct": 63.5,
}


class FakeSensors:
    """Stands in for GroveSensors. A value that is an exception is raised."""

    def __init__(self, **overrides):
        self.values = {**GOOD, **overrides}

    def _get(self, name):
        value = self.values[name]
        if isinstance(value, BaseException):
            raise value
        return value

    def soil_moisture_raw(self):
        return self._get("soil_moisture_raw")

    def light_pct(self):
        return self._get("light_pct")

    def temperature_humidity(self):
        return self._get("temperature_c"), self._get("humidity_pct")


# --- read_all -------------------------------------------------------------


def test_valid_readings_are_returned_unchanged():
    assert sensors.read_all(FakeSensors()) == GOOD


@pytest.mark.parametrize("name", ["soil_moisture_raw", "light_pct"])
def test_failed_read_is_none_and_other_sensors_still_read(name):
    reading = sensors.read_all(FakeSensors(**{name: OSError("no answer")}))

    assert reading[name] is None
    assert {k: v for k, v in reading.items() if k != name} == {
        k: v for k, v in GOOD.items() if k != name
    }


def test_failed_dht_gives_none_for_temperature_and_humidity():
    reading = sensors.read_all(FakeSensors(temperature_c=OSError("timeout")))

    assert reading["temperature_c"] is None
    assert reading["humidity_pct"] is None
    assert reading["soil_moisture_raw"] == 420
    assert reading["light_pct"] == 63.5


@pytest.mark.parametrize(
    "name, bad_value",
    [
        ("temperature_c", 120.0),
        ("temperature_c", -60.0),
        ("humidity_pct", 150.0),
        ("humidity_pct", -1.0),
        ("soil_moisture_raw", -1),
        ("soil_moisture_raw", 5000),
        ("light_pct", 100.1),
        ("light_pct", float("nan")),
        ("light_pct", "63.5"),
        ("soil_moisture_raw", None),
    ],
)
def test_out_of_range_or_invalid_value_is_none(name, bad_value):
    reading = sensors.read_all(FakeSensors(**{name: bad_value}))

    assert reading[name] is None
    assert all(v is not None for k, v in reading.items() if k != name)


def test_only_the_bad_half_of_the_dht_pair_is_dropped():
    reading = sensors.read_all(FakeSensors(humidity_pct=150.0))

    assert reading["humidity_pct"] is None
    assert reading["temperature_c"] == 19.5


def test_a_real_zero_is_kept_as_zero():
    # Darkness and 0 degrees are measurements, not missing data.
    reading = sensors.read_all(FakeSensors(light_pct=0.0, temperature_c=0.0))

    assert reading["light_pct"] == 0.0
    assert reading["temperature_c"] == 0.0


def test_every_sensor_failing_gives_all_none_never_zero():
    broken = FakeSensors(
        temperature_c=OSError(), soil_moisture_raw=OSError(), light_pct=OSError()
    )

    assert sensors.read_all(broken) == dict.fromkeys(GOOD)


def test_floats_are_rounded_to_one_decimal():
    reading = sensors.read_all(FakeSensors(temperature_c=19.46, light_pct=63.449))

    assert reading["temperature_c"] == 19.5
    assert reading["light_pct"] == 63.4


# --- validate ---------------------------------------------------------------


@pytest.mark.parametrize("name", sensors.VALID_RANGES)
def test_range_limits_are_accepted(name):
    low, high = sensors.VALID_RANGES[name]

    assert sensors.validate(name, low) == low
    assert sensors.validate(name, high) == high


def test_booleans_are_not_readings():
    assert sensors.validate("light_pct", True) is None


# --- GroveSensors against fake Grove libraries ----------------------------
#
# These fakes copy the documented behaviour of grove.py and seeed_dht.
# They check our handling of it, not the real hardware.


class FakeADC:
    fail = False

    def __init__(self, address=0x04):
        self.address = address

    def _check(self):
        if FakeADC.fail:
            sys.exit(2)  # what grove.adc does on an I2C error

    def read_voltage(self, channel):
        self._check()
        return {0: 420}[channel]

    def read(self, channel):
        self._check()
        return {2: 635}[channel]


class FakeDHT:
    frames = []

    def __init__(self, dht_type, pin):
        self.dht_type = dht_type
        self.pin = pin

    def _read(self):
        if FakeDHT.frames:
            return FakeDHT.frames.pop(0)
        return None, "checksum error"

    def read(self):  # the method we must not use: it hides failures
        return 0.0, 0.0


class FakeAHT20:
    present = True

    def __init__(self):
        if not FakeAHT20.present:
            raise OSError("no device at 0x38")

    def read(self):
        if not FakeAHT20.present:
            raise OSError("no device at 0x38")
        return 21.3, 55.0  # temperature first


@pytest.fixture
def grove(monkeypatch):
    """Install fake grove and seeed_dht modules for one test."""
    FakeADC.fail = False
    FakeDHT.frames = []
    FakeAHT20.present = True

    modules = {
        "grove": types.ModuleType("grove"),
        "grove.adc": types.ModuleType("grove.adc"),
        "grove.grove_temperature_humidity_aht20": types.ModuleType(
            "grove.grove_temperature_humidity_aht20"
        ),
        "seeed_dht": types.ModuleType("seeed_dht"),
    }
    modules["grove.adc"].ADC = FakeADC
    modules[
        "grove.grove_temperature_humidity_aht20"
    ].GroveTemperatureHumidityAHT20 = FakeAHT20
    modules["seeed_dht"].DHT = FakeDHT
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def test_grove_reads_map_to_the_telemetry_keys(grove):
    FakeDHT.frames = [(78.0, 19.5)]  # seeed_dht gives humidity first

    reading = sensors.read_all(sensors.GroveSensors(dht_type="11"))

    assert reading == GOOD


def test_adc_exit_becomes_none_instead_of_stopping_the_program(grove):
    FakeDHT.frames = [(78.0, 19.5)]
    FakeADC.fail = True

    reading = sensors.read_all(sensors.GroveSensors(dht_type="11"))

    assert reading["soil_moisture_raw"] is None
    assert reading["light_pct"] is None
    assert reading["temperature_c"] == 19.5


def test_dht11_retries_until_a_valid_frame(grove):
    FakeDHT.frames = [(None, "timeout"), (None, "checksum error"), (78.0, 19.5)]

    reading = sensors.read_all(sensors.GroveSensors(dht_type="11"))

    assert reading["temperature_c"] == 19.5
    assert reading["humidity_pct"] == 78.0


def test_dht11_without_a_valid_frame_is_none_not_a_stale_value(grove):
    grove_sensors = sensors.GroveSensors(dht_type="11")
    FakeDHT.frames = [(78.0, 19.5)]
    assert sensors.read_all(grove_sensors)["temperature_c"] == 19.5

    reading = sensors.read_all(grove_sensors)  # no frames left: all tries fail

    assert reading["temperature_c"] is None
    assert reading["humidity_pct"] is None


def test_dht20_gives_temperature_and_humidity_in_the_right_order(grove):
    reading = sensors.read_all(sensors.GroveSensors(dht_type="20"))

    assert reading["temperature_c"] == 21.3
    assert reading["humidity_pct"] == 55.0


def test_dht20_unplugged_at_start_is_none_then_recovers(grove):
    FakeAHT20.present = False
    grove_sensors = sensors.GroveSensors(dht_type="20")
    assert sensors.read_all(grove_sensors)["temperature_c"] is None

    FakeAHT20.present = True

    assert sensors.read_all(grove_sensors)["temperature_c"] == 21.3


def test_unknown_dht_type_is_rejected(grove):
    with pytest.raises(ValueError):
        sensors.GroveSensors(dht_type="22")
