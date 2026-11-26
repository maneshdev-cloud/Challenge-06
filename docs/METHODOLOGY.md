# Scientific Methodology, Formulas, Assumptions & Limitations

PRANA-AI strictly separates deterministic domain calculations (Python engine) from conversational explanation (Google Gemini). Every concentration, sub-index, inhaled lung dose Proxy, room score, and commute emissions delta is computed symbolically from public regulatory breakpoints and peer-reviewed exposure coefficients externalized in [`backend/data/constants.json`](../backend/data/constants.json).

---

## 1. Estimated Hourly India CPCB NAQI (`backend/air_quality.py`)

For pollutant $p \in \{\text{PM}_{2.5}, \text{PM}_{10}, \text{NO}_2\}$ at hourly concentration $C$:

$$
I_p = \text{round}\!\left(\frac{I_{\text{hi}} - I_{\text{lo}}}{C_{\text{hi}} - C_{\text{lo}}}(C - C_{\text{lo}}) + I_{\text{lo}}\right), \qquad \text{Est. NAQI} = \max\!\big(I_{\text{PM}_{2.5}},\, I_{\text{PM}_{10}},\, I_{\text{NO}_2}\big)
$$

Continuous interval bridging smoothly interpolates between integer CPCB breakpoint gaps (for example, $30.0 < C < 31.0$), capped at `500`.

### Official CPCB Breakpoint Tables (`constants.json`)

| Category | AQI Range ($I_{\text{lo}}$–$I_{\text{hi}}$) | $\text{PM}_{2.5}$ ($\mu\text{g/m}^3$) | $\text{PM}_{10}$ ($\mu\text{g/m}^3$) | $\text{NO}_2$ ($\mu\text{g/m}^3$) |
| :--- | :---: | :---: | :---: | :---: |
| **Good** | 0 – 50 | 0 – 30 | 0 – 50 | 0 – 40 |
| **Satisfactory** | 51 – 100 | 31 – 60 | 51 – 100 | 41 – 80 |
| **Moderate** | 101 – 200 | 61 – 90 | 101 – 250 | 81 – 180 |
| **Poor** | 201 – 300 | 91 – 120 | 251 – 350 | 181 – 280 |
| **Very Poor** | 301 – 400 | 121 – 250 | 351 – 430 | 281 – 400 |
| **Severe** | 401 – 500 | 251 – 500 | 431 – 600 | 401 – 600 |

- **Key Assumption:** Official India CPCB bulletins define NAQI over a 24-hour station running average. PRANA-AI maps each hourly gridded forecast concentration through CPCB concentration breakpoints as an **Estimated Hourly India AQI** so diurnal morning/evening smog peaks and afternoon mixing dips remain visible for scheduling.

---

## 2. Dynamic Golden Window & `<15%` Flat-Curve Honesty Rule

Across both today's 24-hour forecast (`find_golden_window`) and all 5 outlook days (`build_daily_outlook`), PRANA-AI scans daytime 2-hour sliding windows $h \in \{7, \dots, 17\}$ for the lowest daytime mean $\overline{\text{PM}}_{2.5,\,\text{2h}}$ and compares it to the morning inversion peak $P_{\text{am}} = \max_{h \in \{6..9\}} \text{PM}_{2.5}(h)$:

$$
\text{Reduction \%} = \frac{P_{\text{am}} - \overline{\text{PM}}_{2.5,\,\text{2h}}}{P_{\text{am}}} \times 100
$$

- **Clean Air Classification (`is_clean_air_day`):** `True` only if estimated hourly NAQI stays $\le 100$ across the 24-hour curve.
- **Honesty Rule (`has_meaningful_window`):** `True` only if $\text{Reduction} \ge 15\%$. When winter thermal inversions keep pollution flat all day (`<15%` improvement), PRANA-AI refuses to celebrate an unsafe dip as "safe" and moves flexible outdoor workouts indoors for sensitive household profiles.

---

## 3. Ledger 1 — Hourly-Integrated USEPA Inhaled Dose Proxy (`Breathe Less`)

Evaluated in `backend/exposure.py` by integrating hour-by-hour over every occupied hour $h$ of each activity or multi-hour shift:

$$
D\,(\mu\text{g}) = \sum_{h} C_{\text{out}}(h) \times \kappa_{\text{microenv}} \times V_E \times \Delta t_h\,(\text{hr}) \times (1 - \eta_{\text{mask}})
$$

$$
\text{Cigarettes Avoided} = \frac{D_{\text{baseline}} - D_{\text{optimized}}}{330.0\,\mu\text{g}}
$$

### Exposure & Shielding Coefficients (`constants.json`)

| Parameter | Values | Source & Notes |
| :--- | :--- | :--- |
| **Ventilation Rate $V_E$ ($\text{m}^3/\text{hr}$)** | `sleep`: `0.45`, `seated`: `0.55`, `light_walk`: `1.25`, `elderly_walk`: `1.30`, `child_play`: `1.35`, `brisk_walk`: `1.60`, `running_or_outdoor_work`: `2.70` | US EPA Exposure Factors Handbook (2011 Ed., EPA/600/R-09/052F, Ch. 6) population-mean short-term inhalation rates |
| **Microenvironment Factor $\kappa$** | `open_road_2w_auto`: `1.55`, `walk_sidewalk`: `1.15`, `bus_non_ac`: `1.15`, `indoor_open`: `0.85`, `car_ac_recirc`: `0.80`, `electric_metro`: `0.55`, `indoor_shut`: `0.50`, `indoor_sealed`: `0.28` | Apte et al. (2011) *Atmospheric Environment* (New Delhi on-road auto-rickshaw plumes) & residential penetration proxies |
| **Mask Filtration $\eta$** | `none`: `0.00`, `cloth`: `0.20`, `surgical`: `0.35`, `n95`: `0.80` | Shakya et al. (2017) *JESEE* & NIOSH 42 CFR Part 84 (conservative real-world fit-adjusted N95 factor `0.80`) |
| **Cigarette Equivalence** | `330.0 ug` $\text{PM}_{2.5} \approx 1\text{ cigarette}$ | Muller & Muller (2015), Berkeley Earth (`~22 ug/m3` 24h at `~15 m3/day`) — risk communication benchmark only |

- **Constraint-Respecting Scheduling:** Flexible routines shift into the cleanest daytime interval (`>=15%` improvement) or move indoors (`indoor_shut`/`indoor_sealed`); fixed shifts (school buses, office commutes, 4h–8h delivery shifts) are **never moved** and instead optimize mask protection and route/break harm reduction.
- **Category Threshold Differentiation (`constants.json`):** Sensitive & high-exposure profiles (`students_kids`, `seniors`, `delivery_riders`) trigger alerts above `Est. NAQI > 100`; `adults_commuters` trigger alerts above `Est. NAQI > 150`.

---

## 4. Clean Air Sanctuary Room Scoring (`backend/indoor.py`)

Each household room is deterministically scored (`0–100`) to rank the lowest-infiltration shelter room:

$$
\text{Room Score} = \text{clamp}_{[0,\,100]}\!\left(100 - 15 \cdot N_{\text{ext\_windows}} - 25 \cdot \mathbb{1}_{\text{road\_facing}} - 25 \cdot \mathbb{1}_{\text{kitchen\_adjacent}} - 10 \cdot \mathbb{1}_{\text{large\_volume}}\right)
$$

- **Window Opening Protocol:** Recommends `timed_open` **only** when the daytime minimum outdoor $\text{PM}_{2.5} \le \min(90\,\mu\text{g/m}^3,\, \text{modeled indoor baseline})$. Otherwise enforces `keep_shut_exhaust`, while noting an optional 10–15 minute exhaust-led vent flush if outdoor minimum is $\le 60\,\mu\text{g/m}^3$ and heavy cooking causes indoor stuffiness.
- **Indoor Source Parameters:** Models closed/unsealed infiltration at `0.50` (`0.28` weatherstripped) and a residential kitchen tadka/frying peak proxy of `+220 ug/m3` (Sharma & Jain, 2019), pairing guidance with budget-filtered hacks (`Rs 0`, `Under Rs 500`, `Under Rs 2,200`).

---

## 5. Ledger 2 — ARAI / WRI India Commute Emissions (`backend/emissions.py`)

Strictly isolated from personal inhaled exposure (`Breathe Less`):

$$
\Delta\text{CO}_2\text{e}\,(\text{g}) = d_{\text{km}} \cdot (\text{EF}_{\text{CO}_2,\text{base}} - \text{EF}_{\text{CO}_2,\text{target}}), \qquad \Delta\text{PM}_{2.5,\text{tailpipe}}\,(\text{mg}) = d_{\text{km}} \cdot (\text{EF}_{\text{PM},\text{base}} - \text{EF}_{\text{PM},\text{target}})
$$

### Transport Emission Factors (`constants.json`)

| Mode Key | Label | $\text{CO}_2\text{e}$ (`g/pkm`) | Tailpipe $\text{PM}_{2.5}$ (`mg/pkm`) | Linked Microenvironment ($\kappa$) |
| :--- | :--- | :---: | :---: | :--- |
| `car_diesel_solo` | Diesel Car (Solo) | 178.0 | 42.0 | `car_ac_recirc` (`0.80`) |
| `car_petrol_solo` | Petrol Car (Solo) | 164.0 | 18.0 | `car_ac_recirc` (`0.80`) |
| `auto_cng` | CNG Auto-Rickshaw | 75.0 | 8.0 | `open_road_2w_auto` (`1.55`) |
| `carpool_3p` | Carpool (3 People) | 55.0 | 6.0 | `car_ac_recirc` (`0.80`) |
| `two_wheeler_petrol` | 2-Wheeler (Petrol) | 48.0 | 15.0 | `open_road_2w_auto` (`1.55`) |
| `city_bus` | City Bus | 22.0 | 2.1 | `bus_non_ac` (`1.15`) |
| `electric_metro` | Electric Metro | 14.0 | 0.0 | `electric_metro` (`0.55`) |
| `walk_or_cycle` | Walk / Cycle | 0.0 | 0.0 | `walk_sidewalk` (`1.15`) |

- **Equivalence Constant:** Smartphone charge comparison uses `8.2 g CO2` per charge (`engine_params.phone_charge_co2_g`).
- **Same-Mode Handling:** When baseline and target modes match (for example, an outdoor delivery rider keeping a petrol two-wheeler), counterfactual tailpipe savings cleanly stay `0`.

---

## 6. Authoritative Source Registry

1. **CPCB National Air Quality Index (CUPS/82/2014-15, Table 1.4):** [CPCB Technical Report PDF](https://cpcb.nic.in/displaypdf.php?id=bmF0aW9uYWwtYWlyLXF1YWxpdHktaW5kZXgvRklOQUwtUkVQT1JUX0FRSV8ucGRm)
2. **US EPA Exposure Factors Handbook (2011, EPA/600/R-09/052F, Ch. 6):** [EPA Record](https://cfpub.epa.gov/ncea/risk/recordisplay.cfm?deid=236252)
3. **Apte et al. (2011) — New Delhi In-Vehicle $\text{PM}_{2.5}$ Exposure:** `DOI: 10.1016/j.atmosenv.2011.05.028`
4. **Shakya et al. (2017) — Cloth/Surgical vs. N95 Efficiency:** `DOI: 10.1038/jes.2016.42`
5. **ARAI / WRI India Vehicle Emission Factors:** [ARAI Vehicle Emission Factor Report PDF](https://www.araiindia.com/pdf/Emission_Factor_Development_for_Indian_Vehicles_report.pdf)
6. **Muller & Muller (2015) — Berkeley Earth Cigarette Equivalence:** [Berkeley Earth](https://berkeleyearth.org/air-pollution-and-cigarette-equivalence/)
7. **Live Atmospheric & Geocoding APIs:** Open-Meteo Air Quality (`CAMS Global ~0.4 deg / ~40 km`), Open-Meteo Weather Forecast (`wind_speed_10m`, `boundary_layer_height`), Open-Meteo Geocoding (`India`), BigDataCloud Client Reverse-Geocoding.

---

## 7. Honest Limitations & Safety Boundaries

1. **Coarse Gridded Global Model vs. Hyperlocal Monitors:** Live air forecasts come from Open-Meteo's **CAMS Global (`~0.4 deg` / `~40 km`, 3-hourly interpolated)** model paired with weather forecasts, which smooths street-canyon traffic plumes or construction hotspots compared to a nearby CPCB CAAQMS monitor.
2. **Estimated Hourly CPCB NAQI Proxy vs. 24h Station Average:** Official India CPCB NAQI is a 24-hour station running average; PRANA-AI maps each hourly step through CPCB breakpoints as an **Estimated Hourly India AQI** for intraday timing decisions.
3. **Modeled Exposure Proxy, Not Medical Telemetry:** $V_E$ and $\kappa$ values represent standardized population benchmarks rather than individual spirometry or optical room particle sensors.
4. **8-Language Fallback Boundaries:** Gemini plans, chat replies, Room IAQ audits, and deterministic daily plans/room-audit tips natively support all **8 languages** (`en`, `hinglish`, `hi`, `mr`, `kn`, `bn`, `ta`, `te`). When Gemini is offline or rate-limited, deterministic chat topic routing handles English/Hinglish while referencing the same live precomputed metrics.
5. **Visual IAQ Estimates & Device Voice Differences:** `POST /v1/audit-room` inspects visible room features (EXIF-stripped) without inventing sensor readings; Web Speech synthesis (`Listen`) and recognition (`Voice Ask`) depend on browser HTTPS context and OS language packs.
6. **Medical Emergency Boundary:** PRANA-AI is a planning assistant, never clinical diagnosis. Acute distress symptoms (`wheezing`, `chest pain`, `difficulty breathing`, `blue lips`, regional emergency phrases) immediately bypass AI planning/rate-limiting to display `108 / 112` emergency directives.
