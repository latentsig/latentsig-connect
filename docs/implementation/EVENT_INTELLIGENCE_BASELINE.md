# Event Intelligence Workspace Baseline

Audit date: 2026-11-16

## Repository and release boundary

- Branch: main
- Local and origin/main HEAD at audit start: 95579b61c2dbfcfc1f1383479df48ef4cb47259a
- Working tree at audit start: clean
- The last authenticated branch-rule review recorded main as protected with required deployment-config, frontend, and backend checks, and zero required approving reviews. A fresh read-only GitHub API request returned 401 in this workspace, so those settings could not be independently refreshed during this audit. No branch rules were changed.
- The deployed application revision is not identifiable from the available health endpoints. No production change is part of this implementation task.

## Existing application

### Data and APIs

- FastAPI, SQLAlchemy, Alembic, SQLite local mode, PostgreSQL production mode.
- Events have dates, location, venue, profile reference, and active state. Event profiles, sessions, staff assignments, QR attribution, and event dashboards already have APIs.
- BTS 2026 already exists as bts-2026, dated 2026-11-17 through 2026-11-19, location Bengaluru. Its venue field is empty. The official summit site confirms Bangalore International Exhibition Centre (BIEC) as the venue: [STPI event listing](https://bengaluru.stpi.in/en/events/bengaluru-tech-summit-2026-0).
- The local isolated review database contains one imported workbook with 4,226 source rows across six worksheets: Registrants (2,560), Strong shortlist (270), Design Partners (221), Clients-Strong (205), Competitors (683), and CSE Research (287). There are 2,560 distinct Profile IDs in the Registrants sheet. The original XLSM remains in private local storage with a checksum matching the source file.
- ResearchImportRow preserves worksheet rows and original cell values. EventRegistrant is one row per source worksheet record; matching helpers group rows by Profile ID, or by source key when no Profile ID exists.
- Import preview, confirmation, checksum-based history, private original-file download, and rollback exist. Worksheet names are stored dynamically. Five Strong-shortlist rows lack Profile IDs; one additional Strong-shortlist row lacks a company. The importer flags these and the other workbook warnings.
- Card capture, OCR failure recovery, private storage, event attribution, synthetic-test flags, lead matching, lead meetings, and consent controls already exist.

### UI

- Admin routes include Events, event workspace, Research, Card Capture, Leads, and lead detail.
- Research currently uses one generic row table and a worksheet dropdown. The original columns are hidden in an inline details disclosure. It does not yet offer separate visible worksheet tabs, useful per-sheet column sets, unified attendee search, a person profile view, column controls, or research export.
- Event workspaces expose overview metrics, sessions, staff, QR links, imports, meetings, and follow-ups in sections, rather than the planned event-local tab navigation.
- At baseline, card capture required review before a lead was saved and had no quick manual staff-capture flow or status-specific inbox navigation.

## Implementation progress — local review only

Implementation started from the audited `main` checkout at `95579b61c2dbfcfc1f1383479df48ef4cb47259a` and is published on the existing `Event-Workspace` branch at `de3cee9`. The API and frontend preview are available at [http://localhost:5173/admin/research](http://localhost:5173/admin/research). No production or GCP services were changed.

### Implemented in this slice

- Research tabs are generated from the latest imported workbook and show worksheet row counts. Registrants is labeled “All registrants.” Search, filters, sort order, and pagination are kept separately per worksheet.
- Sheet tables select visible columns from headers actually present in that worksheet. Users can change visible columns, inspect every original cell in a profile, and download a CSV export. CSV cells beginning with spreadsheet formula characters are escaped.
- Global search returns one attendee result per stable Profile ID, or per source key if the ID is absent. Same-name rows with different IDs remain separate. The profile view contains all source memberships and values.
- Dashboard “unmatched visitors” no longer counts unmatched imported registrants. Its sources are event-scoped real manual/business-card lead interactions without a matched research record, plus unresolved non-synthetic card captures with no lead.
- Added an additive `event_encounters` table and event-scoped list/create APIs. Authorized event staff can mark a research attendee met, record a demo, or schedule/confirm a meeting without creating a lead or consent record. A later research-to-lead match links the saved encounters to that lead.
- Added Quick Manual Capture for staff who receive visitor details without a business card. It requires event attribution, supports a session and notes, saves incomplete records as pending review, and leaves consent blank. Exact contact matches can link to an existing lead, while ambiguous matches require staff selection or an explicit distinct-person confirmation. New data only fills empty lead fields.
- Dashboard counts now distinguish registered research identities, captured submissions, quick manual captures, card captures, people with recorded staff interactions, and meetings. Synthetic captures are excluded.
- Event workspaces now show four action panels: Must Meet Next, Research Opportunities, Follow-up Today, and Needs Review. A/B priorities come only from exact source values in the latest imported workbook, are grouped by stable identity, and are suppressed after a completed staff encounter. Must Meet Next reports both full A and B totals even when its visible list is paginated. The research worksheet view can filter by exact A or B source priority.
- Follow-up panels combine open lead meetings and research-attendee meeting encounters. Review panels link reconciliation rows and pending card captures to their review screens.
- Added event-local navigation for Overview, Attendees, Research, Card Captures, Meetings, Follow-ups, Days & Sessions, and Imports & Reports. Attendees opens global identity search; Imports & Reports opens import history. The event workspace meeting tracker combines lead and research-attendee meetings, keeps each research meeting attached to its profile, and supports status and owner controls.
- Added a card-capture inbox with event/status filters, a last-24-hours view, pagination, authenticated private thumbnails, capture time/staff details, and state-specific review actions. Status filters group template identity checks with pending review; synthetic rows remain opt-in.
- Import fallback keys now use a normalized worksheet token and row-content fingerprint with a duplicate occurrence suffix when the workbook has no stable row identifier. Reordering rows no longer changes those keys. During upgrade from existing row-number keys, a unique Profile ID plus worksheet match (or unique anonymous row-content match) reuses the existing record in place. Import rollback restores the prior source key and row data; independent staff encounters and notes remain intact.
- Import preview and history now include an Import Quality summary: source SHA-256, worksheet and row counts, unique Profile IDs in the Registrants sheet, Profile IDs repeated across worksheets, rows missing Profile IDs, validation warnings, import status, and rollback availability. Profile IDs are described as source identifiers because this flow does not independently verify them.

### Metric definitions

| Metric | Source and filtering |
|---|---|
| Unique registrants | Distinct `EventRegistrant` identity within the event: normalized Profile ID, otherwise source key. This is research data, not live visitors. |
| Submissions | Count of event `Interaction` rows captured by manual or business-card submission; excludes synthetic and analytics-excluded rows. |
| Unique submitted contacts | Distinct lead IDs from those event-scoped submission interactions, with the same exclusions. |
| Quick manual captures | Event `Interaction` rows whose source is `staff_quick_capture`, excluding synthetic and analytics-excluded rows. |
| Staff card captures | Event `StaffCardCapture` rows excluding synthetic and analytics-excluded records. Includes unresolved review records. |
| Staff-confirmed encounters | Non-synthetic linked card captures plus non-synthetic completed `EventEncounter` actions (met, demo, or completed meeting). A card capture is not counted as a demo. |
| People met | Distinct event identity keys from completed staff `EventEncounter` actions. |
| Confirmed meetings | Existing event `Meeting` records with confirmed/completed status plus event `EventEncounter` meeting records with confirmed/completed status. |
| Unmatched visitors | Distinct event manual/business-card interaction leads not linked to an `EventRegistrant`, plus unresolved non-synthetic card captures without a lead. Imported prospects alone do not contribute. |
| Outstanding follow-ups | Event lead-meetings and research-attendee meeting encounters with a due date and a status other than completed/cancelled; synthetic encounters excluded. |

These definitions are being expanded alongside the remaining event dashboard work; they do not yet cover day-wise or staff-wise breakdowns.

### Local priority-panel snapshot

The isolated BTS review database currently returns 56 open Must Meet targets (24 A and 32 B), 236 strong-fit client/design-partner opportunities, no due follow-ups, 9 research reconciliation rows, and no pending card captures. Counts are from explicit imported workbook fields and exclude completed Must Meet identities. This snapshot is local review data only.

The latest local BTS import-quality report shows 4,226 rows across six worksheets, 2,560 Profile IDs in Registrants, 1,109 Profile IDs repeated across multiple worksheets, 5 rows missing Profile IDs, and 9 validation warnings. The original file checksum is present and rollback is available for the imported batch. This report is derived from the isolated review database; Profile IDs remain source identifiers pending verification.

### Current validation

- Backend: 93 passed, 1 PostgreSQL-only concurrency case skipped locally, 11 subtests passed. Coverage includes repeat-import idempotency, reordered rows, legacy row-key promotion, duplicate anonymous rows, preservation of a staff encounter and note through reimport and rollback, Import Quality values in preview/history, grouped capture filters, private thumbnail authorization, and unified event-meeting results.
- Frontend unit tests: 7 passed. TypeScript check and production build passed. The latest build reports a 781.13 KB minified JavaScript chunk, above the 500 KB warning threshold.
- Ruff passed for changed backend files; `git diff --check` passed.
- Local Chrome E2E: the latest full 18-test run passed 12 and failed 6. One failure was an ambiguous `getByLabel('Event')` selector, now corrected to an exact label; five later admin-login failures hit the isolated API's default 10-attempt/5-minute authentication throttle. The capture-inbox test passes when run alone, and earlier focused runs pass event navigation/A-B/session links, attendee navigation, Import Quality, and meeting actions. Quick Manual Capture writes are intercepted in browser tests. A complete post-change suite rerun with a temporarily higher local-only auth throttle remains outstanding.
- Quick Manual Capture API tests cover incomplete fields/no consent, ambiguous research matches, and exact contact linking to a lead from another event. These use in-memory test databases.
- Alembic upgrade and `alembic check` passed against the isolated temporary review database. The API was restarted with its existing isolated database and private-storage configuration.

## Gaps against the new plan

1. The research tab/profile/search/export and A/B priority filtering slices are implemented locally. They still need full acceptance coverage against the original six-sheet workbook fixture and permission-role matrix.
2. Add independent research, identity-match, event-interaction, and sales-pipeline statuses with history.
3. Single-attendee staff encounters and later lead linkage are implemented locally. Event meetings now combine lead and research-attendee records; shared group encounters remain outstanding.
4. The unmatched-visitors metric now excludes imported research-only rows; day/session breakdowns, staff-wise activity, and further analytics reconciliation remain.
5. Event-local navigation, unified meeting tracking, follow-up and priority panels are implemented locally. Day/session operations and accurate staff/day metrics remain.
6. Quick manual capture and status-specific card-inbox filters are implemented locally. Group encounters remain outstanding.
7. Import row reordering and the unique legacy row-key upgrade path are covered locally. More cases are needed for ambiguous identity corrections, interleaved concurrent imports, rollback order across multiple versions, and broader formula-injection and permission tests.
8. The full AT-01–AT-24 acceptance matrix, physical-device checks, realistic latency measurements, backup-restore verification, and authorized production smoke have not all been completed.

## Test and operational baseline

- At audit start, the backend suite had 83 passed, 1 PostgreSQL-only concurrency case skipped locally, and 11 subtests passed. Earlier implementation checkpoints reported 86, 90, and 91 passing tests; the current suite has 92 passed, 1 skipped, and 11 subtests passed.
- Frontend unit suite: 7 passed; TypeScript check and production build passed. The latest build reports a 776.60 KB JavaScript chunk, above the 500 KB warning threshold.
- Ruff passed; deployment archive tests passed (23 tests); a fresh SQLite migration upgrade and alembic check passed.
- Local browser checks for the earlier baseline included Research, QR choice, card review/template guard, Android camera emulation, and Other form flows. This slice adds passing Chrome checks for research tabs/search, responsive layout, research meeting actions, and template-card safeguards. The local backend uses an isolated temporary SQLite database.
- Docker Desktop is unavailable locally. PostgreSQL concurrency and mobile Safari therefore require the configured CI services; physical device checks remain outstanding.
- The GCP workflow has a verified-backup step before deploy, but its most recent attempted run stopped at configuration preflight before authentication or backup. No production backup, deployment, migration, or synthetic card smoke was performed. The previous read-only production probe found an expired TLS certificate. Restore readiness and current deployed version remain unverified.

## Release blockers and safety

- Do not deploy until the production environment variables, TLS, backup/restore, migration compatibility, OCR provider, and approval gate are verified.
- Do not convert imported registrants into leads or infer consent.
- Venue and dates are verified from the official event listing; setting an event venue in the local review database does not deploy or alter production.
- Production data, storage, DNS, and branch protection have not been modified.
