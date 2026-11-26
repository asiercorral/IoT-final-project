"""T-21: the local SQLite database for the sensor history (decision 002).

One file, ``data/plantpulse.db``, with one table: a row per reading and a
column per sensor, the same keys as the telemetry payload. The MQTT
subscriber (T-22) fills it; the web API (T-28) and Grafana (T-31) read it.

Run on the Pi to create the database (safe to repeat, existing rows stay):

    python -m plantpulse.storage
"""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

from plantpulse import config

# A missing sensor value is NULL, never 0. (device_id, timestamp) is unique,
# so a reading that MQTT delivers twice is stored once.
SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    device_id         TEXT    NOT NULL,
    timestamp         INTEGER NOT NULL,  -- Unix seconds
    temperature_c     REAL,
    humidity_pct      REAL,
    soil_moisture_raw INTEGER,           -- mV from the ADC
    light_pct         REAL,
    PRIMARY KEY (device_id, timestamp)
)
"""


def connect(path=config.DB_PATH):
    """Open the database, creating its folder if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)


def init_db(path=config.DB_PATH):
    """Create the readings table if it does not exist yet."""
    with closing(connect(path)) as conn:
        conn.execute(SCHEMA)
        conn.commit()


def count_readings(path=config.DB_PATH):
    with closing(connect(path)) as conn:
        return conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create the PlantPulse SQLite database.")
    parser.add_argument("--db", type=Path, default=config.DB_PATH,
                        help="database file (default: %(default)s)")
    args = parser.parse_args(argv)

    init_db(args.db)
    print(f"Database ready: {args.db} ({count_readings(args.db)} readings)")


if __name__ == "__main__":
    main()
