# Contributing

Use a short branch for each change and open a pull request against `main`. The CI workflow runs for every branch push and every pull request. It checks deployment configuration, frontend code, and backend code. A maintainer can also start it with the Actions `workflow_dispatch` control.

GitHub may hold a workflow from a first-time contributor until a repository maintainer approves it. CI uses no cloud credentials and does not deploy or publish anything. GCP deployment remains a manual operation.

## Run checks locally

Use Python 3.11 and Node.js 22. Start the local PostgreSQL and Redis services before running backend migrations or tests.

For deployment configuration, run these commands from the repository root:

```sh
docker compose --profile production --profile certificates config --quiet
for script in scripts/backup-postgres.sh scripts/issue-tls-certificate.sh scripts/renew-tls-certificate.sh deploy/nginx/select-config.sh; do
  sh -n "$script" || exit
done
for script in deploy/gcp/*.sh; do
  bash -n "$script" || exit
done
python -m compileall -q deploy/gcp
python deploy/gcp/test_deploy_archive.py
docker build -t latentsig-nginx-config ./deploy/nginx
docker run --rm -e PUBLIC_DOMAIN=connect.latentsig.com latentsig-nginx-config nginx -t
```

The workflow also checks the Nginx configuration with a temporary TLS certificate.

For frontend checks:

```sh
cd frontend
npm ci
npm run lint
npm test
npm run build
```

For backend checks:

```sh
cd backend
python -m pip install -r requirements-dev.txt
ruff check app tests ../deploy/gcp
DATABASE_URL=postgresql+psycopg://latentsig:ci-password@localhost:5432/latentsig alembic upgrade head
APP_ENV=development DATABASE_URL=postgresql+psycopg://latentsig:ci-password@localhost:5432/latentsig REDIS_URL=redis://localhost:6379/0 python -m pytest -q
DATABASE_URL=postgresql+psycopg://latentsig:ci-password@localhost:5432/latentsig alembic check
```

The database URL above assumes the CI PostgreSQL credentials. Change the URL to match your local database.

## Require CI before merging

Repository administrators configure required status checks under branch protection or a ruleset for `main`. Select the `deployment-config`, `frontend`, and `backend` job checks after the workflow has run once. The workflow runs those jobs, but repository rules decide whether GitHub blocks a merge until they pass.
