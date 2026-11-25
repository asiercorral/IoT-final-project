"""T-32: rain forecast for Bilbao, with a local cache.

``get_forecast()`` returns one dict, or None when no forecast was ever
downloaded:

    {
      "source": "euskalmet",           # or "open-meteo"
      "fetched_at": 1764000000,        # when it was downloaded (Unix time)
      "hours": [[1764000000, 0.4], ...] # [start of the hour, rain in mm], sorted
    }

Where the forecast comes from, in this order (decision 001):

1. the cache, if it is younger than ``FORECAST_REFRESH_S`` (1 h): no request;
2. the source in ``FORECAST_SOURCE`` (Euskalmet), then the other one;
3. if both fail: the last cache, whatever its age.

Whether a forecast is fresh enough to change the advice is decided by
``forecast_summary()`` (T-34): older than 6 h, or not covering the next
hours, means it is never used.

Run on the Pi or a laptop:

    python -m plantpulse.forecast    # fetch (or read the cache) and print the next 6 h
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from plantpulse import config

log = logging.getLogger(__name__)

TZ = ZoneInfo("Europe/Madrid")  # Euskalmet gives local hours
TIMEOUT_S = 15
HOUR_S = 3600

EUSKALMET_BASE = "https://api.euskadi.eus"
EUSKALMET_TRENDS = (
    "/euskalmet/weather/regions/basque_country/zones/great_bilbao/locations/bilbao"
    "/forecast/trends/measures/at/{at:%Y/%m/%d}/for/{day:%Y%m%d}"
)
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

_LOCAL_HOUR = re.compile(r"LocalTime:\[(\d{2}):")


class ForecastError(Exception):
    """A forecast source did not give a usable answer."""


class NotFound(ForecastError):
    """HTTP 404: for Euskalmet, today's forecast is not published yet."""


# --- parsing (no network, tested with docs/euskalmet_trends.json) ------------


def parse_euskalmet(data, day):
    """Hourly rain from one Euskalmet trends/measures answer for ``day``.

    The entries are not sorted and give local hours ("LocalTime:[05:00...]").
    Only the numeric precipitation is used, never the weather symbol.
    """
    hours = []
    for entry in data["trends"]["set"]:
        match = _LOCAL_HOUR.match(entry.get("range", ""))
        rain = (entry.get("precipitation") or {}).get("value")
        if match is None or rain is None:
            continue
        start = datetime(day.year, day.month, day.day, int(match.group(1)), tzinfo=TZ)
        hours.append([int(start.timestamp()), float(rain)])
    return sorted(hours)


def parse_open_meteo(data):
    """Hourly rain from an Open-Meteo answer requested with ``timeformat=unixtime``.

    Open-Meteo gives at each time stamp the rain of the hour *before* it, so
    the hour starts one hour earlier.
    """
    hourly = data["hourly"]
    return sorted(
        [int(ts) - HOUR_S, float(mm)]
        for ts, mm in zip(hourly["time"], hourly["precipitation"])
        if mm is not None
    )


# --- sources ------------------------------------------------------------------


def _http_get(url, params=None, headers=None):
    import requests

    response = requests.get(url, params=params, headers=headers, timeout=TIMEOUT_S)
    if response.status_code == 404:
        raise NotFound(url)
    response.raise_for_status()
    return response.json()


def _euskalmet_token(now):
    """Signed JWT for the Euskalmet API (see decision 001)."""
    import jwt

    if not config.EUSKALMET_EMAIL:
        raise ForecastError("EUSKALMET_EMAIL is not set in .env")
    try:
        key = Path(config.EUSKALMET_PRIVATE_KEY).read_text(encoding="utf-8")
    except OSError as exc:
        raise ForecastError(f"private key not readable: {exc}") from None
    claims = {
        "aud": "met01.apikey",
        "iss": "PlantPulse",
        "iat": int(now),
        "exp": int(now) + HOUR_S,
        "version": "1.0.0",
        "email": config.EUSKALMET_EMAIL,
    }
    return jwt.encode(claims, key, algorithm="RS256")


def fetch_euskalmet(now, get=_http_get):
    """Hourly rain for today and tomorrow (the next 6 h can cross midnight)."""
    headers = {"Authorization": f"Bearer {_euskalmet_token(now)}"}
    today = datetime.fromtimestamp(now, TZ).date()
    hours = []
    for day in (today, today + timedelta(days=1)):
        # Early in the morning today's forecast may not exist yet: use yesterday's.
        for at in (today, today - timedelta(days=1)):
            try:
                data = get(EUSKALMET_BASE + EUSKALMET_TRENDS.format(at=at, day=day), headers=headers)
                break
            except NotFound:
                continue
        else:
            raise ForecastError(f"Euskalmet has no forecast for {day}")
        hours += parse_euskalmet(data, day)
    return sorted(hours)


def fetch_open_meteo(now, get=_http_get):
    """Hourly rain from Open-Meteo (no key needed)."""
    params = {
        "latitude": config.LATITUDE,
        "longitude": config.LONGITUDE,
        "hourly": "precipitation",
        "timeformat": "unixtime",
        "forecast_days": 3,
    }
    return parse_open_meteo(get(OPEN_METEO_URL, params=params))


FETCHERS = {"euskalmet": fetch_euskalmet, "open-meteo": fetch_open_meteo}


# --- cache --------------------------------------------------------------------


def load_cache(path):
    """The cached forecast, or None if there is none or it is unreadable."""
    try:
        forecast = json.loads(Path(path).read_text(encoding="utf-8"))
        int(forecast["fetched_at"])
        if not isinstance(forecast["hours"], list):
            raise TypeError("hours must be a list")
        return forecast
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("forecast cache %s is unreadable (%s); ignoring it", path, exc)
        return None


def save_cache(forecast, path):
    """Write the cache in one step, so a power cut never leaves half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(forecast), encoding="utf-8")
    tmp.replace(path)


# --- public function ----------------------------------------------------------


def get_forecast(
    now=None,
    cache_path=None,
    source=None,
    fetchers=None,
    refresh_s=None,
):
    """The newest forecast we can get; never raises. See the module docstring."""
    now = time.time() if now is None else now
    cache_path = cache_path or config.FORECAST_CACHE
    fetchers = fetchers or FETCHERS
    source = source or config.FORECAST_SOURCE
    refresh_s = config.FORECAST_REFRESH_S if refresh_s is None else refresh_s

    cached = load_cache(cache_path)
    if cached is not None and 0 <= now - cached["fetched_at"] < refresh_s:
        return cached

    if source not in fetchers:
        log.warning("unknown FORECAST_SOURCE %r; trying %s", source, ", ".join(fetchers))
    order = [source] + [name for name in fetchers if name != source]
    for name in order:
        if name not in fetchers:
            continue
        try:
            hours = fetchers[name](now)
            if not hours:
                raise ForecastError("answer has no hourly values")
        except Exception as exc:  # no Internet, expired key, API change ...
            log.warning("forecast from %s failed: %s", name, exc)
            continue
        forecast = {"source": name, "fetched_at": int(now), "hours": hours}
        try:
            save_cache(forecast, cache_path)
        except OSError as exc:
            log.warning("could not write the forecast cache: %s", exc)
        return forecast

    if cached is not None:
        log.warning("no source answered; using the cached forecast from %s", cached["source"])
    return cached


# --- what the rules need (T-34) ------------------------------------------------


def rain_mm(forecast, now, window_h):
    """Rain from the current hour over the next ``window_h`` hours, in mm.

    None when the forecast does not cover the whole window.
    """
    start = now - now % HOUR_S
    end = now + window_h * HOUR_S
    covered = [mm for ts, mm in forecast["hours"] if start <= ts < end]
    if len(covered) < window_h:
        return None
    return round(sum(covered), 1)


def forecast_summary(forecast, now, window_h, max_age_s=config.FORECAST_MAX_AGE_S):
    """The forecast as the rule engine and the web page use it.

    ``status`` is "fresh", "outdated" (older than ``max_age_s``) or
    "unavailable" (no forecast, or it does not cover the window). Only a
    fresh forecast may change the advice.
    """
    if not forecast:
        return {
            "status": "unavailable", "source": None, "fetched_at": None,
            "age_h": None, "rain_mm": None, "window_h": window_h,
        }
    # The forecast is often fetched a little after the reading being judged
    # (``now``), so a negative age counts as 0.
    age_s = max(now - forecast["fetched_at"], 0)
    mm = rain_mm(forecast, now, window_h)
    if mm is None:
        status = "unavailable"
    elif age_s > max_age_s:
        status = "outdated"
    else:
        status = "fresh"
    return {
        "status": status,
        "source": forecast["source"],
        "fetched_at": forecast["fetched_at"],
        "age_h": round(age_s / HOUR_S, 1),
        "rain_mm": mm,
        "window_h": window_h,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    current = time.time()
    summary = forecast_summary(get_forecast(current), current, window_h=6)
    print(json.dumps(summary, indent=2))