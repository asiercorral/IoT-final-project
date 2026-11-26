# 002 – Database for the sensor history

Date: 2026-11-26 · Issue: #50 (T-21) · Owner: @Ibonerdoiza2004 · Status: accepted

## Question

Where does PlantPulse keep every reading so the teacher can see the history (US-03): SQLite or InfluxDB?

## What the database must do

- Store one reading every 5 minutes: 288 rows a day, about 105,000 a year.
- Work on the Pi without Internet (US-06).
- Be read by the Flask API (`GET /api/history`, T-28) and by Grafana (T-31).
- Be written by the MQTT subscriber (T-22), which may receive the same reading twice (QoS 1).

## Options

| | SQLite | InfluxDB 2 |
| --- | --- | --- |
| Install on the Pi | Built into Python; `sqlite3` package only to inspect the file | Extra repository and service; set up an organisation, a bucket and a token |
| Credentials | None: it is a file | A token kept in `.env` |
| Flask API (T-28) | One SQL query with Python's `sqlite3` | `influxdb-client` library and Flux queries |
| Grafana (T-31) | Needs the `frser-sqlite-datasource` plugin | Supported out of the box |
| Tests on a laptop | Yes, with a temporary file | Needs a running server |
| Data volume | Far more than enough | Far more than enough |

## Decision

**SQLite**, in one file: `data/plantpulse.db` (`config.DB_PATH`, inside the ignored `data/` folder).

One table, `readings`: a row per reading and a column per sensor, with the same names as the telemetry payload (`temperature_c`, `humidity_pct`, `soil_moisture_raw`, `light_pct`). A missing value is `NULL`, never 0. `(device_id, timestamp)` is the primary key, so a duplicated MQTT message is stored once. `python -m plantpulse.storage` creates the table.

## Why

- Nothing to install or run besides Python, and no secret to manage: fewer things that can fail during the demo.
- The web API and the tests use the standard library only.
- Our volume is tiny; InfluxDB's strengths (very many series, retention policies, downsampling) are not needed.

## Consequences

- Grafana (T-31) needs the SQLite plugin and read access to `data/plantpulse.db`.
- Only one program should write to the database: the MQTT subscriber (T-22). The web API and Grafana only read it.
- A backup is a copy of one file.
- If the project grows to many plants or years of data, InfluxDB can be reconsidered; the telemetry payload stays the same.
