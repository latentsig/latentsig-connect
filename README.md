# LatentSig Connect

LatentSig Connect captures event and meeting leads through a mobile-first QR flow. Visitors can enter details manually or scan a business card with local PaddleOCR, review the extracted fields, choose interests and intent, and submit. The local setup stores leads in SQLite; PostgreSQL is supported for a shared deployment. Contacts are deduplicated by normalized email and phone, while each event encounter remains a separate interaction.

## Review the running app

After starting the frontend and backend below, use these review URLs:

- Public landing and capture choices: **http://localhost:5173/connect**
- Direct manual capture form: **http://localhost:5173/connect/manual**
- Admin login: **http://localhost:5173/admin/login**
- API readiness: **http://localhost:8000/health/ready**
- API interactive docs: **http://localhost:8000/docs**

The API base URL is `http://localhost:8000`.

These are **three URLs, not three separate processes**. The frontend server on port `5173` serves both the public capture form and admin workspace. The backend server on port `8000` serves the API, health checks, and API docs. The local setup below currently starts the backend and frontend in **two separate terminals**; opening the URLs does not start the servers.

## Product flows

- Public pages: `/connect`, `/connect/manual`, `/connect/card`, `/connect/card/review`, `/connect/thank-you`.
- Admin pages: `/admin/login`, `/admin/dashboard`, `/admin/leads`, `/admin/leads/:id`, `/admin/team`, `/admin/settings`.
- QR attribution accepts `ref`, `event`, `utm_source`, `utm_medium`, and `utm_campaign` query parameters and carries them through the visitor flow.
- Manual and OCR review forms classify common consumer email providers as Personal and other domains as Work. Visitors can change this selection.
- The phone control lets visitors choose a country, adds its calling code, requests a telephone keyboard, filters alphabetic characters, validates the international number, and submits E.164 format. OCR uses an explicit international calling code when present and otherwise uses `DEFAULT_PHONE_REGION`.
- OCR accepts a required front image and an optional back image (JPG, PNG, or WEBP; 10 MB each). It reads both locally in one scan, and the visitor reviews and edits every result before submitting. Interest, intent, and requirements are always chosen by the visitor. OCR uses local PaddleOCR, not a hosted model.
- Admin functions include lead search and event/date/interest/intent/status/source/assignment filters, mobile cards and desktop table, detail/history, assignment, notes, private front/back card viewing, team role updates, event creation/activation, summary metrics, and three-sheet Excel export. Sales users see leads assigned to them plus unassigned intake leads; they can view unassigned leads but must wait for a manager to assign them before changing status or adding notes.
- Local admins enter one of five explicitly allowlisted emails. This convenience sign-in is available only when `APP_ENV=development`; it does not verify mailbox ownership and must not be exposed as a shared or production login.
- The configured SQL database is the source of truth. Google Sheets writes run in a retryable background integration worker and do not block lead capture.

## Requirements

- Node.js 20.19+ or 22.12+, npm
- Python 3.11+
- A CPU that can run PaddlePaddle for local OCR

## Local setup (PowerShell)

### 1. Backend

In a terminal from the repository root:

```powershell
cd backend
Copy-Item .env.example .env
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m alembic upgrade head
python -m app.services.ocr.warmup
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The default local database is `backend/latentsig.db`. Startup creates the default event (`bts-2026`) when it is missing. Alembic applies schema changes; do not use `create_all` as a deployment migration strategy. `.env` is read relative to the backend working directory.

The first package installation and OCR model warm-up need internet access. Paddle model files are cached under `backend/.cache/paddlex`. Once dependencies and models are cached, recognition runs on the API host without sending images to an external OCR service. A disconnected event machine must be provisioned and warmed before it goes offline.

### 2. Frontend

In a second terminal from the repository root:

```powershell
cd frontend
Copy-Item .env.example .env.local
npm.cmd install
npm.cmd run dev
```

Open **http://localhost:5173/connect**. Set `VITE_API_BASE_URL=http://localhost:8000` in `frontend/.env.local` if the API is elsewhere. Public Vite variables must never contain server credentials.

### Test on a phone over Wi-Fi

With the local backend and frontend stopped, run `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-Mobile-Preview.ps1` from the repository root. This one-command policy override does not change the machine’s execution policy. The script binds the app to this computer’s Wi-Fi address, points the event QR code and browser API requests to that address, and allows that page as an API origin. Connect the phone to the same Wi-Fi, open the printed admin URL on the computer, go to Settings, and scan the event QR code with the phone. On `/connect/card`, **Take Photo** opens the phone’s rear camera; **Upload Image** opens the photo library. If Windows asks, allow private-network access for Python and Node. If the phone cannot connect, an administrator must allow inbound TCP ports 5173 and 8000 from the local subnet in Windows Firewall. This local preview is for a trusted LAN and does not provide public access or production HTTPS.

### 3. Local admin review

Open `http://localhost:5173/admin/login` and enter one of the five addresses in `ADMIN_EMAIL_ALLOWLIST`. The email-only shortcut works only in local development and does not prove who owns that mailbox; use it only on this trusted local machine. Other email addresses are rejected. Initial admins are `bharat@latentsig.com` and `bhoomika@latentsig.com`. Grant another team member admin access with `python -m app.cli grant-admin name@latentsig.com`.

No Docker, PostgreSQL, or Redis service is needed for the local review. The local defaults use SQLite and an in-process development rate limiter. PostgreSQL and Redis remain optional deployment choices; production mode requires them.

## Team walkthrough

1. Visit `/connect` on a phone-sized browser and choose manual entry or business-card scanning.
2. For manual entry, choose the email type if needed, select a phone country, complete the required fields, choose one or more interests and an intent, then submit. Selecting **Other** under interests or discussion opens its own required five-word explanation. The optional “How did you feel? What could we improve?” comment appears directly below those Other answers. These answers are stored separately and shown in admin lead details and exports.
3. For OCR, take or upload the front of the card, then optionally add the back. Each side can be a JPG, PNG, or WEBP image up to 10 MB. The local OCR reads both together. Check every populated field, correct anything inaccurate, then choose interests and intent before submitting. OCR never submits automatically.
4. Confirm the thank-you screen appears. API writes return a lead code and interaction ID. Repeat the same email or phone at another event to add an interaction to the existing lead.
5. Open `/admin/login`, then review the dashboard, filter/search leads, open a lead, change its status, assign a team member, and add a note.
6. Export an Excel workbook from the Leads page. The workbook contains Leads, Summary, and Export Metadata sheets.
7. Try a QR URL such as `/connect?event=bts-2026&ref=booth&utm_source=bts&utm_medium=qr&utm_campaign=bts-2026` and check the resulting interaction in admin.

Use synthetic contact information during development. Local leads, card images, and test records live on the machine and are not automatically removed.

## Tests and checks

For Docker Compose and production configuration, see [DEPLOYMENT.md](DEPLOYMENT.md). CI runs frontend static checks, unit tests and build, plus backend lint, API tests and Alembic checks.

### Current responsive and E2E verification

Last local verification: **September 30, 2026**. The complete Playwright suite passed **10/10**, backend API tests passed **15/15**, frontend unit tests passed **7/7**, and frontend lint and production build passed.

The responsive E2E sweep checked the public capture form and admin leads page at viewport widths of **320, 390, 430, 768, 1024, 1366, and 1920 CSS pixels**. It verified that neither page creates document-level horizontal overflow at those sizes. It also submitted a lead and opened admin review in these mobile profiles:

- **Pixel 10** using Playwright's Pixel 10 profile.
- **iPhone 17** using Playwright's iPhone 17 viewport profile.
- **iPhone 18-size** using the iPhone 17 viewport as an approximation because Playwright does not provide an iPhone 18 profile in this project.

All browser E2E runs use the installed **Chromium** engine. The iPhone profiles therefore test mobile layout and touch emulation in Chromium; they do not test iOS Safari/WebKit. These checks are emulations, not tests on physical phones. Camera capture is tested through the browser file-capture input and review flow, not through a connected phone camera sensor. Test leads are written to the configured local database and are retained until manually removed.

### Run frontend checks

From PowerShell, the `.cmd` suffix avoids PowerShell execution-policy blocks on `npm.ps1`:

```powershell
cd frontend
npm.cmd run lint
npm.cmd run test
npm.cmd run build
npm.cmd run test:e2e
```

Playwright starts the Vite development server when needed and reuses an existing server on port 5173. Install Chromium once if it is missing:

```powershell
cd frontend
npx.cmd playwright install chromium
```

### Run backend checks

```powershell
cd backend
python -m unittest discover -s tests -v
python -m compileall -q app tests
python -m alembic upgrade head
```

The browser tests submit synthetic leads to the configured local API and leave those test leads in the local database. A manual OCR smoke check can upload one or two local images as repeated `files` fields to `POST /api/v1/ocr/business-card`; the response contains per-side opaque short-lived review tokens and extracted candidates. OCR works best with a clear, well-lit card image; the visitor must verify its results.

## Configuration

Copy `backend/.env.example` to `backend/.env`; keep it server-side. Important values:

| Variable | Purpose |
| --- | --- |
| `APP_ENV`, `APP_SECRET` | Environment and signed-session key. Use a unique 32+ character secret in production. |
| `DATABASE_URL` | SQLite locally or managed PostgreSQL. |
| `FRONTEND_URL`, `FRONTEND_URLS` | Frontend URL and CORS allowlist. |
| `DEFAULT_EVENT_SLUG` | Event used when a QR link omits `event`. |
| `DEFAULT_PHONE_REGION` | Fallback region for phone values with no international calling code. |
| `ADMIN_EMAIL_ALLOWLIST`, `INITIAL_ADMIN_EMAILS` | Local team email list and initial admin role assignment. Email-only access works only in development. |
| `REDIS_URL` | Distributed rate-limit storage; required in production. |
| `LEAD_RATE_LIMIT_COUNT`, `LEAD_RATE_LIMIT_WINDOW_SECONDS` | Public lead submission limits. |
| `OCR_RATE_LIMIT_COUNT`, `OCR_RATE_LIMIT_WINDOW_SECONDS` | OCR request limits. |
| `AUTH_RATE_LIMIT_COUNT`, `AUTH_RATE_LIMIT_WINDOW_SECONDS` | Admin login attempt limit. |
| `MAX_UPLOAD_BYTES` | Business-card upload maximum; defaults to 10 MiB. |
| `PRIVATE_STORAGE_DIR`, `STORAGE_PROVIDER` | Private local storage or S3-compatible storage. |
| `STORAGE_BUCKET`, `STORAGE_ENDPOINT`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY` | S3-compatible storage credentials and target. |
| `BUSINESS_CARD_RETENTION_DAYS` | Retention period used by the manual cleanup command; schedule it with Windows Task Scheduler or cron if recurring cleanup is wanted. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` or `GOOGLE_SERVICE_ACCOUNT_EMAIL` + `GOOGLE_PRIVATE_KEY`, `GOOGLE_SHEET_ID`, `GOOGLE_SHEET_TAB` | Server-side Google Sheets integration. Share the sheet with the service account. |
| `WHATSAPP_NUMBER` | LatentSig WhatsApp destination, digits only with country code. |

Frontend values in `frontend/.env.local`:

```dotenv
VITE_API_BASE_URL=http://localhost:8000
VITE_APP_NAME=LatentSig Connect
VITE_PUBLIC_SITE_URL=http://localhost:5173
VITE_WHATSAPP_NUMBER=
```

`VITE_WHATSAPP_NUMBER` is optional; the visitor explicitly clicks the WhatsApp link and sends the prefilled message. Never place `DATABASE_URL`, Google service-account keys, or storage credentials in a `VITE_` variable.

## API overview

| Method | Endpoint | Use |
| --- | --- | --- |
| `GET` | `/health` | Process health check. |
| `POST` | `/api/v1/leads` | Validate, deduplicate, and persist a lead and interaction. |
| `POST` | `/api/v1/ocr/business-card` | Local OCR of one front image plus an optional back image; returns candidates and short-lived per-side tokens. Send repeated `files` multipart fields in front-then-back order. |
| `POST` | `/api/v1/auth/email-login` | Local-only sign-in for an allowlisted email. |
| `GET` | `/api/v1/auth/me` | Return the signed-in admin profile. |
| `POST` | `/api/v1/auth/logout` | End the admin session. |
| `POST` | `/api/v1/auth/dev-login` | Allowlisted local-only login when `APP_ENV=development`. |
| `GET` | `/api/v1/admin/dashboard` | Lead totals and breakdowns. |
| `GET` | `/api/v1/admin/leads` | Search, filter, and page leads. |
| `GET/PATCH/DELETE` | `/api/v1/admin/leads/{id}` | View and manage lead records (delete is ADMIN-only). |
| `POST` | `/api/v1/admin/leads/{id}/notes` | Add a private internal note. |
| `GET` | `/api/v1/admin/leads/{id}/business-card` | Authenticated private card image; `side=front` by default or `side=back`. |
| `GET/PATCH` | `/api/v1/admin/team`, `/api/v1/admin/team/{id}` | List and update team members. |
| `GET/POST/PATCH` | `/api/v1/admin/events` | List/create events and update event details or activation. |
| `GET` | `/api/v1/admin/settings` | Show integration configuration state, never secrets. |
| `GET` | `/api/v1/admin/exports/leads.xlsx` | Admin/manager Excel workbook with supported query filters. |

Lead submissions require `full_name`, `company`, `job_title`, `email`, `phone`, at least one `interest`, and `intent`. Optional visitor fields include `website` and `requirement_message`. Business-card submissions include the front `business_card_token` and, when uploaded, `business_card_back_token`; the server validates each token and stores both images privately on the same card record and interaction.

## Data and privacy

- The configured SQL database is the source of truth. `leads` hold deduplicated contacts; `interactions` retain each event/source/intent/status encounter. Tables also cover users, events, business cards, notes, audit logs, and integration jobs.
- Email is normalized to lowercase. Phone values are validated with `phonenumbers`, stored in E.164 form, and associated with an ISO country code when identifiable.
- Front and optional back images are validated by declared MIME type and actual bytes, decoded with EXIF orientation correction, resized when large, and staged in private storage. OCR runs locally in the backend. Per-side review tokens expire after 30 minutes; retained card images are never served publicly and admin image retrieval is authenticated.
- Public form and OCR endpoints use configurable rate limits. Redis is used when configured; local development can fall back to process memory.
- Admin sessions are signed and HttpOnly, local email-only sign-in is disabled outside development, CORS uses an explicit origin allowlist, and API role checks are enforced.
- The email-only sign-in is intentionally local-development-only and is not an identity check. Do not expose it on a shared or production deployment.

For a one-off local retention cleanup, run `cd backend; python -m app.services.storage.retention`. It deletes expired image files while retaining their database and audit records. Recurring cleanup is optional and can be scheduled using the team OS scheduler.

## Google Sheets and Excel

When `GOOGLE_SHEET_ID` and server-side service-account credentials are configured, each committed interaction creates a pending integration job. Run a worker in a separate backend process:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.services.integrations.worker
```

The worker retries failures with increasing delay and marks exhausted jobs failed. A Sheets outage does not undo a lead submission. Excel exports are generated on the backend with openpyxl, include summary/metadata sheets, honor supported event/date/status/interest/capture/assignment filters, and sanitize formula-leading cell values.

## Deployment notes

Local review uses SQLite and needs no containers. A PostgreSQL/Redis container stack is available through Docker Compose; see [DEPLOYMENT.md](DEPLOYMENT.md). The local email-only sign-in is disabled outside development; choose a verified identity provider before exposing admin access to a shared deployment.

## Repository map

```text
frontend/src/App.tsx                     Public capture flow and routes
frontend/src/Admin.tsx                   Admin pages and lead workflows
frontend/src/styles.css                  Public responsive design system
frontend/src/admin.css                   Admin desktop/mobile layouts
frontend/e2e/public-flow.spec.ts          Chromium end-to-end flows
backend/app/api/v1/routes/                Public, auth, admin, OCR, export APIs
backend/app/services/ocr/                 Local preprocessing, PaddleOCR, parser
backend/app/services/leads/               Dedupe and capture workflow
backend/app/services/storage/             Private local/S3 card storage
backend/app/services/integrations/        Google Sheets worker
backend/app/db/models.py                  SQLAlchemy schema
backend/alembic/                          Database migrations
LatentSig_Event_Lead_Capture_Full_Plan.md Product source plan
```
