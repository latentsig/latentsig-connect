# Execution Checklist

- [x] Inspect repository state, configuration, OCR endpoint, frontend capture flow, storage, and integrations.
- [x] Replace active local OCR execution with a backend-only OpenRouter vision adapter.
- [x] Preserve the OCR endpoint and response shape consumed by the existing review UI.
- [x] Validate image format, encoded size, pixel count, EXIF orientation, and normalized image dimensions.
- [x] Keep AI extraction separate from lead submission and retain manual fallback.
- [x] Add ignored local OpenRouter configuration and blank safe example settings.
- [x] Add editable address extraction and persistence, reversible migrations, and update exports/integration columns.
- [x] Record separate AI image consent, required data-processing consent, and optional follow-up consent without fabricating historical consent records.
- [x] Add idempotency keys to prevent unchanged browser retries from creating duplicate interactions.
- [x] Add installable PWA metadata, icons, and a static-only offline shell.
- [x] Prepare a production Compose profile with private PostgreSQL/Redis/API services and an Nginx TLS edge for the planned domain.
- [x] Add HTTP-01 certificate issue/renew scripts and an ignored environment generator with unique secrets and the requested admin allowlist.
- [x] Add production allowlisted password login, salted scrypt hashing, rate limits, secure sessions, and interactive password provisioning.
- [x] Add mocked provider tests and architecture/audit documentation.
- [x] Run all backend tests, Ruff, in-memory Alembic upgrade, Compose validation, PowerShell script parsing, environment generation check, manifest validation, and diff checks.
- [ ] Run frontend lint/unit/build and Nginx image tests in CI; local npm registry and Docker Buildx access are unavailable.
- [ ] Verify live provider behavior, production deployment after infrastructure and domain approval, physical-device camera, Sheets credentials, and external backup restore procedure.
