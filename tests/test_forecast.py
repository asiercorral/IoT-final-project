"""Tests for plantpulse.forecast. They run on a laptop: no Internet, no key.

The HTTP requests are replaced by fake functions; Euskalmet parsing uses the
real sample answer in docs/euskalmet_trends.json (Bilbao, 13 Nov 2026).
"""

import json
from datetime import date, datetime

import pytest

from plantpulse import config, forecast

SAMPLE = json.loads((config.ROOT_DIR / "docs" / "euskalmet_trends.json").read_text(encoding="utf-8"))
SAMPLE_DAY = date(2026, 11, 13)
HOUR = 3600
# 2026-11-13 10:20 in Bilbao (UTC+1 in winter)
NOW = int(datetime(2026, 11, 13, 10, 20, tzinfo=forecast.TZ).timestamp())
HOUR_START = NOW - NOW % HOUR  # 10:00


def local_hour(h, day=SAMPLE_DAY):
    return int(datetime(day.year, day.month, day.day, h, tzinfo=forecast.TZ).timestamp())


def hours(start, mm_per_hour, count=24):
    """A forecast list: ``count`` hours from ``start`` with the same rain."""
    return [[start + i * HOUR, mm_per_hour] for i in range(count)]


# --- parsing --------------------------------------------------------------------


def test_euskalmet_sample_gives_24_sorted_local_hours():
    parsed = forecast.parse_euskalmet(SAMPLE, SAMPLE_DAY)

    assert len(parsed) == 24
    assert [ts for ts, _ in parsed] == [local_hour(h) for h in range(24)]
    assert sum(mm for _, mm in parsed) == pytest.approx(2.5)


def test_euskalmet_entry_without_rain_value_is_skipped():
    data = {"trends": {"set": [
        {"range": "LocalTime:[05:00:00:000..05:59:59:999]", "precipitation": {"value": 1.2}},
        {"range": "LocalTime:[06:00:00:000..06:59:59:999]"},
    ]}}
    assert forecast.parse_euskalmet(data, SAMPLE_DAY) == [[local_hour(5), 1.2]]


def test_open_meteo_value_belongs_to_the_hour_before():
    data = {"hourly": {"time": [NOW + HOUR, NOW + 2 * HOUR], "precipitation": [0.5, None]}}
    assert forecast.parse_open_meteo(data) == [[NOW, 0.5]]


# --- sources ------------------------------------------------------------------------


def test_euskalmet_asks_for_today_and_tomorrow(monkeypatch):
    monkeypatch.setattr(forecast, "_euskalmet_token", lambda now: "token")
    urls = []

    def fake_get(url, params=None, headers=None):
        urls.append(url)
        return SAMPLE

    forecast.fetch_euskalmet(NOW, get=fake_get)

    assert urls[0].endswith("/at/2026/11/13/for/20261113")
    assert urls[1].endswith("/at/2026/11/13/for/20261114")


def test_euskalmet_uses_yesterdays_forecast_when_today_is_not_published(monkeypatch):
    monkeypatch.setattr(forecast, "_euskalmet_token", lambda now: "token")
    urls = []

    def fake_get(url, params=None, headers=None):
        urls.append(url)
        if "/at/2026/11/13/" in url:
            raise forecast.NotFound(url)
        return SAMPLE

    assert forecast.fetch_euskalmet(NOW, get=fake_get)
    assert any("/at/2026/11/12/for/20261113" in url for url in urls)


def test_euskalmet_without_email_fails_cleanly(monkeypatch):
    monkeypatch.setattr(config, "EUSKALMET_EMAIL", "")
    with pytest.raises(forecast.ForecastError):
        forecast.fetch_euskalmet(NOW, get=lambda *a, **k: SAMPLE)


# --- get_forecast: sources, fallback and cache ----------------------------------


def fetcher(result):
    def fetch(now):
        if isinstance(result, Exception):
            raise result
        return result
    return fetch


def test_primary_source_is_used_and_cached(tmp_path):
    cache = tmp_path / "cache.json"
    fetchers = {"euskalmet": fetcher(hours(NOW, 0.1)), "open-meteo": fetcher(OSError("unused"))}

    result = forecast.get_forecast(NOW, cache, "euskalmet", fetchers)

    assert result["source"] == "euskalmet"
    assert result["fetched_at"] == NOW
    assert forecast.load_cache(cache) == result


def test_fallback_when_euskalmet_fails(tmp_path):
    fetchers = {"euskalmet": fetcher(OSError("no Internet")), "open-meteo": fetcher(hours(NOW, 0.2))}

    result = forecast.get_forecast(NOW, tmp_path / "cache.json", "euskalmet", fetchers)

    assert result["source"] == "open-meteo"


def test_empty_answer_counts_as_failure(tmp_path):
    fetchers = {"euskalmet": fetcher([]), "open-meteo": fetcher(hours(NOW, 0.2))}
    assert forecast.get_forecast(NOW, tmp_path / "c.json", "euskalmet", fetchers)["source"] == "open-meteo"


def test_both_fail_gives_the_old_cache(tmp_path):
    cache = tmp_path / "cache.json"
    old = {"source": "euskalmet", "fetched_at": NOW - 10 * HOUR, "hours": hours(NOW - 10 * HOUR, 0.3, 48)}
    forecast.save_cache(old, cache)
    failing = {"euskalmet": fetcher(OSError()), "open-meteo": fetcher(OSError())}

    assert forecast.get_forecast(NOW, cache, "euskalmet", failing) == old


def test_both_fail_and_no_cache_gives_none(tmp_path):
    failing = {"euskalmet": fetcher(OSError()), "open-meteo": fetcher(OSError())}
    assert forecast.get_forecast(NOW, tmp_path / "cache.json", "euskalmet", failing) is None


def test_young_cache_needs_no_request(tmp_path):
    cache = tmp_path / "cache.json"
    recent = {"source": "euskalmet", "fetched_at": NOW - 600, "hours": hours(NOW, 0.1)}
    forecast.save_cache(recent, cache)
    must_not_run = {"euskalmet": fetcher(AssertionError("no request expected"))}

    assert forecast.get_forecast(NOW, cache, "euskalmet", must_not_run, refresh_s=HOUR) == recent


def test_broken_cache_file_is_ignored(tmp_path):
    cache = tmp_path / "cache.json"
    cache.write_text("{not json", encoding="utf-8")
    assert forecast.load_cache(cache) is None


# --- summary: rain in the window and freshness (T-34) -----------------------------


def fresh(mm_per_hour, fetched_ago_s=0):
    return {"source": "euskalmet", "fetched_at": NOW - fetched_ago_s, "hours": hours(HOUR_START - HOUR, mm_per_hour, 48)}


def test_rain_is_summed_from_the_current_hour_for_the_window():
    summary = forecast.forecast_summary(fresh(0.5), NOW, window_h=6)
    # 10:00 to 16:20 -> the hours starting 10, 11, ..., 16 = 7 hours
    assert summary["rain_mm"] == pytest.approx(3.5)
    assert summary["status"] == "fresh"


def test_forecast_older_than_6_h_is_outdated():
    summary = forecast.forecast_summary(fresh(1.0, fetched_ago_s=7 * HOUR), NOW, window_h=6)
    assert summary["status"] == "outdated"
    assert summary["age_h"] == 7.0


def test_forecast_exactly_6_h_old_is_still_fresh():
    assert forecast.forecast_summary(fresh(1.0, 6 * HOUR), NOW, 6)["status"] == "fresh"


def test_no_forecast_is_unavailable():
    assert forecast.forecast_summary(None, NOW, 6)["status"] == "unavailable"


def test_forecast_not_covering_the_window_is_unavailable():
    short = {"source": "open-meteo", "fetched_at": NOW, "hours": hours(HOUR_START, 1.0, 3)}
    assert forecast.forecast_summary(short, NOW, 6)["status"] == "unavailable"


def test_forecast_fetched_after_the_reading_is_fresh():
    # The rule engine judges a reading from a few minutes ago with a forecast
    # downloaded just now.
    summary = forecast.forecast_summary(fresh(1.0, fetched_ago_s=-240), NOW, 6)
    assert summary["status"] == "fresh"
    assert summary["age_h"] == 0.0