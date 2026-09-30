# LatentSig Event Lead Capture Platform
## Full Product, UI/UX, Frontend, Backend, OCR, Database, Excel, Security & Deployment Plan

**Project type:** Event lead capture web application  
**Primary use case:** Capture leads at conferences, builder/startup events, summits, exhibitions, client meetings, and networking events  
**Frontend:** React + TypeScript  
**Backend:** Python + FastAPI  
**OCR:** Python OCR pipeline for business cards  
**Primary database:** PostgreSQL  
**Primary users:** Visitors, LatentSig sales/marketing team, admins  
**Primary devices:** Mobile phones first, desktop/tablet fully supported

---

# 1. Product Objective

Build a fast, professional lead-capture application for LatentSig.

Visitors should be able to scan a QR code and choose one of two methods:

1. **Upload / scan a business card**
2. **Enter their information manually**

The form must be extremely fast, mobile-friendly, and visually polished.

After submission:

- Lead information is saved privately.
- Business-card OCR data is reviewed before final submission.
- The lead is stored in PostgreSQL.
- Data can be synchronized to a private Google Sheet.
- Authorized LatentSig employees can view leads in an admin dashboard.
- Authorized users can download leads as `.xlsx`.
- Visitors see a professional thank-you screen.
- Visitors can optionally continue the conversation on WhatsApp.

The public website must never expose:

- Previous leads
- Other visitors
- Admin data
- Spreadsheet URLs
- Private card images
- Database credentials
- API keys

---

# 2. Primary User Flow

```text
EVENT VISITOR
    |
    | scans QR
    v
/connect
    |
    +------------------------------+
    |                              |
    v                              v
Scan Business Card          Enter Details Manually
    |                              |
    v                              v
Take/Upload Photo              Fill Short Form
    |                              |
    v                              |
Python OCR                       |
    |                              |
    v                              |
Review Extracted Data             |
    |                              |
    +---------------+--------------+
                    |
                    v
             Select Interest
                    |
                    v
                Submit
                    |
                    v
           FastAPI Backend
                    |
                    v
              PostgreSQL
                    |
          +---------+----------+
          |                    |
          v                    v
   Google Sheet           Admin Dashboard
          |                    |
          v                    v
    Excel Export          Sales Follow-up
                    |
                    v
            Thank You Screen
                    |
                    v
              WhatsApp CTA
```

---

# 3. Recommended Technology Stack

## 3.1 Frontend

### Core

- **React**
- **TypeScript**
- **Vite**
- **React Router**
- **Tailwind CSS**
- **shadcn/ui**

### Forms

- **React Hook Form**
- **Zod**
- `@hookform/resolvers`

### API / server state

- **TanStack Query**

### Icons

- **Lucide React**

### Tables

- **TanStack Table**

### Notifications

- Sonner or shadcn toast

### File upload

Use native file input plus a custom upload UI.

Optional:

- `react-dropzone`

### Phone input

Use an international phone-number component such as:

- `react-phone-number-input`

### QR

QR images can be generated with:

- `qrcode.react`

---

# 3.2 Backend

Use:

- **Python**
- **FastAPI**
- **Pydantic**
- **SQLAlchemy**
- **Alembic**
- **PostgreSQL**

Recommended server:

- `uvicorn`

Production process management:

- Uvicorn workers / Gunicorn-compatible deployment where supported

---

# 3.3 OCR Stack

Use Python for OCR.

Recommended architecture:

```text
Business card image
        |
        v
Image validation
        |
        v
OpenCV preprocessing
        |
        v
PaddleOCR
        |
        v
OCR text blocks
        |
        v
Business-card parser
        |
        v
Structured contact data
        |
        v
Confidence scoring
        |
        v
Visitor review/edit screen
```

Recommended packages:

- **OpenCV**
- **Pillow**
- **PaddleOCR**
- **NumPy**
- **phonenumbers**
- **email-validator**

Optional fallback:

- EasyOCR

Recommended primary engine:

**PaddleOCR**

Reason:

- Python-native workflow
- Good OCR accuracy
- Suitable for business cards
- Works locally
- Can support rotated text
- Avoids making OCR dependent on a third-party API

Do not automatically trust OCR output.

Always show extracted values to the visitor before final submission.

---

# 3.4 Database

Recommended:

- PostgreSQL

Possible hosting:

- Supabase PostgreSQL
- Neon PostgreSQL
- Managed PostgreSQL on your preferred cloud

For this project, **Supabase PostgreSQL** is convenient because it can also provide:

- Database
- Private object storage
- Authentication support if required
- Backups

The backend should still own business logic.

---

# 3.5 File Storage

Business-card images must be private.

Recommended:

- Supabase Storage private bucket
- Amazon S3 private bucket
- Cloudflare R2 private bucket

Example structure:

```text
business-cards/
  bts-2026/
    2026-11-17/
      LS-BTS-000001/
        original.jpg
        processed.jpg
```

Never create permanent public card-image URLs.

Use temporary signed URLs for authorized admin viewing.

---

# 3.6 Excel

Generate Excel files in Python using:

- **openpyxl**

Alternative:

- XlsxWriter

Recommended:

**openpyxl**

Excel generation happens only in the backend.

Example output:

```text
LatentSig_BTS_2026_Leads_2026-11-19.xlsx
```

---

# 3.7 Google Sheets

Optional but recommended.

Architecture:

```text
PostgreSQL
    |
    v
FastAPI sync service
    |
    v
Google Sheets API
    |
    v
Private LatentSig Sheet
```

Use:

- Google Service Account
- `google-api-python-client`
- `google-auth`

Never call Google Sheets directly from the browser.

---

# 3.8 Authentication

Admin dashboard should use Google login.

Recommended:

- Google OAuth
- Restrict access to approved LatentSig accounts

Example allowlist:

```text
bharat@latentsig.com
bhoomika@latentsig.com
raksha@latentsig.com
```

Also support:

```text
@latentsig.com
```

but use an explicit allowlist for sensitive admin functions.

Recommended role model:

```text
ADMIN
MANAGER
SALES
VIEWER
```

---

# 4. Public Website Pages

Recommended routes:

```text
/connect
/connect/card
/connect/card/review
/connect/manual
/connect/thank-you
```

Admin:

```text
/admin/login
/admin/dashboard
/admin/leads
/admin/leads/:id
/admin/settings
/admin/team
```

---

# 5. Public Landing Page

Route:

```text
/connect
```

## Content

Logo:

**LatentSig**

Heading:

> Let's stay connected.

Supporting text:

> Met our team today? Share your details in less than a minute.

Two primary actions:

### Option 1

**Scan / Upload Business Card**

Supporting text:

> Fastest option

### Option 2

**Enter Details Manually**

Supporting text:

> Takes less than a minute

Privacy line:

> Your information is securely shared only with the LatentSig team.

---

# 6. Manual Form

The manual form must be short.

## Required fields

### Full Name

```text
full_name
```

Required.

---

### Company

```text
company
```

Required.

---

### Job Title / Role

```text
job_title
```

Required.

---

### Work Email

```text
email
```

Required.

---

### WhatsApp / Phone

```text
phone
```

Required.

Support international numbers.

Store normalized E.164 format when possible.

---

# 7. Interest Selection

Use visual selectable cards/chips instead of a traditional select menu.

Options:

```text
AI Agents
Data & Analytics
Automation
Software Development
QA / Testing
Product Development
Partnership
Other
```

Allow one or multiple selections depending on product decision.

Recommended:

**Allow multiple interests.**

---

# 8. Intent Selection

Question:

> What would you like to discuss?

Options:

```text
I have a project
I need a demo
I am looking for a technology partner
Partnership opportunity
Investment / business discussion
Just connecting
Other
```

---

# 9. Optional Requirement Message

Label:

> Tell us briefly what you're looking for

Field:

```text
requirement_message
```

Maximum:

```text
1000 characters
```

Optional.

---

# 10. Business Card Flow

Route:

```text
/connect/card
```

## Step 1 — Capture

Show:

- Take photo
- Upload image

Supported:

```text
JPG
JPEG
PNG
WEBP
```

Recommended max size:

```text
10 MB
```

Mobile browsers should support camera capture.

HTML input can use:

```text
accept="image/*"
capture="environment"
```

Do not make camera capture mandatory.

Allow upload as fallback.

---

# 11. OCR Image Processing

Backend endpoint:

```text
POST /api/v1/ocr/business-card
```

Request:

```text
multipart/form-data
```

Processing:

```text
1. Validate content type
2. Validate actual image bytes
3. Validate file size
4. Decode image
5. Correct EXIF orientation
6. Resize very large image
7. Detect rotation
8. Improve contrast
9. Denoise
10. Sharpen if necessary
11. Run PaddleOCR
12. Collect text blocks
13. Parse likely contact fields
14. Produce confidence scores
15. Return extracted structured data
```

---

# 12. OpenCV Preprocessing

Recommended steps:

```text
Original
   |
   v
Orientation correction
   |
   v
Resize
   |
   v
Grayscale
   |
   v
Contrast enhancement
   |
   v
Denoising
   |
   v
Adaptive threshold when useful
   |
   v
Deskew
   |
   v
OCR
```

Do not over-process every image.

Use conditional preprocessing because colorful business cards can lose useful information after aggressive thresholding.

---

# 13. OCR Parsed Output

Backend response example:

```json
{
  "full_name": {
    "value": "Rachel Thomas",
    "confidence": 0.91
  },
  "company": {
    "value": "ABC Technologies",
    "confidence": 0.88
  },
  "job_title": {
    "value": "VP Innovation",
    "confidence": 0.84
  },
  "email": {
    "value": "rachel@abc.com",
    "confidence": 0.99
  },
  "phone": {
    "value": "+447700123456",
    "confidence": 0.92
  },
  "website": {
    "value": "abc.com",
    "confidence": 0.94
  }
}
```

---

# 14. Business Card Parsing

OCR itself returns text.

You still need a parser.

## Email

Use regex plus `email-validator`.

---

## Phone

Use:

```text
phonenumbers
```

Normalize to E.164.

---

## Website

Detect:

```text
www.
http://
https://
common domain formats
```

---

## Name

Name detection is difficult.

Heuristics:

- Prominent text
- Text near role/designation
- Not matching company-domain name
- Not email
- Not phone
- Not address

Optional future improvement:

Use a vision/LLM extraction service as a fallback only when confidence is low.

---

## Company

Heuristics:

- Largest organization-like text
- Words such as:
  - Technologies
  - Labs
  - Solutions
  - Pvt Ltd
  - Inc
  - LLC
  - GmbH
  - Corporation
  - Group
  - Systems

---

## Job title

Maintain known-role dictionary:

```text
CEO
CTO
COO
CFO
Founder
Co-Founder
Director
Manager
Engineer
Architect
Consultant
VP
Vice President
Head
Lead
Partner
President
Sales
Business Development
Product Manager
```

---

# 15. OCR Review Page

Route:

```text
/connect/card/review
```

Heading:

> Please confirm your details.

Every OCR field must be editable.

Show confidence only if useful to users.

Do not expose technical OCR confidence by default.

Fields:

```text
Full Name
Company
Role
Email
Phone
Website
```

Then:

```text
Interest
Intent
Requirement
```

Button:

> Confirm & Connect

---

# 16. Submission Endpoint

Endpoint:

```text
POST /api/v1/leads
```

Server must:

```text
1. Validate all fields
2. Normalize email
3. Normalize phone
4. Sanitize text
5. Check duplicate lead
6. Create/reuse lead
7. Create interaction
8. Save capture metadata
9. Save business-card reference if available
10. Queue spreadsheet sync
11. Return success
```

---

# 17. Duplicate Detection

Do not blindly create duplicate people.

Check:

```text
normalized_email
```

Then:

```text
normalized_phone
```

If matching lead exists:

```text
reuse lead
create new interaction
```

Example:

Rachel met the LatentSig team in November and again in January.

There should be:

```text
1 lead
2 interactions
```

not:

```text
2 duplicate contacts
```

---

# 18. Database Design

## Table: users

```text
id
email
full_name
role
is_active
created_at
updated_at
```

---

# 19. Table: leads

```text
id UUID PK
lead_code UNIQUE
full_name
company
job_title
email
normalized_email
phone
normalized_phone
website
created_at
updated_at
```

Indexes:

```text
normalized_email
normalized_phone
company
created_at
```

---

# 20. Table: events

```text
id
name
slug
start_date
end_date
location
is_active
created_at
updated_at
```

Example:

```text
Bengaluru Tech Summit 2026
bts-2026
```

---

# 21. Table: interactions

```text
id UUID PK
lead_id FK
event_id FK
interest JSONB / array
intent
requirement_message
capture_method
source
captured_by
status
assigned_to
created_at
updated_at
```

Capture method:

```text
manual
business_card
```

Status:

```text
new
contacted
qualified
meeting
proposal
won
follow_up_later
not_interested
lost
```

---

# 22. Table: business_cards

```text
id
lead_id
interaction_id
storage_path
original_filename
mime_type
file_size
ocr_text
ocr_json
created_at
```

Do not store full image binary inside PostgreSQL.

Store file in private object storage.

---

# 23. Table: lead_notes

```text
id
lead_id
interaction_id
author_user_id
note
created_at
updated_at
```

---

# 24. Table: audit_logs

Recommended.

```text
id
user_id
action
entity_type
entity_id
metadata
created_at
```

Examples:

```text
lead_exported
lead_status_changed
lead_assigned
lead_deleted
admin_login
```

---

# 25. QR Source Tracking

Use QR links like:

```text
https://connect.latentsig.com/connect?ref=bhoomika
https://connect.latentsig.com/connect?ref=raksha
https://connect.latentsig.com/connect?ref=bharat
https://connect.latentsig.com/connect?ref=booth
```

Store:

```text
ref
utm_source
utm_medium
utm_campaign
```

Recommended event QR:

```text
?ref=booth&utm_source=bts&utm_medium=qr&utm_campaign=bts-2026
```

---

# 26. Admin Login

Route:

```text
/admin/login
```

Button:

> Continue with Google

Allowed:

```text
bharat@latentsig.com
bhoomika@latentsig.com
raksha@latentsig.com
```

Create admin setting:

```text
ADMIN_EMAIL_ALLOWLIST
```

Example:

```text
bharat@latentsig.com,bhoomika@latentsig.com,raksha@latentsig.com
```

---

# 27. Admin Roles

## ADMIN

Can:

- View all leads
- Edit all leads
- Delete leads
- Export Excel
- Manage users
- Manage events
- Manage integrations

---

## MANAGER

Can:

- View all leads
- Assign leads
- Change statuses
- Add notes
- Export Excel

Cannot:

- Manage core integrations
- Delete admin users

---

## SALES

Can:

- View assigned leads
- View permitted shared leads
- Change status
- Add notes
- Contact lead

Optional:

- Allow export

---

## VIEWER

Can:

- View permitted leads

Cannot:

- Edit
- Export
- Assign

---

# 28. Admin Dashboard

Route:

```text
/admin/dashboard
```

Cards:

```text
Total Leads
New
Contacted
Qualified
Meetings
Proposals
Won
```

Additional analytics:

```text
Leads by interest
Leads by staff member
Leads by day
Leads by event
Leads by status
```

Keep charts simple.

---

# 29. Leads Page

Route:

```text
/admin/leads
```

Features:

- Search
- Filters
- Sort
- Pagination
- Column visibility
- Excel download
- CSV optional
- Bulk assignment
- Bulk status change optional

Search by:

```text
Name
Company
Email
Phone
```

Filters:

```text
Event
Date
Interest
Intent
Status
Captured By
Assigned To
Capture Method
```

---

# 30. Leads Table

Columns:

```text
Lead ID
Name
Company
Role
Email
WhatsApp
Interest
Intent
Captured By
Assigned To
Status
Date
```

Keep fewer columns visible on mobile.

---

# 31. Lead Detail

Route:

```text
/admin/leads/:id
```

Show:

```text
Name
Company
Role
Email
Phone
Website
Interest
Intent
Requirement
Event
Source
Capture Method
Captured By
Assigned To
Status
Created At
Business Card
Internal Notes
Interaction History
```

Actions:

```text
WhatsApp
Email
Assign
Change Status
Add Note
```

---

# 32. Excel Download

Endpoint:

```text
GET /api/v1/admin/exports/leads.xlsx
```

Query parameters:

```text
event_id
date_from
date_to
status
interest
captured_by
assigned_to
```

Example:

```text
/api/v1/admin/exports/leads.xlsx?event=bts-2026
```

Output:

```text
LatentSig_BTS_2026_Leads_2026-11-19.xlsx
```

---

# 33. Excel Workbook

## Sheet 1 — Leads

Columns:

```text
Lead ID
Created At
Full Name
Company
Job Title
Email
WhatsApp
Website
Interest
Intent
Requirement
Capture Method
Source
Captured By
Assigned To
Status
Notes
```

---

## Sheet 2 — Summary

Include:

```text
Total leads
Leads by status
Leads by interest
Leads by captured-by employee
Leads by assigned employee
Leads by capture method
```

---

## Sheet 3 — Export Metadata

Optional.

Include:

```text
Generated At
Generated By
Event
Filters Applied
Total Rows
```

---

# 34. Google Sheets Sync

Database remains source of truth.

Recommended flow:

```text
Lead submission
      |
      v
PostgreSQL transaction completes
      |
      v
Background sync job
      |
      v
Google Sheet updated
```

If Google Sheets is unavailable:

```text
DO NOT FAIL LEAD SUBMISSION
```

Instead:

```text
store sync status = pending
retry later
```

Create table:

```text
integration_jobs
```

Fields:

```text
id
type
entity_id
status
attempt_count
last_error
next_retry_at
created_at
updated_at
```

---

# 35. Background Tasks

Use FastAPI background tasks for simple workloads.

For more reliable production processing use:

- Celery + Redis
- RQ + Redis
- Dramatiq

Recommended for MVP:

**FastAPI BackgroundTasks**

Recommended when volume grows:

**Celery + Redis**

Possible jobs:

```text
Google Sheet sync
OCR processing
thumbnail generation
email notifications
cleanup
export generation
```

---

# 36. Public Mobile UI/UX

Mobile is the most important interface because visitors scan QR codes on phones.

Recommended breakpoints:

```text
320–479 px
480–767 px
768+ px
1024+ px
```

---

# 37. Mobile Landing Layout

```text
┌──────────────────────────────┐
│          LATENTSIG           │
│                              │
│   Let's stay connected.      │
│                              │
│ Met our team today?          │
│ Share your details in less   │
│ than a minute.               │
│                              │
│ ┌──────────────────────────┐ │
│ │ 📷 Scan Business Card    │ │
│ │ Fastest option           │ │
│ └──────────────────────────┘ │
│                              │
│              OR              │
│                              │
│ ┌──────────────────────────┐ │
│ │ ✍ Enter Details         │ │
│ │ Takes less than a minute │ │
│ └──────────────────────────┘ │
│                              │
│ 🔒 Shared only with our team │
└──────────────────────────────┘
```

---

# 38. Mobile UX Rules

Use:

```text
Minimum touch target: 44px
Recommended button height: 48–56px
```

Input:

```text
48–52px height
```

Spacing:

```text
16px minimum side padding
24px preferred main page padding
```

Do not use:

- Tiny text
- Horizontal scrolling
- Very large menus
- Multi-column forms
- Hover-only interactions

Use mobile keyboards appropriately:

```text
email → inputMode=email
phone → inputMode=tel
```

---

# 39. Desktop UI

Desktop should not simply stretch the mobile form to full width.

Use centered content.

Example:

```text
max-width: 1100px
```

Landing desktop:

```text
┌─────────────────────────────────────────────────────┐
│                     LATENTSIG                       │
│                                                     │
│            Let's stay connected.                    │
│                                                     │
│   ┌───────────────────┐   ┌─────────────────────┐  │
│   │ Business Card     │   │ Manual Entry        │  │
│   │                   │   │                     │  │
│   │ Scan or upload    │   │ Enter details       │  │
│   └───────────────────┘   └─────────────────────┘  │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

# 40. Desktop Manual Form

Use:

```text
max-width: 720px
```

Recommended fields:

```text
Name           Company
Role           Email
Phone          Website
```

But keep logical flow.

On mobile, stack everything vertically.

On desktop, two-column layout can be used for basic contact fields only.

Interest and intent selections should remain full width.

---

# 41. Responsive Admin Dashboard

Desktop:

- Sidebar navigation
- Full table
- Filters in toolbar

Tablet:

- Collapsible sidebar
- Fewer table columns

Mobile:

- Bottom sheet filters
- Lead cards instead of wide table
- Search at top
- Primary actions visible

---

# 42. Mobile Admin Lead Card

Example:

```text
Rachel Thomas
ABC Technologies

VP Innovation

AI Agents
Qualified

Captured by: Bhoomika
17 Nov, 11:42 AM

[ View ]
```

Do not force large data tables onto a 360px-wide device.

---

# 43. Design System

Use design tokens.

## Spacing

```text
4
8
12
16
20
24
32
40
48
64
```

---

## Radius

Recommended:

```text
Inputs: 10–12px
Cards: 16px
Primary panels: 20–24px
```

---

## Typography

Recommended:

```text
Font: Inter
```

Hierarchy:

```text
Display
H1
H2
H3
Body
Small
Label
Caption
```

---

# 44. UI Style

Direction:

- Minimal
- Premium
- Professional
- Corporate
- Modern
- Card-based
- Clean whitespace
- Soft borders
- Strong hierarchy

Avoid:

- Google Form look
- Heavy gradients everywhere
- Neon colors
- Too many animations
- Dense text
- Large marketing navigation
- Unnecessary carousels

---

# 45. Loading States

OCR loading:

```text
Reading your business card...
```

Show:

- Progress indicator
- Card preview
- Friendly status

Do not show:

```text
PaddleOCR inference...
```

to public visitors.

---

# 46. OCR Error State

If OCR cannot confidently identify fields:

Show:

> We couldn't read everything clearly. Please check or complete the fields below.

Pre-fill anything detected.

Do not show a hard failure unless the image itself is invalid.

---

# 47. Form Error UX

Inline errors.

Example:

```text
Work Email

abc@

Please enter a valid email address.
```

Never clear all previously entered data after validation failure.

---

# 48. Submission State

Button:

```text
Connect With Us
```

While submitting:

```text
Submitting...
```

Disable repeated clicks.

Use idempotency on backend if possible.

---

# 49. Thank-You Page

Route:

```text
/connect/thank-you
```

Example:

```text
✓

Thank you, Rachel!

It was great connecting with you.

We've received your details.
Our team will follow up shortly.

[ Continue on WhatsApp ]

[ Visit LatentSig ]
```

---

# 50. WhatsApp

Do not automatically send messages.

Use a user-clicked deep link.

Example template:

```text
Hi LatentSig,

I just connected with your team and I'd like to continue our discussion.
```

Optionally include:

```text
Event: Bengaluru Tech Summit 2026
```

---

# 51. API Structure

Recommended:

```text
/api/v1/health

/api/v1/events/current

/api/v1/ocr/business-card

/api/v1/leads

/api/v1/auth/google
/api/v1/auth/me

/api/v1/admin/dashboard
/api/v1/admin/leads
/api/v1/admin/leads/{id}
/api/v1/admin/leads/{id}/status
/api/v1/admin/leads/{id}/assign
/api/v1/admin/leads/{id}/notes

/api/v1/admin/exports/leads.xlsx

/api/v1/admin/users
/api/v1/admin/events
```

---

# 52. Backend Project Structure

```text
backend/
  app/
    main.py

    api/
      v1/
        routes/
          auth.py
          leads.py
          ocr.py
          exports.py
          admin.py
          events.py

    core/
      config.py
      security.py
      logging.py
      rate_limit.py

    db/
      base.py
      session.py
      models/
      migrations/

    schemas/
      auth.py
      lead.py
      interaction.py
      ocr.py
      export.py

    services/
      ocr/
        engine.py
        preprocess.py
        parser.py
        confidence.py

      leads/
        service.py
        dedupe.py

      integrations/
        google_sheets.py
        whatsapp.py

      exports/
        excel.py

      storage/
        business_cards.py

    repositories/
      leads.py
      interactions.py
      users.py

    tests/
      unit/
      integration/

  requirements.txt
  alembic.ini
  Dockerfile
```

---

# 53. Frontend Project Structure

```text
frontend/
  src/
    app/
      router.tsx

    pages/
      public/
        ConnectHome.tsx
        ManualLeadForm.tsx
        CardUpload.tsx
        CardReview.tsx
        ThankYou.tsx

      admin/
        Login.tsx
        Dashboard.tsx
        Leads.tsx
        LeadDetail.tsx
        Team.tsx
        Settings.tsx

    components/
      ui/
      forms/
      cards/
      admin/
      layout/

    features/
      leads/
      ocr/
      auth/
      exports/

    hooks/

    services/
      api.ts

    schemas/
      lead.ts
      auth.ts

    types/

    utils/

    styles/
      globals.css

  public/

  vite.config.ts
  tsconfig.json
```

---

# 54. Environment Variables

## Backend

```text
APP_ENV
APP_SECRET

DATABASE_URL

GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET

GOOGLE_SERVICE_ACCOUNT_EMAIL
GOOGLE_PRIVATE_KEY
GOOGLE_SHEET_ID

ADMIN_EMAIL_ALLOWLIST

STORAGE_PROVIDER
STORAGE_BUCKET
STORAGE_ENDPOINT
STORAGE_ACCESS_KEY
STORAGE_SECRET_KEY

FRONTEND_URL

REDIS_URL

WHATSAPP_NUMBER
```

---

# 55. Frontend Environment

Only public-safe values.

```text
VITE_API_BASE_URL
VITE_APP_NAME
VITE_PUBLIC_SITE_URL
```

Never place:

```text
DATABASE_URL
GOOGLE_PRIVATE_KEY
SERVICE_ACCOUNT_KEY
STORAGE_SECRET
ADMIN_SECRET
```

in Vite variables.

Anything starting with `VITE_` can become visible in the browser bundle.

---

# 56. Security

Required:

- HTTPS
- Server-side validation
- Parameterized ORM queries
- Authorization checks
- Authentication checks
- Rate limiting
- File-size limits
- MIME validation
- Magic-byte validation
- Secure cookies where used
- CORS allowlist
- CSRF protections depending on auth flow
- Private object storage
- No private keys in frontend
- Audit logging
- Admin export permission checks

---

# 57. OCR File Security

Do not trust filename extension.

Validate:

```text
declared MIME
actual image decoding
actual file signature
```

Reject:

```text
SVG
HTML disguised as JPG
executables
archives
unsupported files
```

Strip unnecessary metadata when creating processed versions.

---

# 58. Rate Limits

Example:

OCR:

```text
10 requests / 5 minutes / IP
```

Lead submissions:

```text
20 requests / 10 minutes / IP
```

Admin:

normal authenticated limits.

Exact values can be adjusted after testing.

---

# 59. Privacy

Display short privacy notice:

> By submitting your information, you agree that LatentSig may use it to contact you regarding your enquiry or business discussion.

Add link to privacy policy.

Store only information actually needed.

Define retention policy for business-card images.

Recommended:

- Keep structured lead data according to company policy.
- Automatically delete raw card images after a defined period if not required.

Example:

```text
90 days
```

---

# 60. Logging

Log:

- Request ID
- Route
- Status
- Duration
- Error type

Do not log:

- OAuth tokens
- Full API keys
- Private keys
- Passwords
- Full raw business-card content unnecessarily

---

# 61. Error Monitoring

Recommended:

- Sentry frontend
- Sentry backend

Track:

- OCR failures
- API errors
- Submission errors
- Sheet sync failures
- Export failures

---

# 62. Testing

## Frontend

Use:

- Vitest
- React Testing Library
- Playwright

Test:

```text
Mobile landing
Manual form
Card upload
Card review
Validation
Thank-you flow
Admin login
Lead filters
Excel export button
```

---

# 63. Backend Tests

Use:

- pytest
- pytest-asyncio
- httpx test client

Test:

```text
lead creation
duplicate detection
auth
permissions
OCR parsing
phone normalization
email validation
file validation
Excel export
Google Sheet failure handling
```

---

# 64. OCR Test Dataset

Create a test folder:

```text
tests/ocr/cards/
```

Include:

- Normal horizontal card
- Dark card
- White card
- Rotated card
- Slightly blurred card
- Reflective photo
- Low-light photo
- International phone
- Multiple emails
- Company logo
- Card with QR code
- Non-English name
- Vertical card

Track:

```text
field accuracy
email accuracy
phone accuracy
name accuracy
company accuracy
role accuracy
```

---

# 65. Performance Goals

Public landing:

```text
< 2s load on good mobile connection
```

Manual submission:

```text
< 1.5s typical
```

OCR:

Target:

```text
1–5 seconds
```

depending on hardware and image.

Never block lead creation because Google Sheet sync is slow.

---

# 66. Accessibility

Use:

- Semantic labels
- Keyboard support
- Visible focus
- Sufficient contrast
- ARIA only when needed
- Error text linked to fields
- Proper button names

Target:

**WCAG 2.1 AA principles**

---

# 67. Deployment

Recommended split:

```text
Frontend
React/Vite
    |
    v
Vercel / Cloudflare Pages

Backend
FastAPI
    |
    v
Render / Railway / Fly.io / AWS / company server

Database
PostgreSQL
    |
    v
Supabase / Neon / managed Postgres

Storage
Private object storage
```

---

# 68. Docker

Backend should ship with Dockerfile.

Recommended:

```text
python:3.12-slim
```

OCR can require additional system libraries.

For PaddleOCR, verify dependencies inside the production image.

Possible OCR image:

```text
Python
OpenCV system libs
PaddlePaddle
PaddleOCR
FastAPI
Uvicorn
```

---

# 69. CI/CD

GitHub Actions:

Frontend:

```text
npm ci
npm run lint
npm run test
npm run build
```

Backend:

```text
pip install -r requirements.txt
ruff check
pytest
alembic check
```

Optional:

```text
Playwright smoke test
```

---

# 70. Recommended Repository Structure

```text
latentsig-connect/
  frontend/
  backend/

  docs/
    architecture.md
    api.md
    deployment.md
    privacy.md

  docker-compose.yml
  README.md
```

---

# 71. Local Development

Docker Compose:

```text
frontend
backend
postgres
redis
```

Optional:

```text
minio
```

for S3-compatible local file storage.

---

# 72. MVP Scope

Must have before event:

```text
React responsive UI
Manual form
Business-card upload
Python OCR
OCR review
FastAPI backend
PostgreSQL
Duplicate detection
Private storage
Allowlisted email/password team login (Google OAuth optional)
Admin dashboard
Lead table
Lead details
Excel export
Google Sheet sync
QR tracking
WhatsApp CTA
Thank-you screen
Mobile testing
Desktop testing
```

---

# 73. Phase 2

After MVP:

```text
Lead scoring
Automatic follow-up reminders
CRM integration
Email sequences
WhatsApp Business API
Meeting scheduling
Lead enrichment
AI summary
OCR confidence analytics
Multi-event support
Multiple organizations
Advanced analytics
```

---

# 74. Recommended Build Order

## Stage 1

Create:

```text
React project
FastAPI project
PostgreSQL
Docker local environment
```

---

## Stage 2

Build public manual form.

Complete:

```text
/connect
/connect/manual
/connect/thank-you
```

Before OCR.

---

## Stage 3

Build backend lead creation.

Complete:

```text
database
validation
dedupe
interaction creation
```

---

## Stage 4

Build Python OCR.

Complete:

```text
upload
preprocessing
PaddleOCR
parsing
review
```

---

## Stage 5

Build admin authentication.

---

## Stage 6

Build leads dashboard and details.

---

## Stage 7

Build Excel export.

---

## Stage 8

Add Google Sheets sync.

---

## Stage 9

Add QR attribution.

---

## Stage 10

Perform:

```text
mobile tests
desktop tests
security tests
event simulation
```

---

# 75. Production Readiness Checklist

**Implementation status (2026-09-29):** Admin email/password login, event QR generation, backup jobs, API health/metrics, and Prometheus alert rules are implemented. Browser/API coverage verifies local flows. Physical devices and production services still require verification in the target environment.

Before event:

```text
[ ] QR works on iPhone
[ ] QR works on Android
[x] Event QR renders with event attribution and downloads as SVG (browser E2E; physical scan remains unverified)
[x] Camera capture input requests the rear camera (`capture=environment`; physical device test remains)
[x] Android browser emulation accepts a rear-camera photo and opens editable OCR review (E2E)
[x] Gallery upload works (browser upload flow)
[x] Manual form works
[x] Slow/offline API failure preserves form data and explains submission was not sent
[x] OCR failure fallback works
[x] Duplicate detection works (API tests)
[x] Admin login works (allowlisted email/password; local email-only shortcut)
[x] Unauthorized email blocked (API tests)
[x] Excel export works (API workbook and browser download)
[ ] Google Sheet sync works (real Google credentials and target sheet required; worker success is covered with a test double)
[x] Google Sheet failure does not lose leads (worker retry test)
[x] Business-card images are private (authenticated admin fetch tested)
[x] WhatsApp CTA works
[x] Mobile layout tested 320px+ (320–430px browser viewports)
[x] Desktop layout tested
[x] Database backups enabled (verified SQLite snapshots; daily verified PostgreSQL Compose job)
[x] Monitoring enabled (API metrics, readiness checks, Prometheus scrape and alert rules)
[x] Error logging enabled (application/server logs)
[x] Privacy text present
[ ] Production secrets configured for a deployed domain (secure `.env` generation script is implemented)
```

---

# 76. Final Recommended Stack

## Frontend

```text
React
TypeScript
Vite
React Router
Tailwind CSS
shadcn/ui
React Hook Form
Zod
TanStack Query
TanStack Table
Lucide React
```

---

## Backend

```text
Python
FastAPI
Pydantic
SQLAlchemy
Alembic
Uvicorn
PostgreSQL
```

---

## OCR

```text
Python
PaddleOCR
OpenCV
Pillow
NumPy
phonenumbers
email-validator
```

---

## Storage

```text
Supabase Storage / S3 / R2
Private bucket
```

---

## Authentication

```text
Salted password login for allowlisted LatentSig team email addresses
Optional Google OAuth
RBAC
```

---

## Spreadsheet

```text
Google Sheets API
Private company sheet
```

---

## Excel

```text
openpyxl
```

---

## Testing

```text
Vitest
React Testing Library
Playwright
pytest
```

---

## Deployment

```text
Frontend:
Vercel / Cloudflare Pages

Backend:
Render / Railway / Fly.io / AWS / company server

Database:
Supabase PostgreSQL / Neon / managed Postgres
```

---

# 77. Full Codex Build Prompt

Use the following prompt with Codex.

```text
Build a production-ready event lead capture application called "LatentSig Connect".

ARCHITECTURE

Frontend:
React
TypeScript
Vite
React Router
Tailwind CSS
shadcn/ui
React Hook Form
Zod
TanStack Query
TanStack Table

Backend:
Python
FastAPI
Pydantic
SQLAlchemy
Alembic
PostgreSQL

OCR:
Python
OpenCV
PaddleOCR
Pillow
NumPy
phonenumbers
email-validator

Excel:
openpyxl

The application must be mobile-first while also providing an excellent tablet and desktop UX.

PURPOSE

The website is used by LatentSig at events and business meetings.

A visitor scans a QR code and can either:

1. Scan/upload a business card.
2. Enter contact information manually.

After submission, data is stored privately in PostgreSQL.

Authorized LatentSig employees can log into a private admin dashboard, manage leads and download Excel exports.

PUBLIC ROUTES

/connect
/connect/manual
/connect/card
/connect/card/review
/connect/thank-you

ADMIN ROUTES

/admin/login
/admin/dashboard
/admin/leads
/admin/leads/:id
/admin/team
/admin/settings

PUBLIC LANDING PAGE

Show LatentSig logo.

Heading:

"Let's stay connected."

Supporting copy:

"Met our team today? Share your details in less than a minute."

Provide two large responsive action cards:

"Scan / Upload Business Card"
"Fastest option"

and

"Enter Details Manually"
"Takes less than a minute"

Show privacy text:

"Your information is securely shared only with the LatentSig team."

MANUAL FORM

Required:

full_name
company
job_title
email
phone

Optional:

website
requirement_message

interest must support:

AI Agents
Data & Analytics
Automation
Software Development
QA / Testing
Product Development
Partnership
Other

intent:

I have a project
I need a demo
I am looking for a technology partner
Partnership opportunity
Investment / business discussion
Just connecting
Other

Use React Hook Form and Zod.

Make fields touch-friendly.

Support international phone numbers.

BUSINESS CARD UPLOAD

Allow:

JPG
JPEG
PNG
WEBP

Maximum 10MB.

On mobile support camera capture with the environment-facing camera.

Upload image to FastAPI.

Endpoint:

POST /api/v1/ocr/business-card

OCR BACKEND

Validate MIME and real image contents.

Correct EXIF orientation.

Preprocess using OpenCV.

Use PaddleOCR.

Parse:

full name
company
job title
email
phone
website

Use regex + email-validator for email.

Use phonenumbers for phone.

Return field confidence.

Never automatically submit OCR data.

Always show a review page where the visitor can edit every extracted field.

DATABASE

Use PostgreSQL.

Create:

users
events
leads
interactions
business_cards
lead_notes
audit_logs
integration_jobs

LEADS

id UUID
lead_code
full_name
company
job_title
email
normalized_email
phone
normalized_phone
website
created_at
updated_at

INTERACTIONS

id UUID
lead_id
event_id
interest
intent
requirement_message
capture_method
source
captured_by
status
assigned_to
created_at
updated_at

Capture methods:

manual
business_card

Statuses:

new
contacted
qualified
meeting
proposal
won
follow_up_later
not_interested
lost

DUPLICATE LOGIC

Normalize and check email.

Then normalize/check phone.

If lead already exists:

reuse lead
create new interaction

Do not duplicate contact unnecessarily.

BUSINESS CARD STORAGE

Use a private object-storage bucket.

Never create permanent public URLs.

Store storage path in database.

Use signed URLs for authorized admins.

ADMIN AUTH

Use allowlisted email/password login with salted password hashes and rate limiting. Google OAuth may be enabled as an optional sign-in method.

Initially allow:

bharat@latentsig.com
bhoomika@latentsig.com
raksha@latentsig.com

Support environment variable:

ADMIN_EMAIL_ALLOWLIST

Create roles:

ADMIN
MANAGER
SALES
VIEWER

Enforce authorization server side.

ADMIN DASHBOARD

Show:

Total Leads
New
Contacted
Qualified
Meeting
Proposal
Won

Show simple charts:

Leads by interest
Leads by status
Leads by employee
Leads by date

ADMIN LEADS PAGE

Search:

name
company
email
phone

Filters:

event
date
interest
intent
status
captured_by
assigned_to
capture_method

Desktop:
use a responsive table.

Mobile:
use stacked lead cards instead of forcing a wide table.

LEAD DETAIL

Show:

name
company
role
email
phone
website
interest
intent
requirement
event
source
capture method
captured by
assigned to
status
business card
notes
interaction history

Actions:

WhatsApp
Email
Assign
Change status
Add note

QR TRACKING

Support:

/connect?ref=bhoomika
/connect?ref=raksha
/connect?ref=bharat
/connect?ref=booth

Also support UTM parameters.

Persist attribution with interaction.

EXCEL

Create:

GET /api/v1/admin/exports/leads.xlsx

Use openpyxl.

Allow filters.

Workbook:

Sheet 1: Leads
Sheet 2: Summary
Sheet 3: Export Metadata

Leads columns:

Lead ID
Created At
Full Name
Company
Job Title
Email
WhatsApp
Website
Interest
Intent
Requirement
Capture Method
Source
Captured By
Assigned To
Status
Notes

Summary:

Total Leads
Leads by Status
Leads by Interest
Leads by Captured By
Leads by Assigned To
Leads by Capture Method

GOOGLE SHEETS

PostgreSQL is the source of truth.

Implement server-side synchronization to a private Google Sheet.

Use Google Service Account credentials.

Never expose credentials to frontend.

If Google Sheets is unavailable:

do not fail lead creation.

Store a pending integration job and retry.

WHATSAPP

Thank-you page should show:

"Thank you, {first_name}!"

"It was great connecting with you."

"We've received your details. Our team will follow up shortly."

Provide button:

"Continue on WhatsApp"

Use a user-clicked WhatsApp deep link with a prefilled message.

Never automatically send a WhatsApp message.

RESPONSIVE DESIGN

Mobile-first.

Support at minimum:

320px
375px
390px
430px
768px
1024px
1280px+

Minimum touch target:

44px

Preferred primary button height:

48–56px

Mobile:

single-column form
large actions
no horizontal scrolling
no hover dependencies

Desktop:

centered layout
maximum content width
two-column basic contact fields where appropriate
interest/intent full width

ADMIN MOBILE

Do not use giant desktop tables.

Use lead cards.

DESIGN DIRECTION

Modern
professional
premium
minimal
card-based
generous whitespace
soft borders
clear hierarchy
rounded components

Do not make it look like Google Forms.

Do not add unnecessary navigation.

ACCESSIBILITY

Use semantic labels.
Visible keyboard focus.
Proper input associations.
Accessible errors.
Sufficient contrast.
Follow WCAG 2.1 AA principles.

SECURITY

Server-side validation.
Rate limiting.
Authorization.
CORS allowlist.
Secure OAuth handling.
Private object storage.
Image magic-byte validation.
Image size validation.
Parameterized ORM queries.
Audit logs.
No private keys in frontend.
No service-account keys in frontend.
No database admin credentials in frontend.

ENVIRONMENT VARIABLES

Backend:

APP_ENV
APP_SECRET
DATABASE_URL
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
GOOGLE_SERVICE_ACCOUNT_EMAIL
GOOGLE_PRIVATE_KEY
GOOGLE_SHEET_ID
ADMIN_EMAIL_ALLOWLIST
STORAGE_PROVIDER
STORAGE_BUCKET
STORAGE_ENDPOINT
STORAGE_ACCESS_KEY
STORAGE_SECRET_KEY
FRONTEND_URL
REDIS_URL
WHATSAPP_NUMBER

Frontend:

VITE_API_BASE_URL
VITE_APP_NAME
VITE_PUBLIC_SITE_URL

TESTING

Frontend:

Vitest
React Testing Library
Playwright

Backend:

pytest
pytest-asyncio

Test:

manual lead flow
OCR flow
OCR failure
form validation
duplicate handling
admin authorization
Excel export
Google Sheet failure
mobile layout
desktop layout

PROJECT STRUCTURE

Create separate:

frontend/
backend/
docs/

Include:

README.md
docker-compose.yml
backend Dockerfile
frontend build configuration
Alembic migrations
.env.example files
API documentation
setup instructions
deployment instructions

DELIVERY STANDARD

The project must run locally.

Provide setup instructions.

Provide migrations.

Provide seed data for one test event.

Provide clean, maintainable and modular code.

Do not hard-code production secrets.

Keep OCR implementation behind an abstraction/service layer so another OCR engine can be added later.
```

---

# 78. Final Architecture

```text
                         PUBLIC USER

                             QR
                              |
                              v
                    React Mobile Website
                              |
                 +------------+-------------+
                 |                          |
                 v                          v
           Manual Form               Business Card
                                             |
                                             v
                                    FastAPI OCR Endpoint
                                             |
                                             v
                                      OpenCV + PaddleOCR
                                             |
                                             v
                                       Review Details
                 |                          |
                 +------------+-------------+
                              |
                              v
                        FastAPI API
                              |
                              v
                         PostgreSQL
                              |
          +-------------------+--------------------+
          |                   |                    |
          v                   v                    v
   Private Storage      Google Sheets        Excel Export
          |                                        |
          v                                        v
 Business Cards                          Authorized Team
                                                   |
                                                   v
                                          React Admin App
                                                   |
                                      +------------+-------------+
                                      |                          |
                                      v                          v
                                   Sales                      Manager
```

---

# 79. Key Product Rule

The system must be optimized for this outcome:

> **A valuable event contact should be captured in less than one minute without losing privacy, accuracy, or follow-up context.**

The visitor experience should stay simple.

The internal system can be more powerful.

Public experience:

```text
Scan
Choose
Confirm
Submit
Done
```

Internal experience:

```text
Store
Search
Assign
Track
Export
Follow up
```
