# Deployment

## Local container stack

Docker Compose starts PostgreSQL, Redis, the FastAPI API, the Google Sheets integration worker, daily verified database backups, Prometheus monitoring, and the Nginx-served React app:

```powershell
docker compose up --build
```

Open `http://localhost:8080/connect` or `http://localhost:8080/admin/login`. Development email sign-in is enabled in this local Compose configuration. Prometheus runs at `http://localhost:9090`; API live/readiness checks are `/health/live` and `/health/ready`. The database, private business-card files, backup archives, and monitoring data persist in named volumes. Use synthetic data for local development.

The Compose defaults are for local review only. To create production secrets and set the first admin email, run `./scripts/Initialize-Production.ps1 -PublicUrl https://your-domain.example -AdminEmail you@example.com`. It writes an ignored root `.env` containing random application and database secrets. Review it before deployment. Password login works without Google OAuth. Sheets sync remains optional and inactive until its service-account credentials and sheet ID are configured.

## Production

Run behind a TLS-terminating reverse proxy or load balancer. Generate the environment file as above, then start the stack. After migrations complete, provision each team password with `docker compose exec backend python -m app.cli set-password you@example.com`. The API requires PostgreSQL, Redis, HTTPS frontend origins, a unique app secret, and explicit admin allowlists. Google OAuth and Sheets are optional. Keep `.env` and service-account material out of source control.

The Compose stack takes a verified `pg_dump` archive immediately and then daily, retaining 14 days in the `database_backups` volume. Prometheus scrapes the API every 15 seconds and evaluates availability and server-error alerts. These local services need an external copy of backups and an alert receiver for production operations; test a restore before relying on the backups.

For the current SQLite development database, create and verify a local snapshot with `cd backend; python -m app.services.backup`. PostgreSQL snapshots run automatically in the Compose stack.

## CI

GitHub Actions runs TypeScript checks, Vitest, the frontend production build, Ruff, pytest, and Alembic migration/schema checks. Browser end-to-end tests are run locally with the API and OCR dependencies available:

```powershell
cd frontend
npm run test:e2e
```
