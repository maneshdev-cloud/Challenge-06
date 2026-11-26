# Deployment, Environment & Keep-Warm Runbook

PRANA-AI supports single-origin full-stack deployment on **Vercel** ([`vercel.json`](../vercel.json)), standalone Python API hosting on **Render** ([`render.yaml`](../render.yaml)), or local development via Vite + Uvicorn.

---

## 1. Environment Variables (`.env.example`)

| Variable | Required? | Purpose |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | Optional (Recommended) | Primary Google AI Studio key for Gemini Flash briefings, chat, and Vision room audits. Without a key, PRANA-AI serves deterministic templates automatically. |
| `GEMINI_API_KEY_BACKUP` | Optional | Secondary fallback API key rotated automatically on `429 RESOURCE_EXHAUSTED`. |
| `GEMINI_API_KEYS` | Optional | Comma-separated pool of Gemini API keys checked ahead of single-key fallbacks. |
| `PRANA_BUNDLE_SECRET` | Recommended in Prod | Dedicated server secret used for HMAC-SHA256 signing and verification of `EvidenceBundle` payloads across serverless instances and restarts. |
| `ALLOWED_ORIGINS` | Recommended in Prod | Comma-separated allowlisted browser origins (e.g., `http://localhost:5173,http://127.0.0.1:5173,https://prana-ai-promptwars.vercel.app`). |
| `VITE_API_BASE_URL` | Frontend Split Deploy | Set only if frontend and backend run on different origins (defaults to `/api` for Vite proxy and Vercel same-origin routing). In split-origin production deploys, also add the backend origin to `connect-src` in [`vercel.json`](../vercel.json) (or proxy `/api/(.*)` through Vercel rewrites so `connect-src 'self'` remains valid). |
| `VITE_API_TARGET` | Optional (Local Dev) | Overrides Vite proxy destination (defaults to `http://127.0.0.1:8000`; loaded from shell env or root `.env`). |
| `TRUST_PROXY_HEADERS` | Optional | Set `1` **only** behind a custom reverse proxy outside Vercel/Render that strips/overwrites incoming `X-Forwarded-For` / `X-Real-IP` headers and restricts direct external access to the backend port; ignores `CF-Connecting-IP` unless `RENDER` is set. |

---

## 2. Vercel Full-Stack Deployment (`vercel.json`)

- **Routing:** `vercel.json` serves the `frontend` Vite SPA (`/* -> /index.html`), routes `/api/(.*)` (stripping `/api`), `/v1/(.*)`, and `/health` to the `backend` FastAPI entrypoint (`backend/main.py`).
- **Security & Cache Headers Applied at the Edge:**
  - Strict `Content-Security-Policy` (`default-src 'self'`, `script-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'`, `upgrade-insecure-requests`).
  - `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`
  - `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Cross-Origin-Opener-Policy: same-origin`, `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: camera=(self), microphone=(self), geolocation=(self), payment=(), usb=()`
  - Immutable 1-year asset caching on `/assets/(.*)` and `Cache-Control: no-store` on `/api/(.*)` and `/v1/(.*)`.

---

## 3. Render Backup Backend (`render.yaml`)

- **Runtime:** Python `3.12.10` (`rootDir: backend`, free web service tier).
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Health Check:** `/health` (configure `PRANA_BUNDLE_SECRET`, `ALLOWED_ORIGINS`, and optional `GEMINI_API_KEY*` in the Render dashboard).
- If splitting frontend (Vercel) and backend (Render), either route `/api/(.*)` to your Render URL in Vercel rewrites (same-origin, keeping `connect-src 'self'`) or add your exact Render origin to `connect-src` in [`vercel.json`](../vercel.json), and include your Vercel origin in Render's `ALLOWED_ORIGINS`.

---

## 4. Free 5-Minute Keep-Warm Setup (Prevents Cold Starts)

Both `GET /health` and `HEAD /health` return `200 OK` (`{"status":"ok","app":"PRANA-AI","version":"1.0.0"}`) from `backend/main.py`:

1. **UptimeRobot (Recommended Free Tier):** Add an **HTTP(s)** monitor targeting `https://<your-backend-domain>/health` at a **5-minute** interval (`HEAD` or `GET`).
2. **GitHub Actions Cron Backup ([`.github/workflows/keep-warm.yml`](../.github/workflows/keep-warm.yml)):** Scheduled every `*/5 * * * *`; add repository secret `PRANA_HEALTH_URL` under **Settings -> Secrets and variables -> Actions** pointing to your deployed `/health` URL.

---

## 5. CI Verification Gate ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml))

Every push and pull request targeting `main` runs:
1. **Backend Job (Python 3.12):** `ruff format --check backend scripts`, `ruff check backend scripts`, `ruff check --select C901,B backend`, raw `pylint backend/*.py` (`10.00/10`), `bandit -r backend -x backend/tests -q`, full transitive `pip-audit -r backend/requirements.txt`, `mypy backend`, `pytest -v --cov --cov-fail-under=90 backend/tests` (source-only line + branch coverage via `pyproject.toml`), and `python scripts/smoke.py`.
2. **Frontend Job (Node 22):** `npm ci`, `npm run audit:deps` (`npm audit --omit=dev --audit-level=high`), `npm run lint` (`eslint` + `jsx-a11y`), `npm run test:coverage` (`vitest run --coverage`), `npm run build` (`vite build`), and `npm run bundle:check` (gzipped initial JS <= `95 kB` & non-preloaded lazy Recharts check).
   *(Note: If deploying split Vercel + Render origins with `VITE_API_BASE_URL` instead of same-origin `/api` rewrites, add your exact backend origin to `connect-src` in `vercel.json`.)*
