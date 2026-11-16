from flask import Flask, jsonify, request

app = Flask(__name__)

# Dummy data, to be replaced by the local database (Ibon) later
CURRENT = {
    "device_id": "plantpulse-school01-plant01",
    "status_code": "CHECK_MOISTURE",
    "reason": "Soil is dry",
    "sensors": {"temperature_c": 19.5, "humidity_pct": 78.0,
                "soil_moisture_raw": 420, "light_pct": 63.5},
}

HISTORY = [
    {"timestamp": 1728920000, "soil_moisture_raw": 520},
    {"timestamp": 1728923600, "soil_moisture_raw": 470},
    {"timestamp": 1728927200, "soil_moisture_raw": 420},
]


@app.get("/api/status")
def status():
    """Current plant state and latest readings."""
    return jsonify(CURRENT)


@app.get("/api/history")
def history():
    """Timestamped readings for the requested period."""
    hours = request.args.get("hours", 24, type=int)
    return jsonify({"hours": hours, "readings": HISTORY})


@app.get("/")
def index():
    """Local page showing the plant state."""
    return (f"<h1>PlantPulse</h1><p>Status: {CURRENT['status_code']}</p>"
            f"<p>{CURRENT['reason']}</p>")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
