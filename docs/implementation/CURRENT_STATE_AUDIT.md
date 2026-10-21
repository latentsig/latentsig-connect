# Current State Audit

Audit date: 2026-10-21. Findings are based on repository inspection; previous README test counts are historical and were not treated as current results.

## Existing capabilities

- **P1 — Implemented:** React public capture, manual registration, business-card review, QR attribution, admin workflows, lead deduplication, private local/S3 storage, Excel export, and retryable Google Sheets integration.
- **P1 — Implemented:** FastAPI, SQLAlchemy/Alembic, SQLite local mode, PostgreSQL production mode, role checks, login sessions, rate limiting, Docker Compose, backup scripts, and health endpoints.
- **P1 — Implemented:** Image MIME checks, per-image size checks, EXIF correction, private staging, and user confirmation before lead creation.
- **P1 — Replaced:** The scan route now uses a backend-only OpenRouter adapter with JSON Schema constrained output, Pydantic validation, bounded retries, and explicit manual fallback. PaddleOCR is no longer an active dependency.
- **P1 — Added:** Address is editable and persisted. Separate AI image consent and final data/follow-up consent are recorded with timestamps and notice versions; historical records remain unmarked.
- **P2 — Added:** PWA install metadata and an offline static shell that excludes APIs and lead data.

## Gaps and risks

- **P0 — External deployment blocker:** Production deployment configuration is prepared for `connect.latentsig.com`; the VPS, domain approval/DNS, TLS issuance, external backup copy, and live health/restore checks remain unavailable and were not changed here.
- **P1 — Provider verification pending:** OpenRouter documentation currently lists the configured Gemini 3.8 Flash model, image input, and JSON Schema response format. Calls are mocked in tests; this audit did not make a billable live request, so the configured account still needs a synthetic-card smoke test.
- **P1 — Data retention:** Private card retention is configured, but event-specific legal basis, retention approval, and deletion workflow need operator review before public launch.
- **P1 — Identity:** Production password login now uses allowlisted accounts, salted scrypt hashes, rate limiting, interactive operator provisioning, and secure session cookies. Password reset and federated identity remain unimplemented; password changes are operator actions.
- **P1 — Reliability:** Browser retries reuse UUID idempotency keys, backed by a nullable unique interaction index. Sheets recovery was not exercised against a live Google account.
- **P2 — QA:** Browser/device coverage in README is historical; physical camera, Safari/WebKit, and 2026 event day workflows need fresh verification.
- **P2 — AI normalization:** Model output is validated structurally and bounded in length. Email/phone correctness remains visitor-confirmed; confidence values in the legacy response shape are UI hints, not calibrated probabilities.
- **P1 — Consent approval:** Consent capture is implemented, but wording and retention must be approved by the event owner/legal reviewer before public deployment.

## Security notes

- OpenRouter credentials are read by backend settings only. The local key is stored in ignored `backend/.env`; `.env.example` remains blank.
- Image payloads and provider responses are excluded from explicit provider error logs. Card images are staged privately only after extraction succeeds.
- Any credential entered into a chat should be rotated if it was not intended for persistent use.
