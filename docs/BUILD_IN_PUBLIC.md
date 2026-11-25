# PRANA-AI — Build-in-Public Post Draft (X / LinkedIn)

> **Attach these 3 screenshots captured in `docs/screenshots/`:**
> 1. `docs/screenshots/01-hero-and-plan.png` — Delhi Hero Dashboard, 24h Boundary-Layer Chart & Clean-Air Note Alert
> 2. `docs/screenshots/02-er-triage-and-chat.png` — Instant `108 / 112` ER Medical Triage Intercept Banner & Ask AI
> 3. `docs/screenshots/03-stale-toggle-and-room-audit.png` — `Simulate Stale Data` Replay Toggle + Multimodal `Audit My Room Photo`

---

Most "AI air quality apps" let an LLM guess numbers from raw PM2.5 and tell a delivery rider to "just stay home." That hallucination pattern breaks user trust fast.

For **Google PromptWars Challenge 06**, I built **PRANA-AI** — a Pan-India household smog & exposure planner engineered around a strict **Neuro-Symbolic split**:

**1. Symbolic Python owns 100% of the physics & math (`engine.py`)**
- Estimated Hourly India CPCB NAQI sub-indices (`PM2.5`, `PM10`, `NO2`) + boundary-layer height (`PBLH`) from Open-Meteo (`CAMS Global ~40 km` + weather forecast)
- Dynamic daytime Golden Window with a strict `<15%` flat-curve honesty rule (never calls polluted air "safe", across both today and the 5-day outlook)
- Hourly-integrated USEPA inhaled lung-dose proxy (`D = sum C_out(h) * kappa * V_E * dt_h * (1 - eta)`) strictly decoupled from ARAI transport `CO2e` savings
- Constraint-aware scheduling: flexible walks shift to cleaner windows; fixed work/delivery shifts stay protected with N95/route harm reduction

**2. Gemini only explains, translates (8 Indian languages), and audits rooms**
- Reads an immutable `EvidenceBundle` JSON
- Every LLM output passes `safety.validate_narrative()` with metric-category binding — if Gemini invents ungrounded numbers, mixes CO2 with PM2.5, or recommends houseplants, the validator catches it and serves a grounded deterministic template instead
- Supports **multi-key rotation + 429/404/503/504 failover** (cooldowns + 8s timeout -> zero-crash **Deterministic Fallback Engine**)
- Includes **Gemini Vision Room IAQ Audit (`POST /v1/audit-room`)** returning 3 practical Rs 0–Rs 500 window/kitchen fixes from a photo

**3. Safety, Accessibility & CI Verification Built In**
- **Hard ER Medical Triage:** Keywords like `"wheezing"`, `"chest pain"`, `"difficulty breathing"`, or `"saans nahi"` short-circuit BEFORE the LLM and surface an urgent **`108 / 112` Emergency Alert** banner (`02-er-triage-and-chat.png`).
- **Simulate Stale Data + Partial Fallback Provenance:** One click in **Data & Judge Mode** switches the app to clearly labeled historical winter replay (`03-stale-toggle-and-room-audit.png`) with transparent upstream gap tracking.
- **Full CI Gate:** Verified with `ruff`, `mypy`, `pytest`, `eslint` (with `jsx-a11y`), `vitest`, and `vite build` (`GET`/`HEAD /health` `200 OK` keep-warm ready).

Plus: Voice `Listen` & `Voice Ask` (Web Speech API), category-specific risk thresholds (`Est. NAQI > 100` alerts for Kids/Seniors/Delivery Riders vs `>150` for Adults), a 1-click School/Office Clean-Air Note generator, and installable iOS/Android PWA support!

What safety guardrail would you add next for health-adjacent GenAI apps?

#PromptWars #BuildInPublic #NeuroSymbolicAI #AirQualityIndia #FastAPI #React #GeminiFlash #CleanAir
