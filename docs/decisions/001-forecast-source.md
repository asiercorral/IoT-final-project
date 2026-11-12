# 001 – Forecast source
 
Date: 2026-11-11 · Issue: #34 (T-17) · Owner: @eliaszlr · Status: accepted
 
## Question
 
Can PlantPulse get a rain forecast for Bilbao automatically, with no manual steps, and is it detailed enough for our rule "wait if rain is expected and it reaches the plant" (US-04)?
 
## What we tried
 
| Step | Result |
| --- | --- |
| API key requested in the Open Data Euskadi API key app | Key version 1.0.0 issued and active on 2026-11-11, unlimited validity |
| Authentication | JWT signed with RS256 using our private key, claims `aud=met01.apikey`, `version=1.0.0`, `email`, `iat`, `exp`; sent as `Authorization: Bearer <JWT>` |
| `GET /euskalmet/geo/regions/basque_country/zones` | HTTP 200; Bilbao is in zone `great_bilbao` |
| `GET .../zones/great_bilbao/locations/bilbao/forecast/at/{yyyy}/{mm}/{dd}/for/{yyyymmdd}` | HTTP 200; daily temperature, min/max and a free-text forecast only, no rain amount |
| `GET .../locations/bilbao/forecast/trends/measures/at/{yyyy}/{mm}/{dd}/for/{yyyymmdd}` | HTTP 200; 24 hourly entries, each with precipitation (mm), temperature, wind and a weather symbol |
| Open-Meteo `GET /v1/forecast` for Bilbao (comparison) | HTTP 200 without a key; hourly precipitation (mm) and precipitation probability (%) |
 
Samples are stored in `docs/euskalmet_zones.json`, `docs/euskalmet_forecast.json` and `docs/euskalmet_trends.json`. The test script is `scripts/euskalmet_test.py`.
 
## Findings
 
- Automatic access to Euskalmet works.
- The **trends/measures** endpoint gives an hourly precipitation amount in mm. This is enough for a numeric rule. Example for 2026-11-12: 28.5 mm in total, at most 4.0 mm in one hour.
- Euskalmet gives **no rain probability**, only amounts. Open-Meteo gives both.
- Each request covers one calendar day, so the next 24 hours need two requests (today and tomorrow).
- The hourly entries are not sorted; they must be sorted by their `range` field.
- The weather symbols are categories and do not always match the amount (e.g. "Lluvia fuerte, > 15 mm/h" with 4.0 mm). The rule uses only the numeric `precipitation.value`.
- Authentication is more complex than Open-Meteo: the private key must exist on the Raspberry Pi, outside the repository.
## Decision
 
**Euskalmet is the primary forecast source; Open-Meteo is the fallback.**
 
- `FORECAST_SOURCE=euskalmet` in `.env` selects Euskalmet; if a request fails (no Internet, expired key, API error), the system tries Open-Meteo.
- If both fail, the last cached forecast is used and marked as outdated; an outdated forecast never delays a watering prompt.
- "Rain expected" means: at least 1 mm in total over the next 6 hours, according to the forecast. This threshold is provisional and will be reviewed with the rule engine in Sprint 2/3.
## Why
 
- Euskalmet is the official Basque weather service, was named in our challenge report and in the project brief, and its hourly amounts are enough for our rule.
- Open-Meteo needs no key and adds rain probability, which makes it a good fallback if Euskalmet is unreachable.
- Keeping both behind one function (`get_forecast()`) means the rule engine does not depend on either API.
## Consequences
 
- The private key is stored in `secrets/` and the path in `.env`; both are in `.gitignore`. It must be copied to the Pi manually.
- The forecast module needs two requests per update and must parse and sort the hourly entries.
- The free Open-Meteo API is for non-commercial use. A commercial PlantPulse deployment would rely on Euskalmet or a paid plan.