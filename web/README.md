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
| `GET /api/status` | Current state, reason, explanation and latest readings (JSON) |
| `GET /api/history?hours=24` | Timestamped readings for the requested period (JSON) |

## Notes

- The chart is plain SVG with no external library, so the page works without Internet.
- Data is currently dummy data. It will be replaced by the local database.
- `explanation` is an extra field added to `/api/status`.
