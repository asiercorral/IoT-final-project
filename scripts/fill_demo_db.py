"""Put readings into the SQLite database so the web page has a history to show.

Until the MQTT subscriber (T-22) fills the database, use one of:

    python scripts/fill_demo_db.py --from-csv data/readings.csv   # real readings from acquisition.py
    python scripts/fill_demo_db.py --demo                         # 7 days of made-up readings

Both write to data/plantpulse.db (``--db`` to change it). Rows already stored
are kept: a reading with the same timestamp is not added twice. Demo readings
are for trying the page on a laptop; do not mix them with real data on the Pi.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import sys
import time
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plantpulse import config, storage  # noqa: E402

INSERT = (
    "INSERT OR IGNORE INTO readings (device_id, timestamp, temperature_c, humidity_pct,"
    " soil_moisture_raw, light_pct) VALUES (?, ?, ?, ?, ?, ?)"
)


def _cell(value, cast):
    return None if value in ("", None) else cast(value)


def rows_from_csv(path):
    """Rows from the acquisition CSV (empty cells become NULL)."""
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            yield (
                config.DEVICE_ID,
                int(float(row["timestamp"])),
                _cell(row.get("temperature_c"), float),
                _cell(row.get("humidity_pct"), float),
                _cell(row.get("soil_moisture_raw"), lambda v: int(float(v))),
                _cell(row.get("light_pct"), float),
            )


def demo_rows(days=7, interval_s=config.READ_INTERVAL_S, now=None, seed=7):
    """Plausible readings: daily light and temperature cycles, soil drying out
    between two waterings, and a short sensor outage to show a gap."""
    rng = random.Random(seed)
    now = int(time.time() if now is None else now)
    start = now - days * 86400
    start -= start % interval_s
    dry, wet = config.SOIL_DRY_MV, config.SOIL_WET_MV
    waterings = [start + int(days * 86400 * f) for f in (0.0, 0.45, 0.9)]
    outage = (start + int(days * 86400 * 0.7), start + int(days * 86400 * 0.7) + 3 * 3600)

    for ts in range(start, now + 1, interval_s):
        local = time.localtime(ts)
        hour = local.tm_hour + local.tm_min / 60
        daylight = max(0.0, math.sin((hour - 7) / 12 * math.pi))
        last_water = max(w for w in waterings if w <= ts)
        days_dry = (ts - last_water) / 86400
        soil_pct = max(8.0, 85 - 22 * days_dry) + rng.uniform(-1.5, 1.5)
        soil_mv = int(dry + (wet - dry) * soil_pct / 100)
        temp = 13 + 6 * daylight + rng.uniform(-0.4, 0.4)
        humidity = 82 - 22 * daylight + rng.uniform(-2, 2)
        light = 3 + 70 * daylight * (0.75 + 0.25 * math.sin(ts / 5000)) + rng.uniform(0, 2)
        if outage[0] <= ts < outage[1]:
            continue  # the Pi was off: no rows at all
        row = [round(temp, 1), round(humidity, 1), soil_mv, round(min(light, 100), 1)]
        if outage[1] <= ts < outage[1] + 3600:
            row[0] = row[1] = None  # the DHT sensor came back later
        yield (config.DEVICE_ID, ts, *row)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-csv", type=Path, help="acquisition CSV to import")
    source.add_argument("--demo", action="store_true", help="add 7 days of made-up readings")
    parser.add_argument("--db", type=Path, default=config.DB_PATH,
                        help="database file (default: %(default)s)")
    args = parser.parse_args(argv)

    storage.init_db(args.db)
    rows = rows_from_csv(args.from_csv) if args.from_csv else demo_rows()
    with closing(storage.connect(args.db)) as conn:
        before = conn.total_changes
        conn.executemany(INSERT, rows)
        conn.commit()
        added = conn.total_changes - before
    print(f"{added} readings added; {storage.count_readings(args.db)} in {args.db}")


if __name__ == "__main__":
    main()
