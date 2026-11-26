# PlantPulse · challenge-scope MVP

One plant and one Raspberry Pi 5: soil moisture, light, air temperature and humidity; local MQTT, storage, rules, LED feedback, Flask REST API, local web history and Grafana. Forecasts are the only Internet-dependent component.

## Scope and backlog
The baseline is **7 user stories and 48 tasks** from Backlog (challenge scope). Tasks link to their story with `Part of #N`; Setup tasks are project work. Closed legacy issues are excluded from the active backlog.

- [US-01 LED signal tells pupils when to check the plant](https://github.com/asiercorral/IoT-final-project/issues/3) · Must
- [US-02 Short explanation of each recommendation](https://github.com/asiercorral/IoT-final-project/issues/8) · Must
- [US-03 Teacher views sensor history](https://github.com/asiercorral/IoT-final-project/issues/4) · Must
- [US-04 Recommendations consider rain and rain exposure](https://github.com/asiercorral/IoT-final-project/issues/9) · Must
- [US-05 Distinct fault signal](https://github.com/asiercorral/IoT-final-project/issues/11) · Must
- [US-06 Monitoring continues without Internet](https://github.com/asiercorral/IoT-final-project/issues/31) · Must
- [US-07 Warning about low light over several afternoons](https://github.com/asiercorral/IoT-final-project/issues/32) · Should

## Sprint plan
| Sprint | Working dates | Goal | Review / deadline |
|---|---|---|---|
| Sprint 1 | 5–16 Nov 2026 | Sensing, calibration, local readings, basic status, forecast spike | Review 1: 17 Nov, 5 min |
| Sprint 2 | 17 Nov–2 Dec 2026 | MQTT, storage, rules, LED, Flask API, web, Grafana, forecast | Review 2: 3 Dec, 5 min |
| Sprint 3 | 3–11 Dec 2026 | Faults, Internet loss, validation, protection, power, docs, release | v1.0 and ALUD: 11 Dec |

Sprints transition on review dates. Rehearse on 16 Nov and 2 Dec. Integrate on 30 Nov. Freeze features on 9 Dec. Final demo: week of 14 Dec, 15 min, every member presents.

## Working agreement
- Status: To do → In progress → Review → Done. Backlog holds only untriaged items.
- Priority: Must, except US-07, T-13 and T-42 which are Should.
- Exactly one assignee per issue; task ownership can be rebalanced by the team.
- Branch per issue; pull request with `Closes #N`; one reviewer before merge.
- All four members commit weekly from their own accounts. Pair work uses `Co-authored-by:`.
- A story is Done only when all its tasks are Done and its acceptance criteria are shown on the Pi.
- Keep secrets in ignored `.env`; commit only placeholder values in `.env.example`.

## Initial ownership
| Area | Assignee |
|---|---|
| Sensing and LED | @asiercorral |
| Messaging and storage | @Ibonerdoiza2004 |
| Rules and weather | @eliaszlr |
| Web and docs | @ayaaitkassi0-01 |

Product Owner and Scrum Master remain a team decision tracked in T-02. Device, demo plant, database, forecast provider and sync slots remain open decisions.

## Behaviour to preserve
Normal = two steady LED segments; Check = half bar; Attention = full bar; Fault = blinking bar. Read every 5 min. Missing or invalid sensors, or telemetry older than 10 min, produce Fault. Forecasts older than 6 h are outdated. Rain can delay advice only if the plant is exposed and soil is not critically dry. Soil wet for 24 h gives Check, soaking wet for 48 h gives Attention. Air colder or hotter than the plant profile allows for 30 min gives Check, very cold air gives Attention. Humidity is context. Persistent low light means three afternoons; night is ignored.

## Out of scope
Pump or automatic watering, phone alerts, weekly report endpoint, care button, PIR or voice calls, BLE, visits tracking, city map/dashboard, LoRaWAN, solar/battery nodes, multiple gardens, growth tracking, UV sensing and cloud analytics.

## Sources
- [Backlog (challenge scope)](https://drive.google.com/file/d/132IHZQTUt1mHTtIUlpEJLhnseDWigi8o/view)
- [Project plan](https://drive.google.com/file/d/1OE76R1GGBCSVXh0cgwe8XrwoHGQM-PIs/view)

## Planned architecture

```mermaid
flowchart TD
  Sensors[Soil, light, temperature and humidity] --> Acquisition[acquisition.py]
  Acquisition --> Broker[Local Mosquitto]
  Broker --> Rules[rule_engine.py]
  Forecast[forecast.py and local cache] --> Rules
  Profile[Plant profile] --> Rules
  Rules --> Database[Local database]
  Rules --> Broker
  Broker --> LED[led_service.py and LED bar]
  Database --> Web[Flask web_server.py]
  Database --> Grafana[Local Grafana]
  Web --> Browser[Local web page]
```

The repository is at the planning stage. The programs below are planned deliverables tracked by the backlog, not claims of implemented or tested functionality.

## Interfaces

| Interface | Purpose |
|---|---|
| `plantpulse/school01/plant01/telemetry` | Non-retained timestamped sensor JSON |
| `plantpulse/school01/plant01/state` | Retained state, status code, reason and forecast used |
| `plantpulse/school01/plant01/status` | Retained online/offline state, with MQTT last will |
| `GET /api/status` | Current state, reason, readings, forecast and age |
| `GET /api/history?hours=24` | Timestamped history for the requested period |
| `GET /` | Local readings, history and care explanation |

Example telemetry from the plan:

```json
{
  "device_id": "plantpulse-school01-plant01",
  "timestamp": 1728920000,
  "sensors": {
    "temperature_c": 19.5,
    "humidity_pct": 78.0,
    "soil_moisture_raw": 420,
    "light_pct": 63.5
  },
  "status_code": "CHECK_MOISTURE"
}
```

Unavailable readings are JSON `null`. Add calibrated `soil_moisture_pct` after calibration; light is a relative percentage, not an uncalibrated claim of lux.

## MQTT broker (T-19)

Mosquitto runs on the Pi and every program connects to it. Programs on the Pi use `localhost:1883`; a laptop sets `PLANTPULSE_MQTT_HOST` to the Pi's address. Topic names live in `plantpulse/config.py`; they follow `plantpulse/<site>/<plant>/<kind>`, all lowercase.

| Topic | Published by | Read by | Retained | QoS | Payload |
|---|---|---|---|---|---|
| `plantpulse/school01/plant01/telemetry` | `acquisition.py`, every 5 min (T-20) | storage subscriber (T-22) | no | 1 | One reading, as in the example above |
| `plantpulse/school01/plant01/state` | `rule_engine.py --publish`, `status.py --publish`, `state.py` | `led_service.py`, web page | yes | 1 | State, status code and reason (`plantpulse/state.py`) |
| `plantpulse/school01/plant01/status` | `acquisition.py`: `online` on connect, `offline` as its last will (T-20) | web page | yes | 1 | `online` or `offline` |

Telemetry is not retained: every reading is a new message and the storage subscriber keeps it. State and status are retained, so a program that starts later gets the current value at once.

Install on the Pi (once):

```bash
sudo apt install -y mosquitto mosquitto-clients
sudo cp config/mosquitto/plantpulse.conf /etc/mosquitto/conf.d/
sudo systemctl restart mosquitto
systemctl is-enabled mosquitto      # "enabled": it starts at boot
hostname -I                         # the Pi's address, for the laptop
```

Check from a laptop on the same network, with the Mosquitto clients installed:

```bash
mosquitto_sub -h <pi-address> -t "plantpulse/#" -v     # on the laptop: leave it running
mosquitto_pub -t plantpulse/test -m "hello from the Pi" # on the Pi
```

The laptop prints `plantpulse/test hello from the Pi`. `python -m plantpulse.state NORMAL` on the Pi shows a real state message the same way.

`config/mosquitto/plantpulse.conf` allows clients without a password, so anyone on the same network can read the readings and publish a fake state. This is accepted for the classroom demo; if the Pi joins a shared network, add a password file and client credentials.

## Storage (T-21)

The sensor history is kept in **SQLite**, one file on the Pi: `data/plantpulse.db` ([decision 002](docs/decisions/002-database.md)). The table `readings` has a row per reading and a column per sensor, with the telemetry names: `device_id`, `timestamp` (Unix seconds), `temperature_c`, `humidity_pct`, `soil_moisture_raw`, `light_pct`. A missing value is `NULL`. The MQTT subscriber (T-22) writes it; the web API (T-28) and Grafana (T-31) only read it.

Create it on the Pi (once; repeating it keeps the rows):

```bash
sudo apt install -y sqlite3                         # command-line tool to look inside
python -m plantpulse.storage                        # creates data/plantpulse.db
sqlite3 data/plantpulse.db ".schema readings"       # shows the table
```

## State screen (US-01)

The signal for pupils is a Grove 16x2 LCD (White on Blue) on an **I2C port** of the Base HAT (address 0x3E). The state is published retained on `plantpulse/school01/plant01/state` (format in `plantpulse/state.py`). `plantpulse/led_service.py` follows that topic and rewrites the screen as soon as a new state arrives: a message on the first row and a 10-cell bar on the second. Normal: "All good", 2 cells; Check: "Check the plant", 5 cells; Attention: "Plant needs help", 10 cells. Fault shows "Sensor problem"; an unreadable message or no state shows "No plant state", never "All good". The printed legend is [docs/led-legend.pdf](docs/led-legend.pdf), drawn by `scripts/make_led_legend.py`.

On the Pi, with Mosquitto running (see [MQTT broker](#mqtt-broker-t-19)):

```bash
python -m plantpulse.lcd                    # check the screen
python -m plantpulse.led_service            # state display program
python -m plantpulse.status --publish       # basic soil status -> state, until the rule engine (T-24)
python -m plantpulse.state ATTENTION        # or publish a state by hand
python -m plantpulse.led_service --demo     # the three screens, no MQTT
```

## Open decisions and validation

- Product Owner and Scrum Master: T-02 (#56).
- Grove modules, ports and Pi 5 drivers: T-05 (#7).
- Demo plant and substrate: T-06 (#33).
- Forecast provider: Euskalmet spike T-17 (#34), then document the fallback if needed.
- Database: SQLite, [decision 002](docs/decisions/002-database.md) (T-21, #50).
- Full-chain validation: T-43 (#38).
- Rebuild instructions and wiring evidence: T-47 (#64).

No test results are claimed by this planning update. Hardware, integration and offline behaviour must be demonstrated before their issues are closed.
