# Event day runbook

## Before doors open

1. Deploy the HTTPS site and verify `/health/live` and `/health/ready`.
2. Confirm the active event slug and event dates in Admin → Settings. Generate the booth QR with that event slug and a source tag such as `ref=booth`.
3. Confirm the backend has `OPENROUTER_API_KEY`, `OCR_ENABLED=true`, the selected model, and suitable rate limits. Never put provider credentials in Vite variables or QR URLs.
4. Perform a synthetic card scan and manually correct the returned fields. Confirm the submitted lead appears in the admin workspace.
5. Confirm Google Sheets reports a recent row and the worker is running. Keep manual registration available if the provider or network fails.
6. Verify private card images open only for authorized staff. Confirm database backup status and an external copy.
7. Test the PWA install and the camera flow on a real iPhone/Safari and Android/Chrome over HTTPS.

## During the event

- Keep a staff admin session open on a trusted device and monitor the lead queue, Sheets failures, and API health.
- If AI scanning fails, ask the visitor to retry once or use **Enter Details Manually**. Do not ask staff to bypass the consent checkbox.
- If Sheets sync is delayed, continue capturing leads; the database remains authoritative and the worker retries queued jobs.
- If API or database health fails, pause the QR capture and record the incident. Do not collect business cards outside the approved retention workflow.

## After the event

- Export a filtered Excel workbook for the event and verify its row count.
- Review sync failures and retry them before closing the event.
- Confirm backup completion, preserve the approved retention schedule, and revoke temporary event access.
