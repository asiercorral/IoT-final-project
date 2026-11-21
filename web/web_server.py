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

# One short explanation per status code (US-02)
EXPLANATIONS = {
    "OK": "All sensor readings are in the normal range. Keep observing.",
    "CHECK_MOISTURE": "The soil moisture is low. Check the soil and water the plant if it feels dry.",
}

PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>PlantPulse</title>
<style>
  body { font-family: sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }
  .card { background: #eef6ee; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
  svg { width: 100%; height: auto; background: #fafafa; border: 1px solid #ddd; }
</style>
</head>
<body>
  <h1>PlantPulse</h1>
  <div class="card">
    <h2 id="status">Loading...</h2>
    <p id="reason"></p>
    <p id="explanation"></p>
  </div>
  <h2>Soil moisture history</h2>
  <svg id="chart" viewBox="0 0 600 240"></svg>
  <script>
    async function load() {
      const s = await (await fetch('/api/status')).json();
      document.getElementById('status').textContent = s.status_code;
      document.getElementById('reason').textContent = s.reason;
      document.getElementById('explanation').textContent = s.explanation;

      const h = await (await fetch('/api/history?hours=24')).json();
      drawChart(h.readings);
    }

    // Plain SVG line chart: no external library, so it works offline
    function drawChart(readings) {
      const svg = document.getElementById('chart');
      if (readings.length < 2) { svg.textContent = 'Not enough data'; return; }
      const values = readings.map(r => r.soil_moisture_raw);
      const min = Math.min(...values), max = Math.max(...values);
      const range = (max - min) || 1;
      const points = readings.map((r, i) => {
        const x = 40 + i * (520 / (readings.length - 1));
        const y = 200 - ((r.soil_moisture_raw - min) / range) * 160;
        return x + ',' + y;
      }).join(' ');
      svg.innerHTML =
        '<polyline fill="none" stroke="#2e7d32" stroke-width="3" points="' + points + '"/>' +
        '<text x="5" y="45" font-size="12">' + max + '</text>' +
        '<text x="5" y="205" font-size="12">' + min + '</text>';
    }

    load();
  </script>
</body>
</html>"""


@app.get("/api/status")
def status():
    """Current plant state, latest readings and short explanation."""
    data = dict(CURRENT)
    data["explanation"] = EXPLANATIONS.get(CURRENT["status_code"], "")
    return jsonify(data)


@app.get("/api/history")
def history():
    """Timestamped readings for the requested period."""
    hours = request.args.get("hours", 24, type=int)
    return jsonify({"hours": hours, "readings": HISTORY})


@app.get("/")
def index():
    """Local page: status, explanation and history chart."""
    return PAGE


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
