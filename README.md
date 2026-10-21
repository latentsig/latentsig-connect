# LatentSig Connect

LatentSig Connect is a mobile-first event lead capture and team follow-up application. Visitors open a QR link, enter their details manually or scan a business card, review the information, and submit an enquiry. The team can review, assign, annotate, and export leads from the admin workspace.

The application includes a React and TypeScript frontend, a FastAPI backend, SQLite for local development, and PostgreSQL and Redis for shared or production deployments.

## Features

- QR-based capture links with event and campaign attribution.
- Responsive manual entry and optional business-card scanning with editable AI-extracted fields.
- Explicit visitor consent before card images are sent through the backend to OpenRouter and its selected vision model provider.
- Admin login, lead search and filters, assignments, notes, event management, and Excel exports.
- Private card image storage, lead and event history, input validation, rate limiting, and idempotent lead submission.
- Optional Google Sheets sync through a retryable background worker.
- Installable progressive web app; only the static app shell is cached.
- Docker Compose deployment profile with Nginx, HTTPS certificate scripts, database backups, and Prometheus monitoring.

## Quick start with Docker

Docker Compose starts the app with PostgreSQL and Redis. From the repository root:

```powershell
docker compose up --build
```

When the services are healthy, open:

- Public capture: [http://localhost:8080/connect](http://localhost:8080/connect)
- Admin login: [http://localhost:8080/admin/login](http://localhost:8080/admin/login)
- API readiness: [http://localhost:8080/health/ready](http://localhost:8080/health/ready)
- API documentation: [http://localhost:8080/docs](http://localhost:8080/docs)
- Prometheus: [http://localhost:9090](http://localhost:9090)

Stop the stack with `Ctrl+C`, or run `docker compose down`. Persistent database, uploaded cards, backups, and monitoring data are stored in named Docker volumes. `docker compose down -v` also deletes those volumes and their data.

Local Compose uses development settings. Its allowlisted email-only admin sign-in is for local review only; it does not verify mailbox ownership and must not be exposed as production authentication. Set `OPENROUTER_API_KEY` in a root `.env` file to enable card scanning in Compose. Manual entry works without an AI key.

## Local development without Docker

### Requirements

- Python 3.11 or later
- Node.js 20.19+ or 22.12+ and npm
- PowerShell 7 or later (`pwsh`) on Windows, macOS, or Linux
- An OpenRouter API key only if you want to use hosted business-card extraction

### 1. Set up and start the backend

From the repository root, run this one-line command in PowerShell 7 on Windows, macOS, or Linux:

```powershell
pwsh -NoProfile -File ./scripts/Start-Backend.ps1
```

The script creates `backend/.env` if it is missing, detects Python 3.11 or later, creates the virtual environment, installs backend requirements, applies Alembic migrations, and starts FastAPI. Keep this terminal running. The default local database is `backend/latentsig.db`; startup creates the default event when it is missing. The script supports PowerShell 7 across Windows, macOS, and Linux, so the setup instructions stay the same on each system.

To enable card scanning, add your key to the ignored `backend/.env` file:

```dotenv
OPENROUTER_API_KEY=your-key
OCR_ENABLED=true
```

The backend sends an opted-in card image to OpenRouter and the configured model provider. Do not enable hosted scanning for images that must remain on-premises. If the provider is not configured or unavailable, visitors can enter details manually.

### 2. Set up and start the frontend

Open a second terminal at the repository root:

```powershell
cd frontend
Copy-Item .env.example .env.local
$npm = if ($IsWindows) { 'npm.cmd' } else { 'npm' }
& $npm install
if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
& $npm run dev
```

Keep this terminal running and open:

- Public capture: [http://localhost:5173/connect](http://localhost:5173/connect)
- Manual form: [http://localhost:5173/connect/manual](http://localhost:5173/connect/manual)
- Card scan: [http://localhost:5173/connect/card](http://localhost:5173/connect/card)
- Admin login: [http://localhost:5173/admin/login](http://localhost:5173/admin/login)
- API readiness: [http://localhost:8000/health/ready](http://localhost:8000/health/ready)
- API documentation: [http://localhost:8000/docs](http://localhost:8000/docs)

The frontend development server proxies `/api` requests to `127.0.0.1:8000`. Leave `VITE_API_BASE_URL` blank for this same-origin proxy, which also lets local admin session cookies work correctly. `VITE_` variables are public browser configuration; never put API keys, passwords, or other server credentials in them.

### Open the local app on a phone

`localhost` on a phone points to the phone itself. To preview on a phone connected to the same Wi-Fi network, stop the regular frontend and backend processes, then run this from the repository root in PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-Mobile-Preview.ps1
```

Open the printed admin URL on your computer, sign in, and scan an event QR code with the phone. If Windows Firewall prompts, allow Python and Node on the private network. This is a local network preview, not a public deployment and not a substitute for production HTTPS.

## Admin access

For local development, open `/admin/login` and enter an address in `ADMIN_EMAIL_ALLOWLIST` from `backend/.env`. The development email sign-in is an allowlist check only; it does not authenticate control of the mailbox. Do not use it for a shared or production deployment.

Production uses password accounts. From the `backend` directory locally, set a password interactively and grant the initial administrator role as needed. On the VPS, prefix these commands with `docker compose exec backend` as shown in [DEPLOYMENT.md](DEPLOYMENT.md):

```powershell
python -m app.cli set-password bhoomika@latentsig.com
python -m app.cli grant-admin bhoomika@latentsig.com
```

The password prompt does not echo the password. Production accounts must also be in `ADMIN_EMAIL_ALLOWLIST`.

## Configuration

Copy `backend/.env.example` to `backend/.env` for local backend settings. Common server-side variables include:

| Variable | Purpose |
| --- | --- |
| `APP_ENV`, `APP_SECRET` | Runtime mode and signed-session key. Production needs a unique secret of at least 32 characters. |
| `DATABASE_URL` | SQLite locally or PostgreSQL for shared/production use. |
| `FRONTEND_URL`, `FRONTEND_URLS` | Public frontend origin and allowed browser origins. |
| `ADMIN_EMAIL_ALLOWLIST`, `INITIAL_ADMIN_EMAILS` | Allowed team accounts and initial administrator accounts. |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OCR_ENABLED` | Backend-only business-card extraction configuration. |
| `REDIS_URL` | Distributed rate limiting; required in production. |
| `PRIVATE_STORAGE_DIR`, `STORAGE_PROVIDER` | Local private file storage or S3-compatible storage. |
| `BUSINESS_CARD_RETENTION_DAYS` | Card image retention period used by the cleanup command. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` or `GOOGLE_SERVICE_ACCOUNT_EMAIL` and `GOOGLE_PRIVATE_KEY` | Optional Google Sheets service account credentials. |
| `GOOGLE_SHEET_ID`, `GOOGLE_SHEET_TAB` | Optional destination spreadsheet and tab. |
| `WHATSAPP_NUMBER` | Optional WhatsApp destination in international digits-only format. |

Copy `frontend/.env.example` to `frontend/.env.local` for browser configuration. The production Docker build sets `VITE_PUBLIC_SITE_URL` from `FRONTEND_URL`; set it to the approved public HTTPS origin before building so event QR codes open on phones.

## Tests and quality checks

### Frontend

```powershell
cd frontend
$npm = if ($IsWindows) { 'npm.cmd' } else { 'npm' }
& $npm run lint
if ($LASTEXITCODE -ne 0) { throw 'Frontend lint failed.' }
& $npm run test
if ($LASTEXITCODE -ne 0) { throw 'Frontend unit tests failed.' }
& $npm run build
```

Run browser end-to-end tests with the backend running:

```powershell
$npm = if ($IsWindows) { 'npm.cmd' } else { 'npm' }
& $npm run test:e2e
```

Install Playwright Chromium once if needed with `$npx = if ($IsWindows) { 'npx.cmd' } else { 'npx' }; & $npx playwright install chromium`. E2E tests use synthetic contact data and Chromium device emulation; they do not replace testing on physical iOS Safari or Android devices.

### Backend

```powershell
cd backend
$python = if ($IsWindows) { '.\.venv\Scripts\python.exe' } else { './.venv/bin/python' }
& $python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Backend test dependencies failed to install.' }
& $python -m ruff check app tests
if ($LASTEXITCODE -ne 0) { throw 'Backend lint failed.' }
& $python -m pytest -q tests/test_api.py tests/test_ocr_parser.py tests/test_passwords.py tests/test_vision.py
if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
& $python -m compileall -q app tests
if ($LASTEXITCODE -ne 0) { throw 'Backend compile check failed.' }
& $python -m alembic upgrade head
```

CI also checks production Docker Compose configuration, builds and validates the Nginx configurations, and checks certificate script syntax. To reproduce database-backed CI tests locally, start PostgreSQL and Redis and set `DATABASE_URL` and `REDIS_URL` before running pytest.

## API overview

The interactive API documentation is available at `/docs` when the backend is running. Main endpoints include:

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/health/ready` | Readiness check. |
| `POST` | `/api/v1/leads` | Validate and save a lead and event interaction. |
| `POST` | `/api/v1/ocr/business-card` | Extract details from a required front image and optional back image. |
| `GET` | `/api/v1/admin/dashboard` | Admin dashboard summary. |
| `GET` | `/api/v1/admin/leads` | Search and filter leads. |
| `GET/PATCH/DELETE` | `/api/v1/admin/leads/{id}` | View or manage a lead, subject to role permissions. |
| `GET/POST/PATCH` | `/api/v1/admin/events` | List and manage capture events. |
| `GET` | `/api/v1/admin/settings` | Integration status without exposing credentials. |
| `GET` | `/api/v1/admin/exports/leads.xlsx` | Download an Excel workbook. |

## Data, consent, and privacy

- Manual entry does not upload a business-card image. Card scanning requires explicit AI-processing consent before the backend sends images to OpenRouter and the selected model provider.
- Images are validated, normalized, and stored in private local or configured S3-compatible storage. Admin access to retained card images is authenticated; images are not served publicly.
- The SQL database is the source of truth. Leads are deduplicated by normalized contact information; event encounters are stored as separate interactions.
- Public submission, OCR, and authentication endpoints use configurable rate limits. Local development can use in-process limits; production uses Redis.
- Admin sessions use signed HTTP-only cookies. Production cookies are secure and admin authentication uses allowlisted password accounts.
- Update `CONSENT_NOTICE_VERSION` when the approved data-processing notice changes.

To run one-off expired card cleanup, use `python -m app.services.storage.retention` from the `backend` directory. For production, schedule retention cleanup and keep backups outside the VPS. Google Sheets syncing is optional; its worker retries transient failures without blocking lead submission.

## Deployment

Production uses Docker Compose with Nginx, HTTPS, PostgreSQL, Redis, FastAPI, the React frontend, an integration worker, database backups, and Prometheus. Deployment requires a provisioned VPS, approved domain and DNS, securely configured secrets, and production admin passwords. **This repository setup does not deploy the application or change DNS.**

See [DEPLOYMENT.md](DEPLOYMENT.md) for the step-by-step VPS, domain, certificate, startup, password, and renewal instructions. The planned public origin is `https://connect.latentsig.com`; it becomes reachable only after deployment and DNS/HTTPS setup.

## Repository layout

```text
frontend/src/                 React public capture and admin application
frontend/e2e/                 Playwright browser tests
backend/app/api/              FastAPI endpoints
backend/app/services/         Lead, vision, storage, and integration services
backend/alembic/              Database schema migrations
backend/tests/                Backend tests
deploy/nginx/                 Nginx bootstrap and HTTPS configuration
scripts/                      Local preview, production setup, backup, and TLS scripts
docs/                         Architecture, runbooks, and implementation notes
docker-compose.yml            Local and production service definitions
DEPLOYMENT.md                 VPS deployment guide
```
