"""Tests for the web page's forecast card (T-35). They run on a laptop with Flask."""

import copy
import json

import pytest

pytest.importorskip("flask")

from plantpulse import config  # noqa: E402
from plantpulse.profile import load_profile  # noqa: E402
from web import web_server  # noqa: E402

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
    return web_server.forecast_used(now=NOW, cache_path=path, profile=profile)


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


# --- page and API -----------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FORECAST_CACHE", tmp_path / "forecast_cache.json")
    return web_server.app.test_client()


def test_status_api_includes_the_forecast_and_why(client):
    data = client.get("/api/status").get_json()

    assert set(data["forecast"]) >= {
        "status", "source", "age_h", "rain_mm", "window_h", "used", "why",
    }
    assert data["forecast"]["why"]


def test_page_has_the_forecast_card(client):
    page = client.get("/").get_data(as_text=True)

    assert 'id="forecast-why"' in page
    assert "showForecast(s.forecast)" in page
