"""T-24: rule engine. Compare the readings with the plant profile and decide
the plant state, with a short reason for pupils.

Every rule that applies adds one *finding*. The screen shows the most severe
one (FAULT > ATTENTION > CHECK > NORMAL); the web page can list them all.
Rules, from most to least severe:

    FAULT      a sensor gives no valid reading; no new reading for
               ``STALE_AFTER_S`` seconds (acquisition stopped)
    ATTENTION  soil critically dry; soil saturated for ``saturated_h`` hours;
               air below ``severe_cold_below_c`` for ``duration_h`` hours
    CHECK      soil dry; soil wet for ``wet_check_h`` hours;
               air below ``cold_below_c`` or above ``hot_above_c`` for ``duration_h`` hours
    NORMAL     everything within the profile; or soil dry, but rain is
               expected and reaches the plant (WAIT_RAIN, T-33)

Temperature rules wait ``duration_h`` so that one noisy DHT reading near a
limit does not make the screen jump. When two findings are equally severe,
the soil one is shown first. Humidity is context only.

Run on the Pi next to the acquisition loop, which writes the readings CSV:

    python -m plantpulse.acquisition --interval 10      # terminal 1
    python -m plantpulse.rule_engine --interval 10      # terminal 2, print only
    python -m plantpulse.rule_engine --publish          # also publish to the screen
    python -m plantpulse.rule_engine --once             # evaluate the last reading, exit

Rain (T-33, T-34): a fresh forecast with at least ``rain.min_mm`` in the next
``rain.window_h`` hours turns "soil getting dry" (CHECK_DRY) into WAIT_RAIN,
but only for a plant with ``rain_exposed: true``. It never delays
ATTENTION_DRY. A forecast older than 6 h or missing is shown as outdated or
unavailable and changes nothing.

Persistent low light (T-42) comes later.
"""

from __future__ import annotations

import argparse
import csv
import logging
import signal
import time
from pathlib import Path

from plantpulse import config, forecast, state
from plantpulse.profile import load_profile

log = logging.getLogger(__name__)

SENSOR_KEYS = ("temperature_c", "humidity_pct", "soil_moisture_raw", "light_pct")
SENSOR_NAMES = {
    "temperature_c": "temperature",
    "humidity_pct": "humidity",
    "soil_moisture_raw": "soil",
    "light_pct": "light",
}
SEVERITY = {name: rank for rank, name in enumerate(state.STATES)}  # NORMAL lowest

# A gap longer than this between two readings breaks a "wet for X hours" run,
# so a Pi that was switched off is not counted as wet the whole time.
MAX_GAP_S = 3 * config.READ_INTERVAL_S

# The newest reading must be younger than this, otherwise the state is FAULT
# (two missed readings = 10 min with the default interval of 5 min).
STALE_AFTER_S = 2 * config.READ_INTERVAL_S


# --- helpers -----------------------------------------------------------------


def soil_index(raw_mv, dry_mv=config.SOIL_DRY_MV, wet_mv=config.SOIL_WET_MV):
    """Soil moisture index 0-100 % between the dry and the wet calibration cup.

    Works for both probe types: whichever of dry and wet is higher. Returns
    None when there is no reading.
    """
    if raw_mv is None:
        return None
    if dry_mv == wet_mv:
        raise ValueError("SOIL_DRY_MV and SOIL_WET_MV must be different")
    pct = (raw_mv - dry_mv) / (wet_mv - dry_mv) * 100
    return round(min(max(pct, 0.0), 100.0), 1)


def hours_continuously(samples, condition, now, max_gap_s=MAX_GAP_S):
    """How long ``condition(value)`` has held without a break, in hours.

    ``samples`` is a list of ``(timestamp, value)``, oldest first, ending with
    the current reading. A missing value, a value that fails the condition or
    a gap longer than ``max_gap_s`` ends the run. Returns 0.0 when the current
    reading does not meet the condition.
    """
    start = None
    later_ts = None
    for ts, value in reversed(samples):
        if value is None or not condition(value):
            break
        if later_ts is not None and later_ts - ts > max_gap_s:
            break
        start = later_ts = ts
    return 0.0 if start is None else max(now - start, 0) / 3600


def _finding(sensor, level, code, reason):
    return {"sensor": sensor, "level": level, "code": code, "reason": reason}


# --- rain (T-33, T-34) ---------------------------------------------------------


def rain_delays_prompt(profile, summary):
    """T-33: rain may delay a "soil getting dry" prompt only if it reaches the
    plant and the forecast is fresh. Callers never ask this for critically
    dry soil."""
    return (
        profile["rain_exposed"]
        and summary["status"] == "fresh"
        and summary["rain_mm"] >= profile["rain"]["min_mm"]
    )


def rain_note(profile, summary):
    """One sentence for the web page: which forecast was used and why the
    advice waits for rain or not (T-35)."""
    window = summary["window_h"]
    if not profile["rain_exposed"]:
        return "The plant is sheltered, so rain does not change the advice."
    if summary["status"] == "unavailable":
        return "No forecast available, so the advice does not wait for rain."
    if summary["status"] == "outdated":
        return (f"The forecast is {summary['age_h']:.0f} h old (outdated), "
                "so the advice does not wait for rain.")
    if rain_delays_prompt(profile, summary):
        return (f"{summary['rain_mm']:.1f} mm of rain expected in the next {window} h: "
                "a dry-soil reminder waits for the rain.")
    return (f"Only {summary['rain_mm']:.1f} mm of rain expected in the next {window} h: "
            "not enough to wait for.")


# --- rules -------------------------------------------------------------------


def _fault_rule(sensors):
    missing = [SENSOR_NAMES[key] for key in SENSOR_KEYS if sensors.get(key) is None]
    if not missing:
        return None
    return _finding(
        "sensors", "FAULT", "FAULT_SENSOR",
        f"No valid reading from the {', '.join(missing)} sensor. Tell the teacher.",
    )


def _soil_rule(pct, history, now, soil, rain_mm=None):
    """At most one soil finding: dry and wet cannot both be true.

    ``rain_mm`` is set only when rain may delay the prompt (``rain_delays_prompt``).
    """
    if pct is None:
        return None  # already reported by the fault rule
    if pct < soil["critical_below_pct"]:
        return _finding("soil", "ATTENTION", "ATTENTION_DRY",
                        f"Soil is very dry ({pct:.0f} %). Water the plant today.")

    saturated_h = hours_continuously(history, lambda v: v >= soil["saturated_above_pct"], now)
    if saturated_h >= soil["saturated_h"]:
        return _finding("soil", "ATTENTION", "ATTENTION_WET",
                        f"Soil has been soaking wet for {saturated_h:.0f} h. "
                        "Do not water; empty the saucer so the roots get air.")

    if pct < soil["dry_below_pct"]:
        if rain_mm is not None:
            return _finding("soil", "NORMAL", "WAIT_RAIN",
                            f"Soil is getting dry ({pct:.0f} %), but {rain_mm:.1f} mm of rain "
                            "is expected soon. No need to water now.")
        return _finding("soil", "CHECK", "CHECK_DRY",
                        f"Soil is getting dry ({pct:.0f} %). "
                        "Feel the soil and water if it is dry below the surface.")

    wet_h = hours_continuously(history, lambda v: v > soil["wet_above_pct"], now)
    if wet_h >= soil["wet_check_h"]:
        return _finding("soil", "CHECK", "CHECK_WET",
                        f"Soil has stayed very wet for {wet_h:.0f} h. "
                        "Do not water; check that the pot drains.")
    return None


def _air_rule(temperature, history, now, air):
    """At most one air finding: the most severe that has lasted ``duration_h``."""
    if temperature is None:
        return None  # already reported by the fault rule
    duration = air["duration_h"]

    def lasted(condition):
        return hours_continuously(history, condition, now) >= duration

    if lasted(lambda t: t < air["severe_cold_below_c"]):
        return _finding("air", "ATTENTION", "ATTENTION_COLD",
                        f"The air is very cold ({temperature:.0f} °C). "
                        "Move the plant somewhere warmer or cover it.")
    if lasted(lambda t: t < air["cold_below_c"]):
        return _finding("air", "CHECK", "CHECK_COLD",
                        f"The air is cold for this plant ({temperature:.0f} °C). "
                        "Check the leaves for dark spots.")
    if lasted(lambda t: t > air["hot_above_c"]):
        return _finding("air", "CHECK", "CHECK_HOT",
                        f"The air is hot for this plant ({temperature:.0f} °C). "
                        "Check the soil; it dries out faster in the heat.")
    return None


# --- evaluation --------------------------------------------------------------


def evaluate(
    reading,
    profile,
    history=(),
    dry_mv=config.SOIL_DRY_MV,
    wet_mv=config.SOIL_WET_MV,
    forecast_data=None,
):
    """Decide the plant state for one reading.

    ``reading`` is one telemetry reading ({"timestamp", "sensors"}) as built by
    ``acquisition.build_reading``. ``history`` holds earlier readings in the
    same format, oldest first; it is only needed for the wet rules.
    ``forecast_data`` is the result of ``forecast.get_forecast()``, or None.

    Returns a state message in the format of ``state.build_state`` with two
    extra keys: ``soil_pct`` and ``findings`` (every finding, most severe first).
    Its ``forecast`` is the forecast summary with ``used`` (did it change the
    advice?) and ``note`` (why or why not).
    """
    now = reading["timestamp"]
    sensors = reading["sensors"]
    earlier = [r for r in history if r["timestamp"] < now]

    pct = soil_index(sensors.get("soil_moisture_raw"), dry_mv, wet_mv)
    soil_series = [
        (r["timestamp"], soil_index(r["sensors"].get("soil_moisture_raw"), dry_mv, wet_mv))
        for r in earlier
    ]
    soil_series.append((now, pct))

    temperature = sensors.get("temperature_c")
    air_series = [(r["timestamp"], r["sensors"].get("temperature_c")) for r in earlier]
    air_series.append((now, temperature))

    rain = forecast.forecast_summary(forecast_data, now, profile["rain"]["window_h"])
    delay_mm = rain["rain_mm"] if rain_delays_prompt(profile, rain) else None

    findings = [
        f
        for f in (
            _fault_rule(sensors),
            _soil_rule(pct, soil_series, now, profile["soil"], delay_mm),
            _air_rule(temperature, air_series, now, profile["air"]),
        )
        if f is not None
    ]
    # sort() is stable: equally severe findings keep the order above (soil first)
    findings.sort(key=lambda f: SEVERITY[f["level"]], reverse=True)

    if findings:
        worst = findings[0]
        level, code, reason = worst["level"], worst["code"], worst["reason"]
    else:
        level, code = "NORMAL", "OK"
        reason = f"Soil moisture is fine ({pct:.0f} %)."

    rain["used"] = any(f["code"] == "WAIT_RAIN" for f in findings)
    rain["note"] = rain_note(profile, rain)
    message = state.build_state(level, reason, status_code=code, forecast=rain, timestamp=now)
    message["soil_pct"] = pct
    message["findings"] = findings
    return message


def stale_state(now, last_ts=None):
    """FAULT message when there is no recent reading (acquisition stopped)."""
    if last_ts is None:
        reason = "No sensor readings arrive. Tell the teacher."
    else:
        minutes = (now - last_ts) / 60
        reason = f"No new sensor reading for {minutes:.0f} min. Tell the teacher."
    message = state.build_state("FAULT", reason, status_code="FAULT_STALE", timestamp=now)
    message["soil_pct"] = None
    message["findings"] = [_finding("sensors", "FAULT", "FAULT_STALE", reason)]
    return message


# --- reading the acquisition CSV ---------------------------------------------


def _number(cell):
    return None if cell in ("", None) else float(cell)


def load_readings(path, since):
    """Readings from the acquisition CSV with ``timestamp >= since``, oldest first."""
    path = Path(path)
    if not path.is_file():
        return []
    readings = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                ts = int(float(row["timestamp"]))
                if ts < since:
                    continue
                readings.append({
                    "timestamp": ts,
                    "sensors": {key: _number(row.get(key)) for key in SENSOR_KEYS},
                })
            except (KeyError, ValueError):
                log.warning("skipping unreadable CSV row: %s", row)
    readings.sort(key=lambda r: r["timestamp"])
    return readings


def evaluate_latest(
    csv_path,
    profile,
    clock=time.time,
    dry_mv=config.SOIL_DRY_MV,
    wet_mv=config.SOIL_WET_MV,
    stale_after_s=STALE_AFTER_S,
    forecast_data=None,
):
    """Evaluate the newest reading in the CSV, with enough history for the wet rules.

    No reading, or a newest reading older than ``stale_after_s``, gives FAULT:
    an old state must never stay on the screen as if it were current.
    """
    now = clock()
    window_h = max(
        profile["soil"]["saturated_h"], profile["soil"]["wet_check_h"], profile["air"]["duration_h"]
    ) + 1
    readings = load_readings(csv_path, since=now - window_h * 3600)
    if not readings:
        return stale_state(now)
    latest = readings[-1]
    if now - latest["timestamp"] > stale_after_s:
        return stale_state(now, latest["timestamp"])
    return evaluate(latest, profile, readings[:-1], dry_mv, wet_mv, forecast_data)


# --- program -----------------------------------------------------------------


def _stop(signum, frame):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m plantpulse.rule_engine",
        description="Evaluate the newest reading against the plant profile.",
    )
    parser.add_argument("--csv", type=Path, default=config.READINGS_CSV,
                        help="readings file written by the acquisition loop (default: %(default)s)")
    parser.add_argument("--plant", default=None, help="plant profile (default: PLANTPULSE_PLANT)")
    parser.add_argument("--interval", type=int, default=config.READ_INTERVAL_S,
                        help="seconds between evaluations (default: %(default)s)")
    parser.add_argument("--once", action="store_true", help="evaluate once and exit")
    parser.add_argument("--publish", action="store_true",
                        help=f"publish the state to {config.TOPIC_STATE}")
    parser.add_argument("--host", default=config.MQTT_HOST)
    parser.add_argument("--port", type=int, default=config.MQTT_PORT)
    parser.add_argument("--no-forecast", action="store_true",
                        help="do not download a forecast (it then counts as unavailable)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    profile = load_profile(args.plant)
    log.info("profile: %s", profile["name"])

    client = None
    if args.publish:
        try:
            client = state.make_client(f"{config.DEVICE_ID}-rules")
            client.connect(args.host, args.port)
        except ImportError as exc:
            parser.exit(1, f"paho-mqtt not found ({exc}). Run: pip install -r requirements.txt\n")
        except OSError as exc:
            parser.exit(1, f"Cannot reach the MQTT broker at {args.host}:{args.port} ({exc})\n")
        client.loop_start()

    try:
        while True:
            # At most one download per hour; otherwise the cache (forecast.py)
            forecast_data = None if args.no_forecast else forecast.get_forecast()
            message = evaluate_latest(args.csv, profile, forecast_data=forecast_data)
            if message["status_code"] == "FAULT_STALE":
                log.warning("no recent readings in %s; is the acquisition loop running?", args.csv)
            log.info("%s (%s): %s", message["state"], message["status_code"], message["reason"])
            if client is not None:
                state.publish_state(client, message)
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log.info("stopped")
    finally:
        if client is not None:
            client.loop_stop()
            client.disconnect()


if __name__ == "__main__":
    main()
