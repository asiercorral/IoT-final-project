"""Tests for the web API and page (T-27, T-28, T-29, T-30, T-35).

They run on a laptop with Flask: a temporary SQLite file, a fake state
listener and a temporary forecast cache stand in for the Pi.
"""

import copy
import csv
import io
import json

import pytest

pytest.importorskip("flask")

from plantpulse import config, storage  # noqa: E402
from plantpulse.profile import load_profile  # noqa: E402
from web import data, web_server  # noqa: E402

NOW = 1_764_000_000 - 1_764_000_000 % 3600 + 600  # ten minutes past an hour
HOUR = 3600


def cache(rain_per_hour=0.0, age_h=1.0, source="euskalmet", hours=12):
    """A forecast cache as forecast.py writes it."""
    start = NOW - NOW % HOUR
    return {
        "source": source,
        "fetched_at": int(NOW - age_h * HOUR),
        "hours": [[start + i * HOUR, rain_per_hour] for i in range(hours)],
    }


@pytest.fixture
def sheltered():
    return copy.deepcopy(load_profile("basil"))  # rain_exposed: false


@pytest.fixture
def exposed(sheltered):
    sheltered["rain_exposed"] = True
    return sheltered


def used(tmp_path, profile, forecast_cache):
    path = tmp_path / "forecast_cache.json"
    if forecast_cache is not None:
        path.write_text(json.dumps(forecast_cache), encoding="utf-8")
    return data.forecast_used(NOW, path, profile)


# --- forecast used and why ------------------------------------------------------


def test_no_forecast_is_not_used_and_says_why(tmp_path, exposed):
    f = used(tmp_path, exposed, None)

    assert f["status"] == "unavailable"
    assert f["used"] is False
    assert "only the sensors" in f["why"]


def test_forecast_older_than_6_hours_is_not_used(tmp_path, exposed):
    f = used(tmp_path, exposed, cache(rain_per_hour=2.0, age_h=7))

    assert f["status"] == "outdated"
    assert f["used"] is False
    assert "7 h old" in f["why"]


def test_sheltered_plant_ignores_rain(tmp_path, sheltered):
    f = used(tmp_path, sheltered, cache(rain_per_hour=1.0))

    assert f["status"] == "fresh"
    assert f["used"] is False
    assert "sheltered" in f["why"]
    # forecast.rain_mm counts the current hour too: 7 hours of 1 mm
    assert f["rain_mm"] == 7.0


def test_exposed_plant_with_rain_coming_can_wait(tmp_path, exposed):
    f = used(tmp_path, exposed, cache(rain_per_hour=0.5))

    assert f["used"] is True
    assert "3.5 mm" in f["why"]  # 7 hours of 0.5 mm
    assert "unless the soil is very dry" in f["why"]


def test_exposed_plant_without_rain_is_not_delayed(tmp_path, exposed):
    f = used(tmp_path, exposed, cache(rain_per_hour=0.0, source="open-meteo"))

    assert f["used"] is True
    assert f["source_name"] == "Open-Meteo"
    assert "not delayed" in f["why"]


def test_forecast_not_covering_the_next_hours_is_not_used(tmp_path, exposed):
    f = used(tmp_path, exposed, cache(hours=2))

    assert f["status"] == "unavailable"
    assert f["used"] is False


# --- test data ---------------------------------------------------------------------


def store(db_path, *rows):
    """Write readings the way the MQTT subscriber (T-22) will."""
    storage.init_db(db_path)
    with storage.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO readings VALUES (?, ?, ?, ?, ?, ?)",
            [(config.DEVICE_ID, *row) for row in rows],
        )


def reading(ts, temp=19.5, hum=70.0, soil=1197, light=40.0):
    return (ts, temp, hum, soil, light)


class FakeListener:
    def __init__(self, message=None):
        self.message = message


def state_message(name="CHECK", code="CHECK_DRY", ts=NOW - 60, **extra):
    return {"device_id": config.DEVICE_ID, "timestamp": ts, "state": name,
            "status_code": code, "reason": "Soil is getting dry (40 %).", "forecast": None,
            **extra}


@pytest.fixture
def make_client(tmp_path, sheltered):
    def make(message=None, rows=()):
        db = tmp_path / "plantpulse.db"
        if rows:
            store(db, *rows)
        app = web_server.create_app(
            db_path=db,
            state_listener=FakeListener(message),
            forecast_cache=tmp_path / "forecast_cache.json",
            profile=sheltered,
            clock=lambda: NOW,
        )
        return app.test_client()
    return make


# --- GET /api/status (T-27) -----------------------------------------------------------


def test_status_has_state_reason_readings_and_forecast(make_client):
    client = make_client(state_message(), rows=[reading(NOW - 600), reading(NOW - 300)])

    s = client.get("/api/status").get_json()

    assert s["state"] == "CHECK"
    assert s["status_code"] == "CHECK_DRY"
    assert s["reason"] == "Soil is getting dry (40 %)."
    assert s["explanation"]                       # why it matters, for pupils
    assert s["readings"]["timestamp"] == NOW - 300
    assert s["readings"]["age_s"] == 300
    assert s["readings"]["temperature_c"] == 19.5
    assert s["readings"]["soil_pct"] == pytest.approx(57.7, abs=0.1)  # 1197 mV
    assert s["screen_cells"] == 5                 # same bar as the LCD
    assert s["forecast"]["why"]
    assert s["forecast"]["age_h"] is None         # no forecast cached


def test_status_without_any_data_explains_what_is_missing(make_client):
    s = make_client().get("/api/status").get_json()

    assert s["state"] is None
    assert "rule engine" in s["reason"]
    assert s["readings"] is None
    assert s["faulty_sensors"] == []
    assert s["screen_cells"] == 0


def test_an_old_state_is_not_shown_as_current(make_client):
    old = state_message("NORMAL", "OK", ts=NOW - data.STATE_STALE_AFTER_S - 60)

    s = make_client(old).get("/api/status").get_json()

    assert s["state"] is None
    assert "No new plant state" in s["reason"]
    assert s["screen_cells"] == 0


def test_faulty_sensor_is_named(make_client):
    client = make_client(
        state_message("FAULT", "FAULT_SENSOR"), rows=[reading(NOW - 60, soil=None)]
    )

    s = client.get("/api/status").get_json()

    assert [f["label"] for f in s["faulty_sensors"]] == ["Soil moisture sensor"]
    assert s["readings"]["soil_pct"] is None
    assert s["readings"]["light_pct"] == 40.0


def test_all_findings_of_the_rule_engine_are_passed_on(make_client):
    findings = [
        {"sensor": "soil", "level": "CHECK", "code": "CHECK_DRY", "reason": "dry"},
        {"sensor": "air", "level": "CHECK", "code": "CHECK_COLD", "reason": "cold"},
    ]

    s = make_client(state_message(findings=findings)).get("/api/status").get_json()

    assert [f["code"] for f in s["findings"]] == ["CHECK_DRY", "CHECK_COLD"]


def test_every_rule_engine_code_has_an_explanation():
    codes = {"OK", "CHECK_DRY", "CHECK_WET", "ATTENTION_DRY", "ATTENTION_WET",
             "CHECK_COLD", "CHECK_HOT", "ATTENTION_COLD", "FAULT_SENSOR", "FAULT_STALE"}

    assert codes <= set(data.EXPLANATIONS)


def test_state_listener_keeps_the_latest_valid_message():
    listener = data.StateListener()

    listener.on_payload(json.dumps(state_message()).encode())
    listener.on_payload(b"not json")
    listener.on_payload(b"[1, 2]")

    assert listener.message["state"] == "CHECK"


# --- GET /api/history (T-28) ------------------------------------------------------------


def test_history_returns_the_requested_period_oldest_first(make_client):
    rows = [reading(NOW - h * HOUR) for h in (30, 23, 5, 1)]
    client = make_client(rows=rows)

    day = client.get("/api/history?hours=24").get_json()
    longer = client.get("/api/history?hours=48").get_json()

    assert [r["timestamp"] for r in day["readings"]] == [NOW - 23 * HOUR, NOW - 5 * HOUR, NOW - HOUR]
    assert len(longer["readings"]) == 4
    assert day["from"] == NOW - 24 * HOUR and day["to"] == NOW
    assert set(day["readings"][0]) == {
        "timestamp", "temperature_c", "humidity_pct", "soil_moisture_raw", "soil_pct", "light_pct",
    }


def test_history_of_7_days(make_client):
    rows = [reading(NOW - d * 86400 - 60) for d in range(8)]  # the 8th is too old

    week = make_client(rows=rows).get("/api/history?hours=168").get_json()

    assert len(week["readings"]) == 7


def test_history_defaults_to_24_hours_and_includes_the_soil_thresholds(make_client, sheltered):
    h = make_client().get("/api/history").get_json()

    assert h["hours"] == 24
    assert h["readings"] == []
    assert h["soil_thresholds"]["check_below_pct"] == sheltered["soil"]["dry_below_pct"]
    assert h["soil_thresholds"]["attention_below_pct"] == sheltered["soil"]["critical_below_pct"]


@pytest.mark.parametrize("hours", ["0", "-3", "abc", "100000"])
def test_history_rejects_a_bad_period(make_client, hours):
    response = make_client().get("/api/history?hours=" + hours)

    assert response.status_code == 400
    assert "hours" in response.get_json()["error"]


def test_history_as_csv(make_client):
    client = make_client(rows=[reading(NOW - 60, temp=None)])

    response = client.get("/api/history?hours=24&format=csv")

    assert response.mimetype == "text/csv"
    rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
    assert rows[0]["timestamp"] == str(NOW - 60)
    assert rows[0]["temperature_c"] == ""        # missing stays empty, never 0


def test_missing_database_gives_empty_history_not_an_error(make_client):
    assert make_client().get("/api/history").status_code == 200


# --- page (T-29, T-30, T-35) -------------------------------------------------------------


def test_page_has_every_part_and_loads_nothing_from_the_internet(make_client):
    client = make_client()
    page = client.get("/").get_data(as_text=True)

    for part in ('id="state-label"', 'id="reason"', 'id="tiles"', 'id="forecast-why"',
                 'id="chart"', 'data-hours="24"', 'data-hours="168"'):
        assert part in page
    for attr in ('src="http', 'href="http', "url(http"):
        assert attr not in page
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200
