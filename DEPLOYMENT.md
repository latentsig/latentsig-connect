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

## GCP Compute Engine

The GCP deployment runs the existing production Compose stack on one Ubuntu 24.04 VM. This keeps PostgreSQL, Redis, local card storage, the integration worker, and Nginx together. Deployments can briefly interrupt requests, and backup snapshots pause application writes while capturing the database and card files. A VM failure requires recovery. Cloud Run would require separate PostgreSQL and Redis services, object storage for cards, and a different worker and certificate setup.

The initial public HTTPS hostname is `latentsig-connect.34.93.221.72.sslip.io`. It resolves to the reserved VM address while custom DNS for `connect.latentsig.com` is pending. The custom domain remains the intended permanent origin.

The deployment uses these dedicated resources:

| Resource | Value |
| --- | --- |
| Project | `refined-outlet-249712` |
| VM and VPC | `latentsig-connect` |
| Zone and machine | `asia-south1-b`, `e2-standard-2` |
| Subnet | `latentsig-connect-mumbai`, `10.42.0.0/24` |
| Reserved public IP | `34.93.221.72` |
| Persistent data disk | `latentsig-connect-data`, 40 GB, balanced persistent disk |
| Backup bucket | `refined-outlet-249712-latentsig-connect-backups` |
| VM identity | `latentsig-connect@refined-outlet-249712.iam.gserviceaccount.com` |

Only TCP 80 and 443 are public. SSH uses Identity-Aware Proxy, with TCP 22 restricted to `35.235.240.0/20`. Operators need GCP permissions for IAP tunneling and VM SSH. The VM identity has access only to the dedicated backup bucket through its bucket-level `roles/storage.objectUser` grant. The bucket uses uniform bucket-level access and public access prevention. No service-account key file is installed.

The data disk must be attached with device name `latentsig-connect-data` and automatic deletion disabled. `bootstrap.sh` mounts it at `/srv/latentsig-connect` and sets Docker's data directory to `/srv/latentsig-connect/docker`. By default it formats only an entirely zeroed disk with no filesystem signature or partitions. The zero scan can take several minutes. Use `--new-disk` only immediately after creating a new blank GCP disk, when the provisioning operation establishes that it contains no data. This flag skips the full zero scan but still rejects signatures and partitions. Existing ext4 filesystems are preserved. A missing disk prevents Docker from starting after reboot. Source files live in `/opt/latentsig-connect`.

### Bootstrap and deploy

Create an archive of the checked-in source, then copy it and the bootstrap script over IAP. Commit intended changes before using `git archive`, since it excludes uncommitted changes. It also avoids macOS filesystem metadata. If packaging a working tree with macOS `tar`, use `COPYFILE_DISABLE=1 tar ...` and exclude `._*` and `__MACOSX` entries. The deploy extractor omits those metadata entries after validating archive paths, and the backend build context excludes them too:

```sh
git archive --format=tar.gz -o /tmp/latentsig-connect-source.tar.gz HEAD
gcloud compute scp deploy/gcp/bootstrap.sh /tmp/latentsig-connect-source.tar.gz latentsig-connect:/tmp/ --tunnel-through-iap --zone=asia-south1-b --project=refined-outlet-249712
gcloud compute ssh latentsig-connect --tunnel-through-iap --zone=asia-south1-b --project=refined-outlet-249712
```

On the VM:

```sh
sudo bash /tmp/bootstrap.sh
mkdir -p /tmp/latentsig-connect-deployer
tar -xzf /tmp/latentsig-connect-source.tar.gz -C /tmp/latentsig-connect-deployer deploy/gcp
sudo bash /tmp/latentsig-connect-deployer/deploy/gcp/deploy.sh /tmp/latentsig-connect-source.tar.gz latentsig-connect.34.93.221.72.sslip.io refined-outlet-249712-latentsig-connect-backups
```

For the first bootstrap of a just-created blank GCP disk, replace the first command with `sudo bash /tmp/bootstrap.sh --new-disk`. Run the default command on later bootstraps or disks whose history is unknown.

The deploy script validates the source archive, preserves `.env`, builds the existing production profile, waits for healthy containers, and installs daily systemd timers. It generates unique application and database secrets only on the first deployment. The environment file is `/srv/latentsig-connect/secrets/production.env`, owned by root with mode `0600`. The repository `.env` is a symlink to it. It contains the full explicit allowlist from `backend/.env.example`, with Bharat and Bhoomika as initial admins. OCR remains disabled until an operator securely configures an OpenRouter key.

Each initial admin receives a different generated password only when the account has no password. The CLI receives passwords through standard input, and its output is captured. Existing passwords survive redeployments. Bootstrap credentials are stored in `/srv/latentsig-connect/secrets/admin-passwords.json` with mode `0600`. Retrieve them through a private operator session or password manager. Do not paste them into logs, source control, tickets, or chat. A password changed later through the CLI does not update this bootstrap file.

Repeat the archive transfer and deploy command for subsequent releases. Use `sudoedit /srv/latentsig-connect/secrets/production.env` for runtime configuration, then redeploy. Use the explicit `runtime.py domain NEW_DOMAIN` command to change `PUBLIC_DOMAIN`, both frontend URL settings, and `GOOGLE_REDIRECT_URI` together. It preserves all other environment bytes and admin credentials and keeps the environment file at mode `0600`. Normal deployment refuses a mismatched domain. The frontend rebuild embeds the public origin in QR links. Do not delete Docker volumes or regenerate database credentials during a redeployment.

### Enable HTTPS and verify

The temporary hostname already resolves to `34.93.221.72`. Until a certificate is issued, Nginx returns its certificate bootstrap response and the app is not publicly usable. The issuance command checks that DNS resolves only to the VM's public IP:

```sh
sudo bash /opt/latentsig-connect/deploy/gcp/operations.sh issue-tls
sudo python3 /opt/latentsig-connect/deploy/gcp/smoke.py https://latentsig-connect.34.93.221.72.sslip.io
```

The smoke script checks HTTPS, public readiness, visitor and login pages, disabled development login, rejected unauthenticated admin access, secure session cookies, and a password-authenticated dashboard. It reads the private bootstrap credential file and never prints credentials or lead records. Its default flow does not create or change leads. Use `--public-only` when running from another machine without credentials.

Before DNS is ready, run the same application checks through the VM's loopback frontend:

```sh
sudo python3 /opt/latentsig-connect/deploy/gcp/smoke.py http://127.0.0.1:8080 --local --expected-public-origin https://latentsig-connect.34.93.221.72.sslip.io --synthetic
```

The explicit local mode accepts only `127.0.0.1:8080`. It checks that production cookies still have the Secure attribute, then sends the cookie manually to that loopback listener. Production configuration remains HTTPS. The origin check searches the built frontend JavaScript for the configured QR origin. The optional synthetic flow submits one reserved test phone number and `example.com` address, repeats the request with the same idempotency key, reads the resulting lead, and deletes it in a cleanup step.

To promote the permanent domain, set its A record to `34.93.221.72` and remove conflicting A or AAAA records. Wait for DNS to resolve correctly and for any current deployment or backup to finish. Transfer the new source archive, then run on the VM:

```sh
sudo python3 /opt/latentsig-connect/deploy/gcp/runtime.py domain connect.latentsig.com
sudo bash /opt/latentsig-connect/deploy/gcp/deploy.sh /tmp/latentsig-connect-source.tar.gz connect.latentsig.com refined-outlet-249712-latentsig-connect-backups
sudo bash /opt/latentsig-connect/deploy/gcp/operations.sh issue-tls
sudo python3 /opt/latentsig-connect/deploy/gcp/smoke.py https://connect.latentsig.com --expected-public-origin https://connect.latentsig.com
```

The domain command only updates the protected environment file. Rebuilding and issuing the new certificate complete the change. Previously shared temporary links and QR codes retain their old hostname, so distribute fresh links and QR codes after promotion.

### Backups and daily tasks

Daily timers renew TLS, purge card images after the application's default 90-day retention period, and upload a recovery snapshot. The local Compose database backup service continues its daily verified dumps with 14-day retention. The external snapshot includes a PostgreSQL dump, private card files, TLS state, and deployment secrets. It pauses the backend and integration worker for the dump and card copy, then restarts them. Each external dump is restored into a disposable database, its user and lead counts are compared with the captured source counts, and the disposable database is dropped before compression and upload. The uploader compares GCS's returned MD5 and size with the local archive. Snapshot files and credentials remain root-only on the VM and private in the bucket. GCS encrypts stored objects.

Apply the 30-day snapshot lifecycle from an authenticated operator machine:

```sh
gcloud storage buckets update gs://refined-outlet-249712-latentsig-connect-backups --lifecycle-file=deploy/gcp/bucket-lifecycle.json
```

Run and inspect the first backup on the VM:

```sh
sudo systemctl start latentsig-connect-backup.service
sudo journalctl -u latentsig-connect-backup.service --no-pager -n 30
systemctl list-timers 'latentsig-connect-*'
```

Inspect failed services with `systemctl --failed` and `journalctl -u latentsig-connect-backup.service`. The checked-in Prometheus alerts still need an external alert receiver. Timer failures need external monitoring too.

Test recovery on an isolated VM before relying on the backups. An authenticated operator can download a matching `.tar.gz` and `.sha256` pair from `snapshots/` in the bucket. Rename the archive to `snapshot.tar.gz`, then run `sha256sum -c` against the downloaded checksum file. Treat the extracted snapshot as secret material. Restore the environment before starting a new PostgreSQL volume, so its password matches the application configuration. Restore `database.dump` with PostgreSQL 16 `pg_restore`, copy card files into the `latentsig-connect_private_cards` volume, and restore TLS state into `latentsig-connect_letsencrypt`. Keep the backend and integration worker stopped during recovery. Verify readiness, admin login, and a known synthetic card on the isolated VM. Record recovery duration and the newest recovered timestamp. Do not point production DNS at a restore until those checks pass.

## CI

GitHub Actions runs TypeScript checks, Vitest, the frontend production build, Ruff, pytest, Alembic migration/schema checks, and production Compose configuration validation. Browser end-to-end tests are run locally with the API and OCR dependencies available:

```powershell
cd frontend
npm run test:e2e
```
