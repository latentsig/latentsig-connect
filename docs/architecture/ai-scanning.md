# AI scanning flow

```mermaid
sequenceDiagram
  participant V as Visitor
  participant UI as React app
  participant API as FastAPI
  participant OR as OpenRouter
  V->>UI: Capture front and optional back
  UI->>API: Multipart images
  API->>API: Check MIME, size, pixels, EXIF; normalize image
  API->>OR: Backend-authenticated JSON Schema vision request
  OR-->>API: Structured contact fields
  API->>API: Pydantic validation and bounded retries
  API-->>UI: Editable fields and private review tokens
  UI-->>V: Correct fields and provide consent
  V->>UI: Confirm submission
  UI->>API: Lead submission
```

Provider failure returns a safe retry/manual-entry message. Images are staged only after extraction succeeds.
