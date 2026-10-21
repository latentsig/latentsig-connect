# Deployment flow

```mermaid
flowchart LR
  Browser[Visitor / staff browser] -->|HTTP 80 / HTTPS 443| Proxy[Nginx edge proxy + TLS]
  Proxy -->|app routes| Frontend[React PWA container]
  Proxy -->|/api and health| API[FastAPI]
  Certbot[Certbot ACME client] -->|HTTP-01 challenge| Proxy
  Certbot --> Certs[(Let's Encrypt certificates)]
  Proxy --> Certs
  API --> PG[(PostgreSQL)]
  API --> Redis[(Redis rate limits)]
  API --> Cards[Private image storage]
  API --> OR[OpenRouter]
  API --> Jobs[(Integration outbox)]
  Worker[Sheets worker] --> Jobs
  Worker --> Sheets[Google Sheets]
  PG --> Backup[Verified backup job]
  API --> Monitor[Health / metrics]
```

Keep provider keys, database credentials, session secrets, and service-account material in the deployment secret store or ignored root `.env`. Only serve the visitor flow over HTTPS so mobile browser camera capture can work.

The Compose `production` profile publishes only Nginx. PostgreSQL and Redis remain private to the Compose network; the frontend's `8080` port binds to loopback for local review. Before certificate issuance, Nginx serves only ACME challenge files over HTTP and returns a temporary 503 for other paths. After issuance it redirects HTTP to HTTPS and loads the TLS virtual host.
