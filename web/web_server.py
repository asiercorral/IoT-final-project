"""PlantPulse local web server: REST API and the page for pupils and teacher.

    GET /                         page: state, reason, readings, forecast, history chart
    GET /api/status               current state, reason, latest readings and forecast used
    GET /api/history?hours=24     stored readings of the last N hours (1 to 744)
    GET /api/history?hours=24&format=csv   the same as a CSV file

Run on the Pi from the repository root:

    python web/web_server.py

then open http://<pi-address>:5000/ from any laptop on the same network.
The page loads nothing from the Internet, so it keeps working offline.
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import sys
import time
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

# "python web/web_server.py" puts web/ on the path, not the repository root;
# add the root so the plantpulse and web packages can be imported.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plantpulse import config  # noqa: E402
from plantpulse.led_service import BAR_CELLS, PATTERNS  # noqa: E402
from plantpulse.profile import load_profile  # noqa: E402
from plantpulse.rule_engine import SENSOR_KEYS  # noqa: E402
from web import data  # noqa: E402

log = logging.getLogger(__name__)

HISTORY_FIELDS = ["timestamp", *SENSOR_KEYS, "soil_pct"]


def create_app(
    db_path=None,
    state_listener=None,
    forecast_cache=None,
    profile=None,
    clock=time.time,
):
    """The Flask app. Every data source can be replaced, which the tests use."""
    app = Flask(__name__)
    app.json.sort_keys = False
    listener = state_listener or data.StateListener()
    plant = profile or load_profile()

    def db():
        return db_path or config.DB_PATH

    @app.get("/api/status")
    def status():
        """Current state, status code, reason, latest readings and forecast used (T-27)."""
        now = clock()
        reading = data.latest_reading(db())
        body = {
            "device_id": config.DEVICE_ID,
            "plant": plant["name"],
            "generated_at": int(now),
            **data.describe_state(listener.message, now),
            "readings": None,
            "faulty_sensors": data.faulty_sensors(reading),
            "forecast": data.forecast_used(now, forecast_cache or config.FORECAST_CACHE, plant),
        }
        # The same bar the LCD shows, so the page matches the printed legend.
        body["screen_cells"] = PATTERNS.get(body["state"], 0)
        body["screen_cells_total"] = BAR_CELLS
        if reading is not None:
            body["readings"] = {**reading, "age_s": max(int(now - reading["timestamp"]), 0)}
        return jsonify(body)

    @app.get("/api/history")
    def history():
        """Stored readings for the requested period (T-28)."""
        try:
            hours = int(request.args.get("hours", "24"))
        except ValueError:
            hours = None
        if hours is None or not 1 <= hours <= data.MAX_HISTORY_HOURS:
            return jsonify(
                {"error": f"hours must be a whole number from 1 to {data.MAX_HISTORY_HOURS}"}
            ), 400
        now = int(clock())
        since = now - hours * 3600
        readings = data.readings_since(db(), since)

        if request.args.get("format") == "csv":
            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=HISTORY_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(readings)
            return Response(
                out.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename=plantpulse-{hours}h.csv"},
            )

        soil = plant["soil"]
        return jsonify({
            "hours": hours,
            "from": since,
            "to": now,
            "interval_s": config.READ_INTERVAL_S,
            "soil_thresholds": {
                "attention_below_pct": soil["critical_below_pct"],
                "check_below_pct": soil["dry_below_pct"],
                "wet_above_pct": soil["wet_above_pct"],
            },
            "readings": readings,
        })

    @app.get("/")
    def index():
        """The local page (T-29, T-30, T-35)."""
        return render_template("index.html")

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python web/web_server.py", description="PlantPulse local web page and API."
    )
    parser.add_argument("--host", default="0.0.0.0",
                        help="address to listen on (default: every interface)")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--db", type=Path, default=config.DB_PATH,
                        help="SQLite database (default: %(default)s)")
    parser.add_argument("--mqtt-host", default=config.MQTT_HOST)
    parser.add_argument("--mqtt-port", type=int, default=config.MQTT_PORT)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    listener = data.StateListener()
    listener.start(args.mqtt_host, args.mqtt_port)
    if not args.db.is_file():
        log.warning("database %s not found: the page will show no readings yet", args.db)
    create_app(db_path=args.db, state_listener=listener).run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
