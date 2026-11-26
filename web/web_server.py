import sys
import time
from pathlib import Path

from flask import Flask, jsonify, request

# "python web/web_server.py" puts web/ on the path, not the repository root;
# add the root so the plantpulse package can be imported.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plantpulse import config, forecast  # noqa: E402
from plantpulse.profile import load_profile  # noqa: E402

app = Flask(__name__)

# Dummy data, to be replaced by the local database (Ibon)
CURRENT = {
    "device_id": "plantpulse-school01-plant01",
    "status_code": "CHECK_MOISTURE",
    "reason": "Soil is dry",
    "sensors": {"temperature_c": 19.5, "humidity_pct": 78.0,
                "soil_moisture_raw": 420, "light_pct": 63.5},
}

SOURCE_NAMES = {"euskalmet": "Euskalmet", "open-meteo": "Open-Meteo"}


def explain_forecast(summary, profile):
    """Whether the forecast can change the advice, and why, in one sentence (T-35).

    Follows the README rules: an outdated (older than 6 h) or unavailable
    forecast is never used, and rain only matters for a plant exposed to it.
    Returns ``(used, why)``.
    """
    window_h = summary["window_h"]
    if summary["status"] == "unavailable":
        return False, (
            f"No forecast for the next {window_h} h is available (no Internet, or it "
            "has not been downloaded yet). The advice uses only the sensors."
        )
    if summary["status"] == "outdated":
        max_age_h = config.FORECAST_MAX_AGE_S // 3600
        return False, (
            f"The forecast is {summary['age_h']:.0f} h old, more than {max_age_h} h, "
            "so it is not used. The advice uses only the sensors."
        )
    rain = summary["rain_mm"]
    if not profile["rain_exposed"]:
        return False, (
            f"{rain} mm of rain expected in the next {window_h} h, but the plant is "
            "sheltered, so rain cannot water it. The advice uses only the sensors."
        )
    if rain >= profile["rain"]["min_mm"]:
        return True, (
            f"{rain} mm of rain expected in the next {window_h} h. The plant is outdoors, "
            "so watering can wait for the rain, unless the soil is very dry."
        )
    return True, (
        f"Little or no rain expected ({rain} mm in the next {window_h} h), "
        "so the watering advice is not delayed."
    )


def forecast_used(now=None, cache_path=None, profile=None):
    """The forecast summary shown on the page, with ``used`` and ``why`` added.

    Reads only the local cache that forecast.py keeps, so the page never waits
    for the Internet. Format: ``forecast.forecast_summary`` plus ``used``,
    ``why`` and a readable ``source_name``.
    """
    now = time.time() if now is None else now
    profile = profile or load_profile()
    cached = forecast.load_cache(cache_path or config.FORECAST_CACHE)
    summary = forecast.forecast_summary(cached, now, profile["rain"]["window_h"])
    summary["source_name"] = SOURCE_NAMES.get(summary["source"], summary["source"])
    summary["used"], summary["why"] = explain_forecast(summary, profile)
    return summary


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

EXPLANATIONS["FAULT"] = "A sensor gives no valid reading. Check its connection and wiring."

SENSOR_LABELS = {
    "temperature_c": "Temperature sensor",
    "humidity_pct": "Air humidity sensor",
    "soil_moisture_raw": "Soil moisture sensor",
    "light_pct": "Light sensor",
}


def find_faulty_sensors(sensors):
    """Return the sensors with no valid reading (null/None, as in the README)."""
    return [
        {"sensor": key, "label": label, "reason": "No valid reading"}
        for key, label in SENSOR_LABELS.items()
        if sensors.get(key) is None
    ]

PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>PlantPulse</title>
<style>
  body { font-family: sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }
  .card { background: #eef6ee; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
  .forecast { background: #eef2f8; }
  svg { width: 100%; height: auto; background: #fafafa; border: 1px solid #ddd; }
  .fault { background: #fdecea; }
</style>
</head>
<body>
  <h1>PlantPulse</h1>
  <div class="card">
    <div class="card" id="faults"></div>
    <h2 id="status">Loading...</h2>
    <p id="reason"></p>
    <p id="explanation"></p>
  </div>
  <div class="card forecast">
    <h3 id="forecast-title">Weather forecast</h3>
    <p id="forecast-source"></p>
    <p id="forecast-why"></p>
  </div>
  <h2>Soil moisture history</h2>
  <svg id="chart" viewBox="0 0 600 240"></svg>
  <script>
    async function load() {
      const s = await (await fetch('/api/status' + location.search)).json();
      document.getElementById('status').textContent = s.status_code;
      document.getElementById('reason').textContent = s.reason;
      document.getElementById('explanation').textContent = s.explanation;

      const fl = document.getElementById('faults');
      if (s.faulty_sensors.length) {
        fl.className = 'card fault';
        fl.textContent = 'Faulty sensor: ' +
          s.faulty_sensors.map(x => x.label + ' (' + x.reason + ')').join(', ');
      } else {
        fl.textContent = 'All sensors are working.';
      }

      showForecast(s.forecast);

      const h = await (await fetch('/api/history?hours=24')).json();
      drawChart(h.readings);
    }

    // Forecast card: which forecast, how old, how much rain, and why it is used or not
    function showForecast(f) {
      document.getElementById('forecast-title').textContent =
        f.used ? 'Forecast used' : 'Forecast not used';
      let line = 'No forecast downloaded yet.';
      if (f.source) {
        const age = f.age_h < 1 ? Math.round(f.age_h * 60) + ' min' : f.age_h + ' h';
        line = f.source_name + ', downloaded ' + age + ' ago';
        if (f.rain_mm !== null) {
          line += '. Rain in the next ' + f.window_h + ' h: ' + f.rain_mm + ' mm';
        }
      }
      document.getElementById('forecast-source').textContent = line;
      document.getElementById('forecast-why').textContent = f.why;
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
    """Current state, readings, explanation, forecast used and faulty sensors."""
    data = dict(CURRENT)
    sensors = dict(CURRENT["sensors"])

    # Test only: /api/status?simulate_fault=soil_moisture_raw
    simulated = request.args.get("simulate_fault")
    if simulated in sensors:
        sensors[simulated] = None

    faulty = find_faulty_sensors(sensors)
    data["sensors"] = sensors
    data["faulty_sensors"] = faulty
    if faulty:
        data["status_code"] = "FAULT"
        data["reason"] = "Faulty sensor: " + ", ".join(f["label"] for f in faulty)
    data["explanation"] = EXPLANATIONS.get(data["status_code"], "")
    data["forecast"] = forecast_used()
    return jsonify(data)


@app.get("/api/history")
def history():
    """Timestamped readings for the requested period."""
    hours = request.args.get("hours", 24, type=int)
    return jsonify({"hours": hours, "readings": HISTORY})


@app.get("/")
def index():
    """Local page: status, explanation, forecast used and history chart."""
    return PAGE


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
