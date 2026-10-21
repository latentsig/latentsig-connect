# Gap Analysis

| Priority | Gap | Action / release condition |
| --- | --- | --- |
| P0 | Production domain approval, VPS, DNS, TLS issuance, and backup restore are still external | Deploy the prepared `connect.latentsig.com` Nginx/Compose configuration after infrastructure and DNS approval; demonstrate health checks and a restore before public launch |
| P1 | OpenRouter model/account compatibility is not live-verified (the model listing documents image and structured-output support) | Run a synthetic-card smoke test with an approved account and record latency and output quality |
| P1 | Password recovery/federated identity and Google credentials are external | Operators can provision/reset passwords with the CLI; add an approved identity provider if required and configure a least-privilege Sheets service account |
| P1 | Consent notice and retention period need event owner/legal review | Approve notice wording, legal basis, access, retention, and deletion policy before public launch |
| P1 | AI structured output may vary by selected model/provider support | Keep response validation and manual fallback; verify with the configured model |
| P2 | Current real-device camera/Safari verification is unavailable | Follow the event-day runbook on supported physical devices and browsers |
| P2 | Concurrent duplicate submission and live Sheets retry recovery have not been exercised under production-like load | Stress-test concurrent retries and exercise worker recovery before launch |
| P2 | Browser dependencies were unavailable, so the updated React flow was not type-checked or browser-tested | Restore/install frontend dependencies and run lint, unit tests, build, and Playwright suite |
