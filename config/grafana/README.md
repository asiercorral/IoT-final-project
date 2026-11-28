# Grafana dashboard (T-31)

One dashboard, **PlantPulse – plant readings**, for the teacher: the current
value of the four readings and their history (US-03). Grafana reads the SQLite
database `data/plantpulse.db` (decision 002) through the
[`frser-sqlite-datasource`](https://grafana.com/grafana/plugins/frser-sqlite-datasource/)
plugin, read-only. Like the web page, it works without Internet once installed.

## Install on the Pi

From the repository root, as the user that owns it:

    bash scripts/setup_grafana.sh

The script installs Grafana from the official APT repository and the SQLite
plugin, copies the two provisioning files with this repository's path, lets
the `grafana` user read the database and the dashboard, and starts
`grafana-server`. It can be run again safely.

Open `http://<pi-address>:3000/` from a laptop on the same network (`hostname -I`
gives the address). The first login is `admin` / `admin`; Grafana then asks
for a new password. The dashboard is under **Dashboards › PlantPulse**.

Until the MQTT subscriber (T-22) fills the database, load readings with
`python scripts/fill_demo_db.py --from-csv data/readings.csv`.

## What it shows

| Panel | Type | Query |
| --- | --- | --- |
| Soil moisture now, Light now, Air temperature now, Air humidity now | Stat | Newest row; a missing value shows "No valid reading", never an older value |
| Last reading | Stat | Time since the newest row; red after 15 min (three missed cycles) |
| Soil moisture, Light, Air temperature, Air humidity | Time series | Rows in the chosen time range |

- Use the time picker (top right) for 24 h, 7 days or any other period.
- The soil values are the calibrated index (0 % dry, 100 % waterlogged),
  computed in SQL from `soil_moisture_raw` with the T-12 references; the soil
  panels are coloured by the basil profile's thresholds: Attention below 20 %,
  Check below 45 %.
- A line breaks when no reading arrived for 15 minutes, so a gap means the Pi
  or a sensor was not measuring; it is never drawn as a straight line.

## Files

| File | Installed as |
| --- | --- |
| `provisioning/datasources/plantpulse.yaml` | `/etc/grafana/provisioning/datasources/plantpulse.yaml` |
| `provisioning/dashboards/plantpulse.yaml` | `/etc/grafana/provisioning/dashboards/plantpulse.yaml` |
| `dashboards/plantpulse.json` | read from the repository, so `git pull` updates the dashboard within a minute |

The dashboard is provisioned, so changes made in the Grafana editor cannot be
saved over it. To change it: edit it in Grafana, **Export › Export as JSON**,
replace `dashboards/plantpulse.json` with that file and commit it.

## If the calibration or the plant changes

The dashboard does not read `.env` or the plant profile. When they change,
update `dashboards/plantpulse.json` to match:

- `dry_mv` and `wet_mv` (dashboard variables, hidden) = `PLANTPULSE_SOIL_DRY_MV`
  and `PLANTPULSE_SOIL_WET_MV` (now 118 and 1989 mV);
- the soil thresholds 20 and 45 = `critical_below_pct` and `dry_below_pct` of
  the plant profile.

## Troubleshooting

- **"No data" everywhere**: the database is empty, or Grafana cannot read it.
  Check with `sudo -u grafana sqlite3 data/plantpulse.db "SELECT COUNT(*) FROM readings"`
  (needs `sudo apt install sqlite3`); if it fails, run the setup script again.
- **"Data source not found" or plugin errors**: `sudo grafana-cli plugins ls` (or `sudo grafana cli plugins ls`)
  must list `frser-sqlite-datasource`; then `sudo systemctl restart grafana-server`.
- Logs: `sudo journalctl -u grafana-server -n 50`.
