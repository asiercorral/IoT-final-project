# PlantPulse web interface

Local Flask server with a REST API and one page for pupils and the teacher:
the plant state and why (US-02), the latest readings, the forecast used and
why (US-04), and the history of the four readings (US-03).

## Run it

On the Pi, from the repository root:

    pip install -r requirements.txt
    python web/web_server.py

Then open `http://<pi-address>:5000/` from any laptop on the same network
(`hostname -I` on the Pi gives the address). On the Pi itself:
http://127.0.0.1:5000/.

The page loads nothing from the Internet (no CDN, no web fonts, charts drawn
in plain SVG), so it keeps working offline (US-06).

## Where the data comes from

| Part of the page | Source | Written by |
| --- | --- | --- |
| State, status code, reason, findings | Retained MQTT message on `plantpulse/school01/plant01/state` | `rule_engine.py --publish` |
| Latest readings and history | SQLite `data/plantpulse.db`, opened read-only (decision 002) | MQTT subscriber (T-22) |
| Forecast used and why | `data/forecast_cache.json` | `python -m plantpulse.forecast` |

Any of them can be missing: the page then says what is missing. A state older
than three reading cycles (15 min) is not shown, because the rule engine has
stopped.

Until the subscriber (T-22) fills the database, put readings in it with:

    python scripts/fill_demo_db.py --from-csv data/readings.csv   # real readings from acquisition.py
    python scripts/fill_demo_db.py --demo                         # 7 days of made-up readings (laptop only)

## Routes

| Route | Purpose |
| --- | --- |
| `GET /` | The page |
| `GET /api/status` | State, status code, reason, explanation, findings, latest readings, faulty sensors and the forecast used (JSON) |
| `GET /api/history?hours=24` | Stored readings of the last 1 to 744 hours, oldest first, with the soil thresholds of the plant profile (JSON) |
| `GET /api/history?hours=24&format=csv` | The same readings as a CSV file |

`/api/status` example (abridged):

```json
{
  "plant": "Sweet basil (demo plant)",
  "state": "CHECK",
  "status_code": "CHECK_DRY",
  "reason": "Soil is getting dry (38 %). Feel the soil and water if it is dry below the surface.",
  "explanation": "Roots take up water from the soil. ...",
  "age_s": 120,
  "findings": [{"sensor": "soil", "level": "CHECK", "code": "CHECK_DRY", "reason": "..."}],
  "readings": {"timestamp": 1764000000, "age_s": 180, "temperature_c": 16.6,
               "humidity_pct": 67.8, "soil_moisture_raw": 1432, "soil_pct": 70.2, "light_pct": 44.4},
  "faulty_sensors": [],
  "screen_cells": 5,
  "forecast": {"status": "fresh", "source_name": "Open-Meteo", "age_h": 0.4, "rain_mm": 0.5,
               "window_h": 6, "used": false, "why": "0.5 mm of rain expected ..."}
}
```

- `state` is null when there is no recent state; `reason` then says why.
- `readings` is null when the database has no readings; a missing sensor value is null, never 0, and the sensor is listed in `faulty_sensors`.
- `soil_pct` is the calibrated soil index (T-12) computed from `soil_moisture_raw`.
- `forecast` is `forecast.forecast_summary` plus `used` and `why`: a forecast older than 6 h or unavailable is never used, and rain only changes the advice for a plant exposed to rain (`rain_exposed` in the plant profile).

## The page

- **Plant state** with the same heading and 10-cell bar as the LCD and the printed legend, the reason from the rule engine, one sentence on why it matters, and any other rule that applies.
- **Weather**: whether the forecast is used, its source and age, the rain expected and why.
- **Latest readings**: four tiles; a sensor without a valid reading says so (T-40).
- **History**: one small chart per reading on a shared time axis, 24 h or 7 days. The soil chart shades the Check and Attention zones of the plant profile. Hover (or focus the chart and use the arrow keys) to read every value at one time. Gaps mean nothing was measured. "Download CSV" gives the same data as a table.

The page refreshes the state every minute and the history every 5 minutes.

## Tests

    python -m pytest tests/test_web.py
