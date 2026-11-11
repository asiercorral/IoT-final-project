"""Tests for plantpulse.acquisition. They run on a laptop with fake sensors and a fake clock."""

import csv
from datetime import datetime

import pytest

from plantpulse import acquisition, sensors

START = 1_731_400_000  # 12 Nov 2024, any fixed instant will do

GOOD = {
    "temperature_c": 19.5,
    "humidity_pct": 78.0,
    "soil_moisture_raw": 420,
    "light_pct": 63.5,
}


class FakeSensors:
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


class FakeTime:
    """Wall clock and monotonic clock in one; sleeping moves both forward."""

    def __init__(self, start=START):
        self.now = float(start)
        self.sleeps = []

    def time(self):
        return self.now

    monotonic = time

    def sleep(self, seconds):
        assert seconds >= 0
        self.sleeps.append(seconds)
        self.now += seconds


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run(store, fake_time, interval, cycles, sensor_source=None):
    acquisition.run(
        store,
        sensor_source or FakeSensors(),
        interval,
        cycles=cycles,
        clock=fake_time.time,
        monotonic=fake_time.monotonic,
        sleep=fake_time.sleep,
    )


# --- payload and CSV format -------------------------------------------------


def test_reading_uses_the_telemetry_payload_format():
    reading = acquisition.build_reading(GOOD, START + 0.7, device_id="plant-x")

    assert reading == {
        "device_id": "plant-x",
        "timestamp": START,
        "sensors": GOOD,
    }


def test_csv_has_header_and_one_row_per_reading(tmp_path):
    store = acquisition.CsvStore(tmp_path / "readings.csv")

    acquisition.acquire_once(store, FakeSensors(), clock=lambda: START)

    lines = (tmp_path / "readings.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(acquisition.CSV_FIELDS)
    assert len(lines) == 2
    row = read_rows(tmp_path / "readings.csv")[0]
    assert row["timestamp"] == str(START)
    assert row["soil_moisture_raw"] == "420"
    assert row["light_pct"] == "63.5"


def test_local_time_column_matches_the_timestamp(tmp_path):
    store = acquisition.CsvStore(tmp_path / "readings.csv")

    acquisition.acquire_once(store, FakeSensors(), clock=lambda: START)

    row = read_rows(tmp_path / "readings.csv")[0]
    assert datetime.fromisoformat(row["time_local"]).timestamp() == START


def test_missing_value_is_an_empty_cell_and_zero_stays_zero(tmp_path):
    store = acquisition.CsvStore(tmp_path / "readings.csv")
    source = FakeSensors(soil_moisture_raw=OSError("unplugged"), light_pct=0.0)

    reading = acquisition.acquire_once(store, source, clock=lambda: START)

    assert reading["sensors"]["soil_moisture_raw"] is None
    row = read_rows(tmp_path / "readings.csv")[0]
    assert row["soil_moisture_raw"] == ""
    assert row["light_pct"] == "0.0"


def test_data_folder_is_created(tmp_path):
    store = acquisition.CsvStore(tmp_path / "data" / "readings.csv")

    acquisition.acquire_once(store, FakeSensors(), clock=lambda: START)

    assert (tmp_path / "data" / "readings.csv").is_file()


def test_restart_appends_without_a_second_header(tmp_path):
    path = tmp_path / "readings.csv"
    acquisition.acquire_once(acquisition.CsvStore(path), FakeSensors(), clock=lambda: START)

    acquisition.acquire_once(acquisition.CsvStore(path), FakeSensors(), clock=lambda: START + 300)

    assert [r["timestamp"] for r in read_rows(path)] == [str(START), str(START + 300)]


def test_file_with_other_columns_is_moved_aside_not_appended_to(tmp_path):
    path = tmp_path / "readings.csv"
    path.write_text("timestamp,soil\n1,2\n", encoding="utf-8")

    store = acquisition.CsvStore(path)
    acquisition.acquire_once(store, FakeSensors(), clock=lambda: START)

    assert len(read_rows(path)) == 1
    kept = [p for p in tmp_path.iterdir() if p.name != "readings.csv"]
    assert len(kept) == 1
    assert kept[0].read_text(encoding="utf-8") == "timestamp,soil\n1,2\n"


# --- the loop -----------------------------------------------------------------


def test_loop_reads_every_interval_with_timestamps(tmp_path):
    path = tmp_path / "readings.csv"
    fake_time = FakeTime()

    run(acquisition.CsvStore(path), fake_time, interval=300, cycles=3)

    assert [int(r["timestamp"]) for r in read_rows(path)] == [START, START + 300, START + 600]
    assert fake_time.sleeps == [300, 300]


def test_a_full_day_at_five_minutes_is_288_rows(tmp_path):
    path = tmp_path / "readings.csv"

    run(acquisition.CsvStore(path), FakeTime(), interval=300, cycles=288)

    rows = read_rows(path)
    assert len(rows) == 288
    assert int(rows[-1]["timestamp"]) - int(rows[0]["timestamp"]) == 287 * 300


class SlowStore(acquisition.CsvStore):
    """Writing takes ``delay`` seconds of fake time."""

    def __init__(self, path, fake_time, delay):
        super().__init__(path)
        self.fake_time = fake_time
        self.delay = delay

    def append(self, reading):
        super().append(reading)
        self.fake_time.now += self.delay


def test_slow_reads_do_not_make_the_schedule_drift(tmp_path):
    path = tmp_path / "readings.csv"
    fake_time = FakeTime()

    run(SlowStore(path, fake_time, delay=4), fake_time, interval=10, cycles=3)

    assert [int(r["timestamp"]) for r in read_rows(path)] == [START, START + 10, START + 20]
    assert fake_time.sleeps == [6, 6]


def test_a_cycle_longer_than_the_interval_skips_to_the_next_slot(tmp_path):
    path = tmp_path / "readings.csv"
    fake_time = FakeTime()

    run(SlowStore(path, fake_time, delay=25), fake_time, interval=10, cycles=2)

    assert [int(r["timestamp"]) for r in read_rows(path)] == [START, START + 30]


class FlakyStore(acquisition.CsvStore):
    """The first write fails, as with a full or read-only SD card."""

    failed = False

    def append(self, reading):
        if not self.failed:
            self.failed = True
            raise OSError("disk full")
        super().append(reading)


def test_a_failed_cycle_does_not_stop_the_loop(tmp_path):
    path = tmp_path / "readings.csv"

    run(FlakyStore(path), FakeTime(), interval=300, cycles=3)

    assert [int(r["timestamp"]) for r in read_rows(path)] == [START + 300, START + 600]


def test_all_sensors_failing_still_stores_a_timestamped_row(tmp_path):
    path = tmp_path / "readings.csv"
    broken = FakeSensors(
        temperature_c=OSError(), soil_moisture_raw=OSError(), light_pct=OSError()
    )

    run(acquisition.CsvStore(path), FakeTime(), interval=300, cycles=1, sensor_source=broken)

    row = read_rows(path)[0]
    assert row["timestamp"] == str(START)
    assert all(row[key] == "" for key in acquisition.SENSOR_KEYS)


# --- command line ---------------------------------------------------------------


def test_once_writes_one_reading_and_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(sensors, "GroveSensors", FakeSensors)
    path = tmp_path / "readings.csv"

    acquisition.main(["--once", "--csv", str(path)])

    assert len(read_rows(path)) == 1


def test_without_grove_libraries_the_program_stops_with_a_message(tmp_path, monkeypatch, capsys):
    def missing():
        raise ModuleNotFoundError("No module named 'grove'")

    monkeypatch.setattr(sensors, "GroveSensors", missing)

    with pytest.raises(SystemExit) as exc:
        acquisition.main(["--once", "--csv", str(tmp_path / "readings.csv")])

    assert exc.value.code == 1
    assert "Run this on the Pi" in capsys.readouterr().err
    assert not (tmp_path / "readings.csv").exists()


@pytest.mark.parametrize("interval", ["0", "-5"])
def test_interval_must_be_positive(interval):
    with pytest.raises(SystemExit) as exc:
        acquisition.main(["--interval", interval])

    assert exc.value.code == 2
