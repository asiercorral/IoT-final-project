"""Where the web page gets its data.

- Readings and history: the SQLite database (decision 002), read-only. The
  MQTT subscriber (T-22) is the only program that writes it.
- Plant state: the retained message on ``config.TOPIC_STATE``, the same one
  the LCD shows, so pupils and teacher always see the same state.
- Forecast: the local cache written by ``plantpulse/forecast.py``.

Nothing here needs the Internet, and every source can be missing: the page
then says what is missing instead of failing.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from plantpulse import config, forecast, state
from plantpulse.rule_engine import SENSOR_KEYS, soil_index

log = logging.getLogger(__name__)

# The rule engine publishes a state every reading cycle. A state older than
# three cycles means it is not running any more.
STATE_STALE_AFTER_S = 3 * config.READ_INTERVAL_S

MAX_HISTORY_HOURS = 31 * 24

SENSOR_LABELS = {
    "temperature_c": "Temperature sensor",
    "humidity_pct": "Air humidity sensor",
    "soil_moisture_raw": "Soil moisture sensor",
    "light_pct": "Light sensor",
}

SOURCE_NAMES = {"euskalmet": "Euskalmet", "open-meteo": "Open-Meteo"}

# One sentence per status code that explains *why* the state matters (US-02).
# The rule engine's reason already says which reading caused it and what to do.
EXPLANATIONS = {
    "OK": "Soil moisture and air are within the range this plant likes.",
    "CHECK_DRY": "Roots take up water from the soil. The top can be dry while "
                 "deeper soil is still moist, so feel it before watering.",
    "CHECK_WET": "Roots need air as well as water. Soil that stays wet for a long "
                 "time pushes the air out.",
    "ATTENTION_DRY": "In very dry soil the roots cannot take up water and the "
                     "leaves start to droop.",
    "ATTENTION_WET": "In soaking wet soil the roots get no air and can start to rot.",
    "CHECK_COLD": "Cold air slows the plant down; warm-weather plants can get "
                  "dark spots on their leaves.",
    "CHECK_HOT": "In hot air the plant loses water through its leaves faster and "
                 "the soil dries sooner.",
    "ATTENTION_COLD": "Very cold air can damage leaves and roots in a single night.",
    "FAULT_SENSOR": "Without a valid reading the system cannot judge the plant, "
                    "so it shows a fault instead of guessing.",
    "FAULT_STALE": "No new readings arrive, so the last state could be wrong. "
                   "The acquisition program or the Pi may have stopped.",
}


# --- database -------------------------------------------------------------------


def _open_read_only(db_path):
    """Read-only connection, or None if the database does not exist yet."""
    path = Path(db_path)
    if not path.is_file():
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_reading(row, dry_mv, wet_mv):
    reading = {"timestamp": row["timestamp"]}
    for key in SENSOR_KEYS:
        reading[key] = row[key]
    reading["soil_pct"] = soil_index(row["soil_moisture_raw"], dry_mv, wet_mv)
    return reading


def _query(db_path, sql, params):
    conn = _open_read_only(db_path)
    if conn is None:
        return []
    try:
        with closing(conn):
            return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:  # no readings table yet, locked file ...
        log.warning("cannot read %s: %s", db_path, exc)
        return []


def latest_reading(db_path, device_id=config.DEVICE_ID,
                   dry_mv=config.SOIL_DRY_MV, wet_mv=config.SOIL_WET_MV):
    """The newest stored reading, with ``soil_pct`` added, or None."""
    rows = _query(
        db_path,
        "SELECT * FROM readings WHERE device_id = ? ORDER BY timestamp DESC LIMIT 1",
        (device_id,),
    )
    return _row_to_reading(rows[0], dry_mv, wet_mv) if rows else None


def readings_since(db_path, since, device_id=config.DEVICE_ID,
                   dry_mv=config.SOIL_DRY_MV, wet_mv=config.SOIL_WET_MV):
    """Stored readings with ``timestamp >= since``, oldest first."""
    rows = _query(
        db_path,
        "SELECT * FROM readings WHERE device_id = ? AND timestamp >= ? ORDER BY timestamp",
        (device_id, int(since)),
    )
    return [_row_to_reading(row, dry_mv, wet_mv) for row in rows]


def faulty_sensors(reading):
    """The sensors with no valid value in a reading (T-40)."""
    if reading is None:
        return []
    return [
        {"sensor": key, "label": label, "reason": "No valid reading"}
        for key, label in SENSOR_LABELS.items()
        if reading.get(key) is None
    ]


# --- plant state over MQTT -------------------------------------------------------


class StateListener:
    """Keeps the latest retained state message from the broker.

    The paho client runs in its own thread and reconnects by itself, so the
    web server keeps working while the broker is down.
    """

    def __init__(self):
        self.message = None
        self.connected = False
        self._client = None

    def on_payload(self, raw):
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("state message is not JSON: %r", raw[:80])
            return
        if isinstance(payload, dict):
            self.message = payload

    def start(self, host=config.MQTT_HOST, port=config.MQTT_PORT):
        try:
            client = state.make_client(f"{config.DEVICE_ID}-web")
        except ImportError as exc:
            log.warning("paho-mqtt not installed (%s): the page cannot show the state", exc)
            return

        def on_connect(client, userdata, flags, reason_code, properties):
            if reason_code.is_failure:
                log.warning("broker refused the connection: %s", reason_code)
                return
            self.connected = True
            client.subscribe(config.TOPIC_STATE, qos=1)
            log.info("following %s on %s:%d", config.TOPIC_STATE, host, port)

        def on_disconnect(client, userdata, flags, reason_code, properties):
            self.connected = False

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = lambda client, userdata, msg: self.on_payload(msg.payload)
        client.connect_async(host, port)
        client.loop_start()
        self._client = client


def describe_state(message, now):
    """The state part of /api/status, also when there is no usable state."""
    if message is None:
        return {
            "state": None,
            "status_code": None,
            "reason": "No plant state received yet. Is the rule engine running "
                      "with --publish, and is the MQTT broker up?",
            "explanation": "",
            "timestamp": None,
            "age_s": None,
            "findings": [],
        }
    timestamp = message.get("timestamp")
    age_s = max(now - timestamp, 0) if isinstance(timestamp, (int, float)) else None
    if age_s is None or age_s > STATE_STALE_AFTER_S:
        minutes = "" if age_s is None else f" for {age_s / 60:.0f} min"
        return {
            "state": None,
            "status_code": None,
            "reason": f"No new plant state{minutes}. The rule engine may have "
                      "stopped, so the last state is not shown.",
            "explanation": "",
            "timestamp": timestamp,
            "age_s": age_s,
            "findings": [],
        }
    code = message.get("status_code")
    return {
        "state": state.state_of(message),
        "status_code": code,
        "reason": message.get("reason") or "",
        "explanation": EXPLANATIONS.get(code, ""),
        "timestamp": timestamp,
        "age_s": age_s,
        "findings": message.get("findings") or [],
    }


# --- forecast (T-35) ---------------------------------------------------------------


def explain_forecast(summary, profile):
    """Whether the forecast can change the advice, and why, in one sentence.

    Follows the README rules: an outdated (older than 6 h) or unavailable
    forecast is never used, and rain only matters for a plant exposed to it.
    Returns ``(used, why)``.
    """
    window_h = summary["window_h"]
    if summary["status"] == "unavailable":
        return False, (
            f"No forecast for the next {window_h} h is available (no Internet, or it "
            "has not been downloaded yet). The advice uses only the sensors."
        )
    if summary["status"] == "outdated":
        max_age_h = config.FORECAST_MAX_AGE_S // 3600
        return False, (
            f"The forecast is {summary['age_h']:.0f} h old, more than {max_age_h} h, "
            "so it is not used. The advice uses only the sensors."
        )
    rain = summary["rain_mm"]
    if not profile["rain_exposed"]:
        return False, (
            f"{rain} mm of rain expected in the next {window_h} h, but the plant is "
            "sheltered, so rain cannot water it. The advice uses only the sensors."
        )
    if rain >= profile["rain"]["min_mm"]:
        return True, (
            f"{rain} mm of rain expected in the next {window_h} h. The plant is outdoors, "
            "so watering can wait for the rain, unless the soil is very dry."
        )
    return True, (
        f"Little or no rain expected ({rain} mm in the next {window_h} h), "
        "so the watering advice is not delayed."
    )


def forecast_used(now, cache_path, profile):
    """``forecast.forecast_summary`` of the local cache, plus ``used``, ``why``
    and a readable ``source_name``. Never downloads anything."""
    cached = forecast.load_cache(cache_path)
    summary = forecast.forecast_summary(cached, now, profile["rain"]["window_h"])
    summary["source_name"] = SOURCE_NAMES.get(summary["source"], summary["source"])
    summary["used"], summary["why"] = explain_forecast(summary, profile)
    return summary
