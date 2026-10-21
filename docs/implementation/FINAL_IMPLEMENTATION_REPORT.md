# Final Implementation Report

Date: 2026-10-21

## A. Implementation summary

Replaced the active PaddleOCR business-card route with a backend-only OpenRouter vision client. The route still accepts one front and optional back image at the existing API path and returns editable contact fields in the legacy review form shape. Image type, byte size, pixel count, EXIF orientation, and output dimensions are checked before provider use. Provider calls use configurable model, timeout, retries, token limit, and strict JSON Schema output, followed by Pydantic validation. Registration requires an explicit data-processing agreement; follow-up contact is a separate optional opt-in. Card scanning requires separate AI image consent before the provider call. Consent timestamps and notice versions are recorded. Browser retries reuse an idempotency key for unchanged submissions, backed by a unique database index. Provider failures return a manual-entry fallback.

## B. Changed files

Updated backend OCR/configuration, image preprocessing, Compose environment, requirements, Docker image, README, and startup behavior for test database overrides. Added the backend OpenRouter adapter, address/consent/idempotency migrations, PWA manifest/service worker/icons, mocked tests, production Nginx/Certbot profiles, certificate scripts, production environment generator, and operator-provisioned password login. Removed the unused Paddle engine and model warmup scripts. Local `backend/.env` stores the user-provided key and is ignored by Git.

## C. Architecture

- [System diagram](../architecture/system.md)
- [AI scanning diagram](../architecture/ai-scanning.md)
- [Database diagram](../architecture/database.md)
- [Deployment diagram](../architecture/deployment.md)
- [Lead lifecycle diagram](../architecture/lead-lifecycle.md)

## D. AI integration

Default model: `google/gemini-3.8-flash` through `https://openrouter.ai/api/v1`; both are configurable. The key is backend-only. Output includes name, company, title, email, phone, website, optional address, warnings, and uncertain fields. Empty values become null. Address is editable in the visitor form, persisted in the lead, visible to authorized staff, and included at the end of exports to preserve existing columns. Tests mock the provider and make no billable request.

## E. UI/UX

The existing capture/review design remains in place with address editing, separate AI image consent before scanning, required data-processing consent, and optional follow-up consent. A PWA manifest, install icons, and an offline static shell were added; API calls are never cached. No screenshot artifacts were generated in this pass.

## F. Responsiveness

No new browser or device checks were completed. README's previous measurements are historical, not re-run results.

## G. Database and integrations

Added reversible Alembic migrations for nullable lead address, consent metadata, and interaction idempotency. Historical interactions remain null for consent rather than being backfilled as if consent had occurred. Address and consent metadata were appended to Sheets and Excel output to preserve existing columns. Live Sheets synchronization was not tested.

## H. Security

Credentials remain backend settings and are absent from `.env.example` values, frontend code, and API responses. The local key is in ignored `backend/.env`. Images are normalized before provider transfer and staged privately only after successful extraction. Production startup requires a key if scanning is enabled. Rotate the key if it was exposed unintentionally.

Production team access uses allowlisted password accounts. The CLI prompts interactively, stores salted scrypt hashes, and the login endpoint is rate-limited. Production sessions are HTTP-only and secure. Password reset is an operator CLI action.

## I. Test results

Backend tests: **30 passed** (including SQLite backup integrity, password hashing/login, OCR validation, idempotency, and mocked vision calls). Ruff: **passed**. Alembic upgrade to head on in-memory SQLite: **passed**. Production Compose profiles validate; PowerShell environment and certificate scripts parse; generated environment values were checked and test secrets discarded. PWA manifest JSON validation and `git diff --check`: **passed**. The local Docker build is blocked by access denied on the Windows Buildx lock. Frontend lint/test/build remain blocked because dependencies are incomplete and npm registry access is offline/cache-only. No live provider call was performed.

## J. Performance

No live provider latency or extraction-quality measurements were collected.

## K. Deployment

For local backend use, configure `backend/.env` and start FastAPI from the backend directory. Docker Compose reads the ignored root `.env`; production settings, Nginx TLS bootstrap/renewal, password provisioning, and the planned `connect.latentsig.com` origin are documented in [DEPLOYMENT.md](../../DEPLOYMENT.md). No deployment, DNS update, or live certificate request was made. See the [event day runbook](../runbooks/EVENT_DAY.md).

## L. Remaining external dependencies

Live OpenRouter compatibility/quality verification, VPS availability, domain/DNS approval, TLS issuance/renewal scheduling, deployed PostgreSQL/Redis and external backup restore evidence, administrator password provisioning, Sheets credentials, legal review of the consent notice and retention policy, fresh browser QA, and physical-device camera checks remain external.

## M. Release readiness

**CONDITIONAL.** The local AI integration, consent capture, address persistence, PWA shell, production reverse-proxy configuration, password authentication, and automated backend tests are implemented. Production launch remains blocked on infrastructure/DNS approval, policy approval, provider smoke testing, and fresh full-stack/browser verification.
