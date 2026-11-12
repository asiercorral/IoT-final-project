# Plant and substrate for the MVP

Issue: #33 (T-06) · Sprint 1 · Owner: @eliaszlr · Date: 2026-11-12

## Decision

| Item | Choice |
| --- | --- |
| Plant | Sweet basil (*Ocimum basilicum*) in a pot |
| Pot | Plastic pot, about 12–14 cm, with drainage hole and saucer |
| Substrate | Universal potting soil (*sustrato universal*), brand: `<brand / product name>` |
| Spare substrate | Rest of the same bag, kept in a closed bag for calibration and demos |
| Calibration samples | Two cups of the same substrate: one dry, one wet (see below) |

## Why this choice

- **Season.** Our use case is a tomato plant in a school garden, but tomatoes do not grow outdoors in Bilbao in November and December. Basil is cheap, easy to buy now, and shows clear signs of thirst (drooping leaves), so pupils' observations can be compared with the sensor readings.
- **Demo.** A potted plant can be carried to the Sprint Reviews and the final demonstration in December.
- **Same story, configurable profile.** The care rules will read their thresholds from a plant profile file (T-23). The demo uses a basil profile; the tomato profile stays the reference for the school scenario in the report.
- **Calibration.** The soil probe gives a relative index, not a water-content percentage (report, section 5). Its readings depend on the substrate, so the plant and the calibration cups use **the same substrate from the same bag**. If the plant came in a different soil, it is repotted into this substrate.
- **Low cost and reusable.** Total cost about 10–15 €; the substrate can be reused for repeated tests.

## Calibration samples

These two cups give the raw reference values for the soil probe (T-12, T-16).

| Sample | How to prepare | Used as |
| --- | --- | --- |
| Dry cup | Fill with substrate, leave uncovered indoors for 2–3 days until dry to the touch | `SOIL_DRY` reference |
| Wet cup | Fill with substrate, water until water drains from the bottom, wait 10 min | `SOIL_WET` reference |

Both cups need drainage holes and should be filled to at least the depth of the probe's sensing area.

## Probe placement

Following section 5 of the challenge report:

- Insert the soil probe near the roots, a few centimetres away from the stem.
- Bury only the sensing part; keep the electronics and the connector above the soil and away from watering.
- Always use the same position and depth, so readings stay comparable over time. Mark the position on the pot edge.

## Status

- [ ] Basil plant bought and potted in the chosen substrate
- [ ] Spare substrate available
- [ ] Dry and wet calibration cups prepared
- [ ] Photo added: `docs/img/plant.jpg`

![Plant, pot and calibration cups](img/plant.jpg)
