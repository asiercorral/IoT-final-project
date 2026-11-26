// PlantPulse page: fills the state, readings, forecast and history chart from
// the local API. Plain JavaScript and SVG, no libraries, so it works offline.
"use strict";

const STATUS_REFRESH_MS = 60 * 1000;
const HISTORY_REFRESH_MS = 5 * 60 * 1000;

// Same headings as the LCD and the printed legend card
const STATES = {
  NORMAL: { label: "All good", icon: "✓" },
  CHECK: { label: "Check the plant", icon: "!" },
  ATTENTION: { label: "Plant needs help", icon: "!!" },
  FAULT: { label: "Sensor problem", icon: "×" },
  null: { label: "State unknown", icon: "?" },
};

const SENSORS = [
  { key: "soil_pct", title: "Soil moisture", unit: "%", domain: [0, 100], sensor: "soil_moisture_raw" },
  { key: "light_pct", title: "Light", unit: "%", domain: [0, 100], sensor: "light_pct" },
  { key: "temperature_c", title: "Air temperature", unit: "°C", domain: null, sensor: "temperature_c" },
  { key: "humidity_pct", title: "Air humidity", unit: "%", domain: [0, 100], sensor: "humidity_pct" },
];

const number = new Intl.NumberFormat("en", { maximumFractionDigits: 1 });
const timeFmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric" });
const fullFmt = new Intl.DateTimeFormat("en-GB", {
  weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
});

const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, text) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

function svg(tag, attrs = {}, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

function ago(seconds) {
  if (seconds === null || seconds === undefined) return "";
  if (seconds < 90) return "just now";
  if (seconds < 90 * 60) return Math.round(seconds / 60) + " min ago";
  if (seconds < 36 * 3600) return number.format(seconds / 3600) + " h ago";
  return Math.round(seconds / 86400) + " days ago";
}

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(url + ": HTTP " + response.status);
  return response.json();
}

// --- state, readings and forecast ------------------------------------------------

function showState(s) {
  const info = STATES[s.state] || STATES.null;
  $("plant-name").textContent = s.plant;
  $("state-card").dataset.state = s.state || "none";
  $("state-icon").textContent = info.icon;
  $("state-label").textContent = info.label;
  $("reason").textContent = s.reason;
  $("explanation").textContent = s.explanation;

  const cells = $("cells");
  cells.replaceChildren();
  for (let i = 0; i < s.screen_cells_total; i++) {
    cells.append(el("span", i < s.screen_cells ? { class: "on" } : {}));
  }
  cells.hidden = s.screen_cells === 0;  // the LCD shows text, not a bar, in these cases

  // The other rules that apply; the most severe one is the reason above
  const others = s.findings.filter((f) => f.reason !== s.reason);
  const list = $("findings");
  list.replaceChildren();
  for (const f of others) {
    const item = el("li");
    item.append(el("b", {}, "Also: "), f.reason);
    list.append(item);
  }
  list.hidden = others.length === 0;
}

function showReadings(s) {
  const r = s.readings;
  const faulty = new Set(s.faulty_sensors.map((f) => f.sensor));
  const tiles = $("tiles");
  tiles.replaceChildren();

  for (const sensor of SENSORS) {
    const tile = el("div", { class: "tile" });
    tile.append(el("p", { class: "label" }, sensor.title));
    const value = r ? r[sensor.key] : null;
    if (r && faulty.has(sensor.sensor)) {
      tile.classList.add("fault");
      tile.append(el("p", { class: "value" }, "No valid reading"));
      tile.append(el("p", { class: "sub" }, "Check the sensor and its cable"));
    } else {
      const v = el("p", { class: "value" }, value === null ? "–" : number.format(value));
      if (value !== null) v.append(el("span", { class: "unit" }, sensor.unit));
      tile.append(v);
      if (sensor.key === "soil_pct" && r && r.soil_moisture_raw !== null) {
        tile.append(el("p", { class: "sub" }, "Probe: " + r.soil_moisture_raw + " mV"));
      }
    }
    tiles.append(tile);
  }

  $("readings-age").textContent = r
    ? "Measured " + ago(r.age_s) + " (" + timeFmt.format(r.timestamp * 1000) + ")"
    : "No readings stored yet";
}

function showForecast(f) {
  $("forecast-title").textContent = f.used ? "Forecast used" : "Forecast not used";
  let line = "No forecast downloaded yet.";
  if (f.source) {
    line = f.source_name + ", downloaded " + ago(f.age_h * 3600);
    if (f.rain_mm !== null) line += " · rain next " + f.window_h + " h: " + f.rain_mm + " mm";
  }
  $("forecast-source").textContent = line;
  $("forecast-why").textContent = f.why;
}

async function loadStatus() {
  try {
    const s = await getJSON("/api/status");
    showState(s);
    showReadings(s);
    showForecast(s.forecast);
    $("updated").textContent = "Updated " + timeFmt.format(s.generated_at * 1000);
  } catch (err) {
    $("updated").textContent = "Cannot reach the Pi: " + err.message;
  }
}

// --- history chart (small multiples, one per sensor, shared time axis) -----------

const chart = { hours: 24, data: null, layout: null };

function niceDomain(values) {
  if (!values.length) return [0, 30];
  const lo = Math.floor((Math.min(...values) - 1) / 5) * 5;
  const hi = Math.ceil((Math.max(...values) + 1) / 5) * 5;
  return [lo, hi];
}

function timeTicks(from, to, hours) {
  const ticks = [];
  const d = new Date(from * 1000);
  d.setMinutes(0, 0, 0);
  if (hours <= 48) {
    const step = hours <= 24 ? 3 : 6;
    d.setHours(d.getHours() + 1);
    while (d.getHours() % step) d.setHours(d.getHours() + 1);
    for (; d.getTime() / 1000 <= to; d.setHours(d.getHours() + step)) {
      ticks.push({ t: d.getTime() / 1000, label: timeFmt.format(d) });
    }
  } else {
    d.setHours(24, 0, 0, 0);
    for (; d.getTime() / 1000 <= to; d.setDate(d.getDate() + 1)) {
      ticks.push({ t: d.getTime() / 1000, label: dayFmt.format(d) });
    }
  }
  return ticks;
}

function linePath(readings, key, x, y, maxGap) {
  let d = "";
  let prev = null;
  for (const r of readings) {
    const v = r[key];
    if (v === null) { prev = null; continue; }
    const px = x(r.timestamp).toFixed(1);
    const py = y(v).toFixed(1);
    // A missing value or a long gap breaks the line; a lone point stays visible
    d += prev === null || r.timestamp - prev > maxGap ? `M${px} ${py}l0.01 0` : `L${px} ${py}`;
    prev = r.timestamp;
  }
  return d;
}

function drawChart() {
  const h = chart.data;
  const root = $("chart");
  root.replaceChildren();
  $("tooltip").hidden = true;
  if (!h) return;

  const withData = h.readings.length > 0;
  $("chart-note").textContent = withData
    ? h.readings.length + " readings, every " + Math.round(h.interval_s / 60) +
      " min. Gaps mean the Pi or a sensor was not measuring."
    : "";
  if (!withData) {
    root.append(el("p", { class: "empty" }, "No readings stored for this period yet."));
    return;
  }

  const width = Math.max(root.clientWidth, 300);
  const m = { left: 40, right: 14 };
  const titleH = 24, plotH = width < 500 ? 70 : 92, gapH = 18, axisH = 22;
  const panelH = titleH + plotH + gapH;
  const height = SENSORS.length * panelH + axisH - gapH;
  const plotW = width - m.left - m.right;
  const x = (t) => m.left + ((t - h.from) / (h.to - h.from)) * plotW;
  const maxGap = 3 * h.interval_s;

  const root_svg = svg("svg", { width, height, viewBox: `0 0 ${width} ${height}` });
  const ticks = timeTicks(h.from, h.to, h.hours);
  const panels = [];

  SENSORS.forEach((sensor, i) => {
    const top = i * panelH + titleH;
    const values = h.readings.map((r) => r[sensor.key]).filter((v) => v !== null);
    const domain = sensor.domain || niceDomain(values);
    const y = (v) => top + plotH - ((v - domain[0]) / (domain[1] - domain[0])) * plotH;
    panels.push({ sensor, y });

    const g = svg("g");
    const latest = [...h.readings].reverse().find((r) => r[sensor.key] !== null);
    g.append(svg("text", { x: m.left, y: top - 9, class: "panel-title" }, sensor.title));
    if (latest) {
      const newest = h.readings[h.readings.length - 1];
      const when = latest === newest ? "now " : "last at " + timeFmt.format(latest.timestamp * 1000) + ": ";
      g.append(svg("text", { x: width - m.right, y: top - 9, class: "panel-value", "text-anchor": "end" },
        when + number.format(latest[sensor.key]) + " " + sensor.unit));
    }

    // Soil: the plant profile's thresholds, so pupils see when the state changes
    if (sensor.key === "soil_pct" && h.soil_thresholds) {
      const att = h.soil_thresholds.attention_below_pct;
      const chk = h.soil_thresholds.check_below_pct;
      g.append(svg("rect", { x: m.left, y: y(chk), width: plotW, height: y(att) - y(chk), class: "band-check" }));
      g.append(svg("rect", { x: m.left, y: y(att), width: plotW, height: y(0) - y(att), class: "band-attention" }));
      g.append(svg("text", { x: width - m.right - 4, y: y(chk) + 12, class: "band-label", "text-anchor": "end" },
        "Check below " + chk + " %"));
      g.append(svg("text", { x: width - m.right - 4, y: y(att) + 12, class: "band-label", "text-anchor": "end" },
        "Attention below " + att + " %"));
    }

    const mid = (domain[0] + domain[1]) / 2;
    for (const v of [domain[0], mid, domain[1]]) {
      g.append(svg("line", { x1: m.left, x2: width - m.right, y1: y(v), y2: y(v),
        class: v === domain[0] ? "baseline" : "grid" }));
      g.append(svg("text", { x: m.left - 6, y: y(v) + 4, "text-anchor": "end" }, number.format(v)));
    }
    for (const tick of ticks) {
      g.append(svg("line", { x1: x(tick.t), x2: x(tick.t), y1: top, y2: top + plotH, class: "grid" }));
    }
    g.append(svg("path", { d: linePath(h.readings, sensor.key, x, y, maxGap), class: "line" }));
    root_svg.append(g);
  });

  const axisY = height - 6;
  for (const tick of ticks) {
    root_svg.append(svg("text", { x: x(tick.t), y: axisY, "text-anchor": "middle" }, tick.label));
  }

  // Hover layer: crosshair snaps to the nearest reading, one tooltip for all sensors
  const hover = svg("g", { visibility: "hidden" });
  const cross = svg("line", { y1: titleH, y2: height - axisH, class: "crosshair" });
  hover.append(cross);
  const dots = panels.map(() => { const c = svg("circle", { r: 4, class: "dot" }); hover.append(c); return c; });
  root_svg.append(hover);
  const hit = svg("rect", { x: m.left, y: 0, width: plotW, height: height - axisH, fill: "transparent" });
  root_svg.append(hit);

  chart.layout = { x, panels, hover, cross, dots, m, plotW, width, maxGap };
  hit.addEventListener("pointermove", (e) => {
    const box = root_svg.getBoundingClientRect();
    const t = h.from + ((e.clientX - box.left - m.left) / plotW) * (h.to - h.from);
    showPoint(nearestIndex(t));
  });
  hit.addEventListener("pointerleave", hidePoint);
  root.append(root_svg);
}

function nearestIndex(t) {
  const rs = chart.data.readings;
  let lo = 0, hi = rs.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (rs[mid].timestamp < t) lo = mid + 1; else hi = mid;
  }
  if (lo > 0 && t - rs[lo - 1].timestamp < rs[lo].timestamp - t) lo -= 1;
  return Math.abs(rs[lo].timestamp - t) <= chart.layout.maxGap ? lo : -1;
}

function hidePoint() {
  if (chart.layout) chart.layout.hover.setAttribute("visibility", "hidden");
  $("tooltip").hidden = true;
  chart.focus = -1;
}

function showPoint(index) {
  if (index < 0) { hidePoint(); return; }
  chart.focus = index;
  const r = chart.data.readings[index];
  const L = chart.layout;
  const px = L.x(r.timestamp);
  L.cross.setAttribute("x1", px);
  L.cross.setAttribute("x2", px);
  L.panels.forEach(({ sensor, y }, i) => {
    const v = r[sensor.key];
    L.dots[i].setAttribute("visibility", v === null ? "hidden" : "inherit");
    if (v !== null) { L.dots[i].setAttribute("cx", px); L.dots[i].setAttribute("cy", y(v)); }
  });
  L.hover.setAttribute("visibility", "visible");

  const tip = $("tooltip");
  tip.replaceChildren(el("p", { class: "when" }, fullFmt.format(r.timestamp * 1000)));
  for (const sensor of SENSORS) {
    const v = r[sensor.key];
    const row = el("div", { class: "row" });
    row.append(el("span", {}, sensor.title), el("b", {}, v === null ? "no reading" : number.format(v) + " " + sensor.unit));
    tip.append(row);
  }
  tip.hidden = false;
  const left = px + 16 + tip.offsetWidth > L.width ? px - 16 - tip.offsetWidth : px + 16;
  tip.style.left = Math.max(4, left) + "px";
}

async function loadHistory() {
  try {
    chart.data = await getJSON("/api/history?hours=" + chart.hours);
  } catch (err) {
    chart.data = null;
    $("chart").replaceChildren(el("p", { class: "empty" }, "Cannot load the history: " + err.message));
    return;
  }
  drawChart();
}

function setPeriod(hours) {
  chart.hours = hours;
  for (const b of document.querySelectorAll(".segmented button")) {
    b.setAttribute("aria-pressed", String(Number(b.dataset.hours) === hours));
  }
  $("download").href = "/api/history?hours=" + hours + "&format=csv";
  loadHistory();
}

// Keyboard: focus the chart and use the arrow keys to step through readings
function onChartKey(e) {
  if (!chart.data || !chart.data.readings.length) return;
  const last = chart.data.readings.length - 1;
  let i = chart.focus >= 0 ? chart.focus : last;
  if (e.key === "ArrowLeft") i = Math.max(0, i - 1);
  else if (e.key === "ArrowRight") i = Math.min(last, i + 1);
  else if (e.key === "Escape") { hidePoint(); return; }
  else return;
  e.preventDefault();
  showPoint(i);
}

document.querySelectorAll(".segmented button").forEach((b) =>
  b.addEventListener("click", () => setPeriod(Number(b.dataset.hours))));
$("chart").tabIndex = 0;
$("chart").addEventListener("keydown", onChartKey);
$("chart").addEventListener("blur", hidePoint);

let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(drawChart, 150);
});

loadStatus();
loadHistory();
setInterval(loadStatus, STATUS_REFRESH_MS);
setInterval(loadHistory, HISTORY_REFRESH_MS);
