# PlantPulse web interface

Local Flask web server that shows the plant status, a short explanation of
each recommendation (US-02) and the sensor history (US-03).

## Run it

    pip install flask
    python web/web_server.py

Then open http://127.0.0.1:5000/

## Routes

| Route | Purpose |
|---|---|
| `GET /` | Local page: status, explanation and soil moisture chart |
| `GET /api/status` | Current state, reason, explanation, latest readings and the forecast used (JSON) |
| `GET /api/history?hours=24` | Timestamped readings for the requested period (JSON) |

## Notes

- The chart is plain SVG with no external library, so the page works without Internet.
- Data is currently dummy data. It will be replaced by the local database.
- `explanation` is an extra field added to `/api/status`.
- `forecast` in `/api/status` is `forecast.forecast_summary` (status `fresh`, `outdated` or
  `unavailable`, source, age, rain in mm) plus `used` and `why`. It is read from the local
  cache that `plantpulse/forecast.py` writes, so the page never waits for the Internet.
  Run `python -m plantpulse.forecast` once to fill the cache.
- `why` follows the README rules: a forecast older than 6 h or unavailable is never used,
  and rain only changes the advice for a plant exposed to rain (`rain_exposed` in the
  plant profile).
