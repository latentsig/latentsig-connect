# Deployment

## Local container stack

Docker Compose starts PostgreSQL, Redis, the FastAPI API, the Google Sheets integration worker, daily verified database backups, Prometheus monitoring, and the React app:

```powershell
docker compose up --build
```

Open `http://localhost:8080/connect` or `http://localhost:8080/admin/login`. Development email sign-in is enabled only in local development. Prometheus runs at `http://localhost:9090`; API live/readiness checks are `/health/live` and `/health/ready`. The database, private business-card files, backup archives, and monitoring data persist in named volumes. Use synthetic data for local development.

## Production environment

For the planned production origin `https://connect.latentsig.com`, generate a root `.env` with unique application and database secrets. This step only writes a local ignored environment file; it does not deploy or change DNS:

```powershell
./scripts/Initialize-Production.ps1 -PublicUrl https://connect.latentsig.com -AdminEmail bhoomika@latentsig.com -AdditionalAdminEmails bharat@latentsig.com
```

The script configures Bhoomika as the initial admin and puts both Bhoomika and Bharat in `ADMIN_EMAIL_ALLOWLIST`. OCR starts disabled until an OpenRouter key is securely configured in `.env`. Never copy credentials into source files or chat. `deploy/production.env.example` documents the configurable production settings without secrets.

## VPS deployment with Nginx and HTTPS

The production profile keeps PostgreSQL, Redis, FastAPI, React, the integration worker, and backups inside Compose. The frontend is bound to `127.0.0.1:8080` for local review; production traffic enters through Nginx on ports 80 and 443. Nginx proxies API and health paths to FastAPI and visitor/admin pages to React. Forwarded client addresses are trusted only on the private Compose network, so rate limits see the visitor IP. PostgreSQL, Redis, and FastAPI have no host-published ports.

Deployment is intentionally not performed by this setup task. Before launch, provision a Linux VPS, approve the domain, and point its DNS records to the VPS. Permit inbound TCP 80/443 and restricted SSH in the host firewall. Keep `.env` and service-account files out of source control.

From the repository directory on the VPS:

1. Generate the root `.env` with the PowerShell command above, or copy `deploy/production.env.example` and provide unique `APP_SECRET` and `POSTGRES_PASSWORD` values from a secrets manager. Confirm `PUBLIC_DOMAIN=connect.latentsig.com`, both admin emails are allowlisted, and `OCR_ENABLED=false` until the provider key is configured.
2. Start the application and Nginx bootstrap listener with `docker compose --profile production up --build -d`. Nginx serves ACME challenges over HTTP and returns a temporary 503 for other paths until a certificate exists.
   The frontend image build uses `FRONTEND_URL` as the QR code’s public origin. Confirm it is `https://connect.latentsig.com` before building; event capture links and downloaded QR codes will then open that public HTTPS address on phones. Rebuild the frontend image if the public origin changes.
3. After approved DNS resolves to the VPS and port 80 is publicly reachable, issue the certificate with `sh scripts/issue-tls-certificate.sh` or `./scripts/Issue-TlsCertificate.ps1`. Nginx restarts and selects its HTTPS configuration after issuance. HTTP requests then redirect to HTTPS.
4. Provision account passwords interactively so they are not command-line arguments or shell-history entries:

   ```sh
   docker compose exec backend python -m app.cli set-password bhoomika@latentsig.com
   docker compose exec backend python -m app.cli set-password bharat@latentsig.com
   docker compose exec backend python -m app.cli grant-admin bharat@latentsig.com
   ```

   Passwords are hashed with salted scrypt. Login is rate-limited, limited to the configured allowlist, and issued in secure HTTP-only session cookies. Development email-only sign-in is unavailable when `APP_ENV=production`.
5. For hosted card extraction, set `OPENROUTER_API_KEY` using the deployment secret mechanism and set `OCR_ENABLED=true`; the backend validates that production configuration at startup. Use a synthetic card for a smoke test after deployment and consent review.
6. Schedule `sh scripts/renew-tls-certificate.sh` or `Renew-TlsCertificate.ps1` daily. It checks renewal and reloads Nginx. Keep an external copy of PostgreSQL backups and test a restore before relying on them.

Google Sheets remains optional until service-account access and a sheet ID are configured. Production requires PostgreSQL, Redis, HTTPS frontend origins, a unique app secret, and explicit admin allowlists.

The Compose stack takes a verified `pg_dump` archive immediately and then daily, retaining 14 days in the `database_backups` volume. Prometheus scrapes the API every 15 seconds and evaluates availability and server-error alerts. These local services need an external copy of backups and an alert receiver for production operations.

For the current SQLite development database, create and verify a local snapshot with `cd backend; python -m app.services.backup`. PostgreSQL snapshots run automatically in the Compose stack.

## CI

GitHub Actions runs TypeScript checks, Vitest, the frontend production build, Ruff, pytest, Alembic migration/schema checks, and production Compose configuration validation. Browser end-to-end tests are run locally with the API and OCR dependencies available:

```powershell
cd frontend
npm run test:e2e
```
