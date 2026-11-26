# Security Policy — PRANA-AI

## Reporting a Vulnerability

Please report security issues privately via the repository **Security → Advisories** workflow rather than public issue threads.

## Threat Model & Verified Controls

| Threat | Control | Location | Verification |
| :--- | :--- | :--- | :--- |
| **API key exposure** | `GEMINI_API_KEY` / `GEMINI_API_KEYS` and `PRANA_BUNDLE_SECRET` are read strictly in server modules; never bundled into `frontend/` (`VITE_*`). | `backend/gemini_client.py`, `backend/safety.py` | Vite client build isolation & test suite |
| **Client-side evidence tampering** | Server signs every `EvidenceBundle` with HMAC-SHA256 (`PRANA_BUNDLE_SECRET`, isolated from `GEMINI_API_KEY`); `/v1/chat` rejects tampered/unsigned bundles with `403`. | `backend/safety.py`, `backend/main.py` | `backend/tests/test_safety.py`, `test_api.py` |
| **LLM number fabrication / hallucination** | Post-generation category-bound validator verifies every number against precomputed CPCB/USEPA/ARAI allowlists and blocks unsafe claims ("safe window", houseplants); failures seamlessly fall back to templates. | `backend/safety.py`, `backend/engine.py`, `backend/explainer.py` | `backend/tests/test_safety.py`, `test_explainer.py` |
| **Proxy IP spoofing / rate-limit bypass** | Forwarding headers (`x-vercel-forwarded-for`, `x-real-ip`, rightmost `x-forwarded-for`) are trusted only behind recognized proxy runtimes (`VERCEL`, `RENDER`, or `TRUST_PROXY_HEADERS=1`); direct socket traffic uses `request.client.host`. | `backend/request_guards.py` | `backend/tests/test_request_guards.py` |
| **Cross-site request abuse (CSRF quota theft)** | Browser POST requests carrying an unallowlisted or cross-host `Origin` header are rejected with `403`. | `backend/request_guards.py`, `backend/main.py` | `backend/tests/test_request_guards.py`, `scripts/smoke.py` |
| **Malicious image upload / EXIF leak / DoS** | Streaming 5 MB read limit (`413`), strict JPG/PNG/WebP MIME & Pillow header check (`415`), `Image.MAX_IMAGE_PIXELS = 25_000_000` bomb limit, and full EXIF stripping via clean re-encode. | `backend/image_audit.py` | `backend/tests/test_api.py` |
| **XSS, clickjacking & MIME sniffing** | Strict CSP (`script-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'`), HSTS preload, COOP `same-origin`, `nosniff`, `X-Frame-Options: DENY`, `Cache-Control: no-store` on API responses, and `X-Request-Id` log correlation. | `vercel.json`, `backend/request_guards.py` | `backend/tests/test_request_guards.py`, `scripts/smoke.py` |
| **Dependency vulnerabilities** | Pinned patched versions (`pillow==13.0.0`, `python-multipart==0.0.31`, `python-dotenv==1.2.2`) gated by CI checks. | `backend/requirements.txt`, `.github/workflows/ci.yml` | CI workflow |

## Known Operational Notes

- In-memory rate limiting and the Open-Meteo TTL cache (`900s`, `256` entries) operate per serverless/container instance.
- Ensure `PRANA_BUNDLE_SECRET` is configured in Render and Vercel environment variables so evidence signatures persist consistently across restarts and horizontal replicas.
