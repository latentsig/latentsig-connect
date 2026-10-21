# Database and integration model

```mermaid
erDiagram
  EVENT ||--o{ INTERACTION : hosts
  LEAD ||--o{ INTERACTION : has
  LEAD ||--o{ BUSINESS_CARD : stores
  INTERACTION ||--o| BUSINESS_CARD : captures
  USER ||--o{ INTERACTION : assigned
  LEAD ||--o{ LEAD_NOTE : receives
  INTERACTION ||--o{ INTEGRATION_JOB : queues
  LEAD {
    uuid id PK
    string lead_code
    string normalized_email UK
    string normalized_phone UK
    string address
  }
  INTERACTION {
    uuid id PK
    uuid lead_id FK
    uuid event_id FK
    datetime data_processing_consent_at
    datetime follow_up_consent_at
    string consent_notice_version
    datetime ai_processing_consent_at
    string ai_processing_consent_notice_version
    string idempotency_key UK
    boolean submission_created
    string status
  }
  BUSINESS_CARD {
    uuid id PK
    uuid lead_id FK
    uuid interaction_id FK
    string private_storage_path
  }
```

The lead is the canonical contact. Each event creates an interaction. Card files remain in private object/local storage; integration jobs synchronize interaction reporting data after commit.
