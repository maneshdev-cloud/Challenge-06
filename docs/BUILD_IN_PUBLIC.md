# PRANA-AI — Build-in-Public Post Draft (X / LinkedIn)

> **Attach these 3 screenshots captured in `docs/screenshots/`:**
> 1. `docs/screenshots/01-hero-and-plan.png` — Delhi Hero Dashboard, 24h Boundary-Layer Chart & Clean-Air Note Alert
> 2. `docs/screenshots/02-er-triage-and-chat.png` — Instant `108 / 112` ER Medical Triage Intercept Banner & Ask AI
> 3. `docs/screenshots/03-stale-toggle-and-room-audit.png` — `Simulate Stale Data` Replay Toggle + Multimodal `Audit My Room Photo`

---

Most "AI air quality apps" let an LLM guess numbers from raw PM2.5 and tell a delivery rider to "just stay home." That hallucination pattern breaks user trust fast.

For **Google PromptWars Challenge 06**, I built **PRANA-AI** — a Pan-India household smog & exposure planner engineered around a strict **Neuro-Symbolic split**:

**1. Symbolic Python owns 100% of the physics & math (`engine.py`)**
- CPCB India NAQI sub-indices (`PM2.5`, `PM10`, `NO2`) + boundary-layer height (`PBLH`)
- Dynamic daytime Golden Window with an explicit `<15%` honesty rule (never calls polluted air "safe")
- USEPA inhaled lung-dose proxy (`D = C_out * kappa * V_E * dt * (1 - eta)`) strictly decoupled from ARAI transport `CO2e` savings
- Constraint-aware scheduling: flexible walks shift to cleaner windows; fixed work/delivery shifts stay protected with N95/route harm reduction

**2. Gemini only explains, translates (8 Indian languages), and audits rooms**
- Reads an immutable `EvidenceBundle` JSON
- Every LLM output passes `safety.validate_narrative()` — if Gemini invents an ungrounded number or houseplant myth, the validator catches it and serves a grounded deterministic template instead
- Supports **multi-key rotation + 429/404/503/504 failover** (cooldowns + 8s timeout -> zero-crash `"Offline Smart Engine"` fallback)
- Includes **Gemini Vision Room IAQ Audit (`POST /v1/audit-room`)** returning 3 practical Rs 0–Rs 500 window/kitchen fixes from a photo

**3. Safety & Judge-Ready Resilience Built In**
- **Hard ER Medical Triage:** Keywords like `"wheezing"`, `"chest pain"`, or `"saans nahi"` short-circuit BEFORE the LLM and surface an urgent **108 / 112 Emergency Alert** banner (`02-er-triage-and-chat.png`).
- **Simulate Stale Data Toggle:** One click in **Data & Judge Mode** switches the app to clearly labeled historical winter replay (`03-stale-toggle-and-room-audit.png`) to prove graceful offline degradation.
- **Keep-Warm `/health` Endpoint:** Supports both `GET` and `HEAD /health` (`200 OK`) for free 5-minute UptimeRobot + GitHub Actions pings so cold starts never slow down live demos.

Plus: Voice `Listen` & `Voice Ask` (Web Speech API), category-specific risk thresholds (`NAQI > 100` alerts for Kids/Seniors/Delivery Riders vs `>150` for Adults), a 1-click School/Office Clean-Air Note generator, and installable iOS/Android PWA support!

**What broke along the way (and what fixed it):**
- Passing `<10s` `HttpOptions` deadlines to the Gemini SDK threw `400 INVALID_ARGUMENT` -> moved to pooled `genai.Client` + `asyncio.wait_for(..., timeout=8.0)` + 404/429 skip caches
- All 4 user categories initially looked too similar on `Good`/`Moderate` days -> added explicit lung intake rates (`m3/hr`), 1.55x road multipliers, and distinct `NAQI > 100` vs `> 150` alerts
- Built & tested end-to-end inside **Google Antigravity** with Playwright responsive checks and **26 passing pytest tests** across CPCB math, ER triage, Open-Meteo `404/503/504` fallback, and Gemini `429/503` key rotation.

What safety guardrail would you add next for health-adjacent GenAI apps?

#PromptWars #BuildInPublic #NeuroSymbolicAI #AirQualityIndia #FastAPI #React #GeminiFlash #CleanAir
