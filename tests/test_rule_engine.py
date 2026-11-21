"""Tests for plantpulse.rule_engine. They run on a laptop, no Pi needed.

Soil readings are given as an index in % and turned into mV with the test
calibration below, so each test reads like the rule it checks.
"""

import copy
import csv

import pytest

from plantpulse import acquisition, rule_engine, state
from plantpulse.profile import load_profile

NOW = 1_800_000_000
HOUR = 3600
STEP = 300  # one reading every 5 min, as on the Pi

DRY_MV, WET_MV = 100, 2100  # test calibration: 0 % = 100 mV, 100 % = 2100 mV


def mv(pct):
    """Soil reading in mV for a soil index in %."""
    return DRY_MV + (WET_MV - DRY_MV) * pct / 100


def reading(soil_pct=60, ts=NOW, **overrides):
    sensors = {
        "temperature_c": 21.0,
        "humidity_pct": 55.0,
        "soil_moisture_raw": None if soil_pct is None else mv(soil_pct),
        "light_pct": 60.0,
    }
    sensors.update(overrides)
    return {"timestamp": ts, "sensors": sensors}


def steady(soil_pct, hours, end=NOW, **overrides):
    """Readings every STEP seconds with the same values, for ``hours`` before ``end``."""
    count = int(hours * HOUR / STEP)
    return [reading(soil_pct, end - i * STEP, **overrides) for i in range(count, 0, -1)]


def evaluate(current, history=(), profile=None):
    return rule_engine.evaluate(
        current, profile or load_profile("basil"), history, dry_mv=DRY_MV, wet_mv=WET_MV
    )


@pytest.fixture
def basil():
    return load_profile("basil")


# --- soil index ----------------------------------------------------------------


def test_soil_index_maps_calibration_to_0_and_100():
    assert rule_engine.soil_index(DRY_MV, DRY_MV, WET_MV) == 0.0
    assert rule_engine.soil_index(WET_MV, DRY_MV, WET_MV) == 100.0
    assert rule_engine.soil_index(mv(37), DRY_MV, WET_MV) == 37.0


def test_soil_index_works_when_dry_reads_higher():
    # capacitive probes read higher when dry
    assert rule_engine.soil_index(2100, dry_mv=2100, wet_mv=100) == 0.0
    assert rule_engine.soil_index(100, dry_mv=2100, wet_mv=100) == 100.0


def test_soil_index_is_clamped_and_none_stays_none():
    assert rule_engine.soil_index(DRY_MV - 50, DRY_MV, WET_MV) == 0.0
    assert rule_engine.soil_index(WET_MV + 50, DRY_MV, WET_MV) == 100.0
    assert rule_engine.soil_index(None, DRY_MV, WET_MV) is None


# --- definition of done: dry, fine and wet soil --------------------------------


@pytest.mark.parametrize(
    "pct, expected_state, expected_code",
    [
        (5, "ATTENTION", "ATTENTION_DRY"),   # below critical_below_pct (20)
        (19.9, "ATTENTION", "ATTENTION_DRY"),
        (20, "CHECK", "CHECK_DRY"),          # below dry_below_pct (45)
        (44.9, "CHECK", "CHECK_DRY"),
        (45, "NORMAL", "OK"),
        (70, "NORMAL", "OK"),
        (95, "NORMAL", "OK"),                # wet, but only just now
    ],
)
def test_soil_states(pct, expected_state, expected_code):
    result = evaluate(reading(pct))
    assert result["state"] == expected_state
    assert result["status_code"] == expected_code


def test_wet_soil_for_a_day_is_check():
    result = evaluate(reading(95), steady(95, 25))
    assert result["state"] == "CHECK"
    assert result["status_code"] == "CHECK_WET"
    assert "Do not water" in result["reason"]


def test_wet_soil_for_less_than_a_day_is_normal():
    assert evaluate(reading(95), steady(95, 20))["state"] == "NORMAL"


def test_saturated_soil_for_two_days_is_attention():
    result = evaluate(reading(100), steady(100, 49))
    assert result["state"] == "ATTENTION"
    assert result["status_code"] == "ATTENTION_WET"


def test_drying_out_breaks_the_wet_run():
    history = steady(95, 30, end=NOW - 2 * HOUR) + steady(80, 1, end=NOW - HOUR) + steady(95, 1)
    assert evaluate(reading(95), history)["state"] == "NORMAL"


def test_a_gap_in_the_readings_breaks_the_wet_run():
    # Pi switched off for 12 h: the hours before the gap do not count
    history = steady(95, 20, end=NOW - 14 * HOUR) + steady(95, 2)
    assert evaluate(reading(95), history)["state"] == "NORMAL"


def test_demo_profile_triggers_wet_states_after_minutes():
    demo = load_profile("basil_demo")
    assert evaluate(reading(95), steady(95, 0.1), demo)["status_code"] == "CHECK_WET"
    assert evaluate(reading(100), steady(100, 0.2), demo)["status_code"] == "ATTENTION_WET"


# --- faults and several findings -----------------------------------------------


def test_missing_soil_reading_is_fault():
    result = evaluate(reading(None))
    assert result["state"] == "FAULT"
    assert "soil" in result["reason"]


def test_every_missing_sensor_is_named():
    result = evaluate(reading(60, light_pct=None, temperature_c=None))
    assert result["state"] == "FAULT"
    assert "temperature" in result["reason"] and "light" in result["reason"]


def test_fault_wins_but_the_dry_soil_is_still_listed():
    result = evaluate(reading(5, light_pct=None))
    assert result["state"] == "FAULT"
    assert [f["code"] for f in result["findings"]] == ["FAULT_SENSOR", "ATTENTION_DRY"]


def test_no_findings_when_everything_is_fine():
    result = evaluate(reading(60))
    assert result["findings"] == []
    assert result["reason"].startswith("Soil moisture is fine")


# --- air temperature ----------------------------------------------------------
# basil: severe cold < 5 °C, cold < 12 °C, hot > 35 °C, each for 0.5 h


def cold(temperature, hours=1, soil_pct=60):
    """History plus current reading at one temperature."""
    return (
        reading(soil_pct, temperature_c=temperature),
        steady(soil_pct, hours, temperature_c=temperature),
    )


def test_cold_air_for_half_an_hour_is_check():
    result = evaluate(*cold(9.0))
    assert result["state"] == "CHECK"
    assert result["status_code"] == "CHECK_COLD"
    assert "9 °C" in result["reason"]


def test_one_cold_reading_does_not_change_the_state():
    # a single noisy DHT reading must not make the screen jump
    assert evaluate(reading(60, temperature_c=9.0), steady(60, 1))["state"] == "NORMAL"


def test_cold_for_less_than_the_duration_is_normal():
    assert evaluate(*cold(9.0, hours=0.25))["state"] == "NORMAL"


def test_very_cold_air_is_attention():
    result = evaluate(*cold(3.0))
    assert result["state"] == "ATTENTION"
    assert result["status_code"] == "ATTENTION_COLD"


def test_hot_air_is_check():
    result = evaluate(*cold(38.0))
    assert result["status_code"] == "CHECK_HOT"


def test_mild_air_gives_no_finding():
    assert evaluate(*cold(20.0))["findings"] == []


def test_dry_soil_and_cold_air_are_both_listed_soil_first():
    result = evaluate(*cold(9.0, soil_pct=30))
    assert result["state"] == "CHECK"
    assert result["status_code"] == "CHECK_DRY"
    assert [f["code"] for f in result["findings"]] == ["CHECK_DRY", "CHECK_COLD"]


def test_very_cold_air_outranks_dry_soil():
    result = evaluate(*cold(3.0, soil_pct=30))
    assert result["status_code"] == "ATTENTION_COLD"
    assert [f["code"] for f in result["findings"]] == ["ATTENTION_COLD", "CHECK_DRY"]


def test_tomato_uses_its_own_temperature_limits():
    tomato = load_profile("tomato")  # cold < 10 °C; soil 80 % is fine for tomato
    assert evaluate(*cold(11.0, soil_pct=80), profile=tomato)["state"] == "NORMAL"
    assert evaluate(*cold(9.0, soil_pct=80), profile=tomato)["status_code"] == "CHECK_COLD"


def test_demo_profile_triggers_temperature_after_minutes():
    demo = load_profile("basil_demo")  # duration_h 0.05 = 3 min
    assert evaluate(*cold(9.0, hours=0.1), profile=demo)["status_code"] == "CHECK_COLD"


# --- the message the screen and the web page read ------------------------------


def test_result_is_a_valid_state_message():
    result = evaluate(reading(30))
    assert state.state_of(result) == "CHECK"
    assert result["timestamp"] == NOW
    assert result["soil_pct"] == 30.0


def test_thresholds_come_from_the_profile(basil):
    strict = copy.deepcopy(basil)
    strict["soil"]["dry_below_pct"] = 80
    assert evaluate(reading(70), profile=strict)["status_code"] == "CHECK_DRY"


# --- reading the acquisition CSV -----------------------------------------------


def write_csv(path, readings):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=acquisition.CSV_FIELDS)
        writer.writeheader()
        for r in readings:
            writer.writerow(acquisition.to_csv_row(r))


def test_evaluate_latest_reads_the_csv_written_by_acquisition(tmp_path, basil):
    path = tmp_path / "readings.csv"
    write_csv(path, steady(100, 49) + [reading(100), reading(None, ts=NOW - 10 * 24 * HOUR)])

    result = rule_engine.evaluate_latest(
        path, basil, clock=lambda: NOW, dry_mv=DRY_MV, wet_mv=WET_MV
    )

    assert result["status_code"] == "ATTENTION_WET"  # old row outside the window is ignored


def test_missing_values_in_the_csv_become_none(tmp_path):
    path = tmp_path / "readings.csv"
    write_csv(path, [reading(60, light_pct=None)])
    loaded = rule_engine.load_readings(path, since=0)
    assert loaded[0]["sensors"]["light_pct"] is None
    assert loaded[0]["sensors"]["soil_moisture_raw"] == pytest.approx(mv(60))


def test_no_csv_means_no_result(tmp_path, basil):
    assert rule_engine.evaluate_latest(tmp_path / "missing.csv", basil, clock=lambda: NOW) is None
