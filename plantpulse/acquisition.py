"""Acquisition loop: read the sensors on a fixed interval, timestamp each
reading and append it to a local CSV file.

Run on the Pi:

    python -m plantpulse.acquisition                 # every 5 min, until stopped
    python -m plantpulse.acquisition --interval 10   # short demo interval
    python -m plantpulse.acquisition --once          # one reading, then exit

Missing values are written as empty cells, never as zero. Publishing each
reading over MQTT comes in Sprint 2; ``build_reading`` already returns it in
the telemetry payload format.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import signal
import time
from datetime import datetime
from pathlib import Path

from plantpulse import config, sensors

log = logging.getLogger(__name__)

SENSOR_KEYS = list(sensors.VALID_RANGES)
CSV_FIELDS = ["timestamp", "time_local", *SENSOR_KEYS]


def build_reading(values, timestamp, device_id=config.DEVICE_ID):
    """One reading in the telemetry payload format (the rule engine adds the status)."""
    return {
        "device_id": device_id,
        "timestamp": int(timestamp),
        "sensors": {key: values.get(key) for key in SENSOR_KEYS},
    }


def to_csv_row(reading):
    """Flatten a reading into one CSV row; None becomes an empty cell."""
    timestamp = reading["timestamp"]
    row = {
        "timestamp": timestamp,
        # Local time with its UTC offset, so day and night are easy to read
        # in the file and stay correct across the change to winter time.
        "time_local": datetime.fromtimestamp(timestamp)
        .astimezone()
        .isoformat(timespec="seconds"),
    }
    for key in SENSOR_KEYS:
        value = reading["sensors"][key]
        row[key] = "" if value is None else value
    return row


class CsvStore:
    """Append-only CSV file of readings, one row per reading."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._set_aside_if_other_columns()

    def _is_empty(self):
        return not self.path.is_file() or self.path.stat().st_size == 0

    def _set_aside_if_other_columns(self):
        # A file written by an older version with other columns would be
        # misread if rows were appended to it, so keep it under another name.
        if self._is_empty():
            return
        with self.path.open(newline="", encoding="utf-8") as f:
            header = next(csv.reader(f), [])
        if header != CSV_FIELDS:
            old = self.path.with_name(f"{self.path.stem}-{int(time.time())}{self.path.suffix}")
            self.path.rename(old)
            log.warning("%s had other columns; moved it to %s", self.path.name, old.name)

    def append(self, reading):
        write_header = self._is_empty()
        with self.path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerow(to_csv_row(reading))
            # Each row reaches the SD card before the next cycle, so a power
            # cut loses at most the reading being written.
            f.flush()
            os.fsync(f.fileno())


def acquire_once(store, sensor_source=None, clock=time.time):
    """Read every sensor once, timestamp the result, store it and return it."""
    timestamp = clock()
    reading = build_reading(sensors.read_all(sensor_source), timestamp)
    store.append(reading)
    return reading


def run(
    store,
    sensor_source,
    interval,
    cycles=None,
    clock=time.time,
    monotonic=time.monotonic,
    sleep=time.sleep,
):
    """Take a reading every ``interval`` seconds; ``cycles=None`` runs forever.

    Readings stay on a fixed schedule instead of drifting by the time each
    read takes. A cycle that fails is logged and the loop carries on.
    """
    next_due = monotonic()
    done = 0
    while cycles is None or done < cycles:
        try:
            reading = acquire_once(store, sensor_source, clock)
            missing = [key for key, value in reading["sensors"].items() if value is None]
            log.info(
                "reading stored: %s%s",
                reading["sensors"],
                f" (missing: {', '.join(missing)})" if missing else "",
            )
        except Exception:
            log.exception("reading cycle failed; trying again next cycle")
        done += 1
        if cycles is not None and done >= cycles:
            break

        next_due += interval
        now = monotonic()
        if next_due < now:
            skipped = int((now - next_due) // interval) + 1
            next_due += skipped * interval
            log.warning("reading took longer than the interval; skipping %d slot(s)", skipped)
        sleep(next_due - now)


def _stop(signum, frame):
    # systemd stops services with SIGTERM; end the loop like Ctrl+C does.
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m plantpulse.acquisition",
        description="Read the PlantPulse sensors on a fixed interval and store them in a CSV file.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=config.READ_INTERVAL_S,
        help="seconds between readings (default: %(default)s)",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=config.READINGS_CSV,
        help="file to append readings to (default: %(default)s)",
    )
    parser.add_argument("--once", action="store_true", help="take one reading and exit")
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be a positive number of seconds")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _stop)

    # Open the sensors before the loop, so a missing library or a wrong
    # setting stops the program at once instead of failing every cycle.
    try:
        sensor_source = sensors.GroveSensors()
    except ImportError as exc:
        parser.exit(1, f"Grove libraries not found ({exc}). Run this on the Pi.\n")
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")

    store = CsvStore(args.csv)
    log.info("reading every %d s into %s", args.interval, store.path)
    try:
        run(store, sensor_source, args.interval, cycles=1 if args.once else None)
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
