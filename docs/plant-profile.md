# Plant profile (T-23)
 
Issue: #5 (T-23) · Part of #8 (US-02) · Owner: @eliaszlr
 
The care rules read every threshold from a plant profile in `config/plants/<name>.json`. No threshold is written in the code. `PLANTPULSE_PLANT` in `.env` chooses the profile; the default is `basil`, the demo plant (see `docs/plant.md`).
 
| Profile | Use |
| --- | --- |
| `basil.json` | Demo plant, real timing |
| `basil_demo.json` | Same thresholds, but the wet states trigger after minutes instead of hours, so they can be shown live in a 5-minute Sprint Review |
| `tomato.json` | School-garden scenario from the challenge report |
 
All values are **starting values**. Adjust them after calibration (T-12) and after observing the plant; record every change and its reason in the change log.
 
## How to read the soil values
 
The soil value is a relative index, not a water content:
 
- **0 %** = the dry calibration cup (`SOIL_DRY`)
- **100 %** = the wet calibration cup, watered until it drains and left 10 min (`SOIL_WET`). This is *container capacity*: the most water the substrate holds after drainage.
Research gives thresholds as volumetric water content (VWC) or soil tension, so we converted them. Peat-based potting substrates hold roughly 45–65 % VWC at container capacity [4, 5]; we assume about 60 %, and some water left in the air-dried cup. A VWC of 0.30 is then roughly an index of 45–50 %, and 0.15 roughly 20–25 %. The conversion is approximate; calibration with the real plant decides.
 
## Values and their sources
 
### Soil: too dry
 
| Key | Basil | Tomato | Meaning |
| --- | --- | --- | --- |
| `soil.dry_below_pct` | 45 | 65 | Below this: **Check**, feel the soil. |
| `soil.critical_below_pct` | 20 | 45 | Below this: **Attention**, water today. Rain never delays this state. |
 
- **Basil.** In a sensor-controlled study with container basil in peat substrate, growth (height, leaf area, shoot mass) and photosynthesis rose steadily from 0.15 to 0.45 m³/m³ VWC; no visible stress appeared even at 0.15 [1]. So drier soil slows basil rather than killing it quickly. We set **Check** at about 0.30 VWC (index 45), where growth is clearly reduced, and **Attention** at about 0.15 VWC (index 20), the driest level tested; below it there is no evidence that the plant stays undamaged.
- **Tomato.** Tomato is sensitive to drying out. In a three-year field study, triggers that allowed at most 40 % depletion of the available water gave the higher yields, and the best yields came from keeping tension between −10 and −30 kPa (20–24 % depletion) [2]. Extension advice for tomatoes is to irrigate at 20–25 % depletion of the total available water [3]. With the wilting point at roughly index 15–20, 40 % depletion is about index 65 (**Check**) and about two thirds depleted is index 45 (**Attention**).
### Soil: too wet
 
| Key | Basil | Tomato | Meaning |
| --- | --- | --- | --- |
| `soil.wet_above_pct` | 90 | 90 | Wetter than this … |
| `soil.wet_check_h` | 24 | 24 | … for this many hours without a break: **Check**, do not water, check drainage. |
| `soil.saturated_above_pct` | 97 | 97 | At or wetter than the wet cup … |
| `soil.saturated_h` | 48 | 48 | … for this many hours: **Attention**, empty the saucer, the roots lack air. |
 
Right after watering the index is near 100 %, which is normal. Too much water only harms roots when the substrate **stays** wet: water fills the pores and the roots get no oxygen. If the air-filled pore space stays low, substrates become waterlogged and root diseases follow [5]. In tomato, stomata close after 24 h of flooding [6], and the leaves start to curl down between 24 and 48 h [7]. This is why the wet states use a duration and not a single reading. The values are the same for both plants because no plant-specific study was found; adjust them after watching how fast the demo pot dries.
 
### Air temperature

| Key | Basil | Tomato | Meaning |
| --- | --- | --- | --- |
| `air.severe_cold_below_c` | 5 | 5 | Colder than this for `duration_h`: **Attention**, move or cover the plant. |
| `air.cold_below_c` | 12 | 10 | Colder than this for `duration_h`: **Check**, look for cold damage on the leaves. |
| `air.hot_above_c` | 35 | 32 | Hotter than this for `duration_h`: **Check**, the soil dries out faster. |
| `air.duration_h` | 0.5 | 0.5 | How long a limit must be crossed without a break. One reading near a limit is not enough: the DHT11 is only accurate to about ±2 °C, and the screen should not jump. `basil_demo` uses 0.05 h (3 min). |

The team decided on 2026-11-21 that air temperature changes the state (before, it was context only). Humidity stays context.
 
- **Basil** is chilling-sensitive: injury occurs at or below 10 °C and is severe at or below 5 °C [8]; other sources put the limit at 12 °C [9]. We use 12 °C. The hot limit (35 °C) is our own assumption; basil grows best in the mid- to upper-80s °F (about 29–31 °C) [10] and no reliable upper limit was found.
- **Tomato**: temperatures above 32 °C harm fruit set, and below 10 °C growth suffers [11]. Chilling injury is reported between 0 and 5 °C [12].

### Light
 
| Key | Basil | Tomato | Meaning |
| --- | --- | --- | --- |
| `light.low_below_pct` | 20 | 20 | Relative light level that counts as low. |
| `light.afternoon_from_h` / `afternoon_to_h` | 14 / 18 | 14 / 18 | Local hours checked. Night is ignored. |
| `light.low_afternoons` | 3 | 3 | Afternoons in a row with low light before a warning (US-07). |
 
Both plants need a lot of light; basil grows best at a daily light integral of about 29 mol·m⁻²·d⁻¹ [10]. Our light sensor gives a relative percentage, not a calibrated light intensity, so these values cannot come from the literature. Set `low_below_pct` from the day and night readings of T-13. There is no "too much light" rule: the sensor cannot measure intensity, and for a plant under a porch roof or indoors in Bilbao in winter, too little light is the realistic problem.
 
### Rain
 
| Key | Basil | Tomato | Meaning |
| --- | --- | --- | --- |
| `rain_exposed` | `false` | `false` | Both plants are sheltered, so a forecast never delays a prompt. |
| `rain.min_mm` | 1.0 | 1.0 | Rain within the window that counts as "rain expected" (decision 001, provisional). |
| `rain.window_h` | 6 | 6 | Hours of forecast added up. |
 
## Validation
 
`plantpulse/profile.py` rejects a profile with a missing value, a non-boolean `rain_exposed`, soil thresholds not in the order `critical < dry < wet <= saturated`, wet durations not in the order `0 < wet_check_h <= saturated_h`, or `cold_below_c` not below `hot_above_c`.
 
## Sources
 
1. Currey et al. (2019), *Substrate Volumetric Water Content Controls Growth and Development of Containerized Culinary Herbs*, Agronomy 9(11):667. https://www.mdpi.com/2073-4395/9/11/667
2. Jaria, F., *Irrigation scheduling strategies for tomato production in Southwestern Ontario*, McGill University. https://escholarship.mcgill.ca/downloads/kd17cx70n
3. Guan & Maynard, *High Tunnel Tomato Irrigation Management*, Purdue University Extension (2025). https://southcenters.osu.edu/sites/southc/files/site-library/site-images/2025%20Tri-state%20HT%20Tom%20Irri.pdf
4. HortScience 46(4):627, water-holding capacity of greenhouse substrates. https://journals.ashs.org/view/journals/hortsci/46/4/article-p627.xml
5. Greenhouse Grower, *Predicting Plant Water Uptake*. https://www.greenhousegrower.com/production/plant-culture/perennials-production/predicting-plant-water-uptake/
6. McNamara & Mitchell (1989), *Differential flood stress resistance of two tomato genotypes*, J. Amer. Soc. Hort. Sci. 114(6):976. https://agris.fao.org/search/ru/records/65dedfe4b766d82b18feae7e
7. *Flooding tolerance of tomato genotypes during vegetative and reproductive stages*, Brazilian Journal of Plant Physiology. https://scielo.br/j/bjpp/a/xwSmRgbC3d4vLXQKtCzRSkz/?lang=en
8. Journal of Medicinally Active Plants, sweet basil chilling injury. https://openpublishing.library.umass.edu/jmap/article/1834/galley/1792/download
9. *Preharvest and postharvest techniques that optimize the shelf life of fresh basil*, Frontiers in Plant Science (2023). https://pmc.ncbi.nlm.nih.gov/articles/PMC10514919/
10. Produce Grower, *Hydroponic production primer: managing basil production throughout the year*. https://producegrower.com/article/hydroponic-production-primer-managing-basil-production-throughout-the-year
11. National Horticulture Board (India), tomato crop guide. https://www.nhb.gov.in/pdf/vegetable/tomato/tom012.pdf
12. Ontario Ministry of Agriculture, *Extreme temperature effects on tomato and pepper crops*. https://www.ontario.ca/page/extreme-temperature-effects-tomato-and-pepper-crops
## Change log
 
| Date | Profile | Change | Reason |
| --- | --- | --- | --- |
| 2026-11-21 | basil, basil_demo, tomato | First values | From the sources above, before calibration |
 