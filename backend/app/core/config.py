from pathlib import Path
from urllib.parse import urlparse
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_env: str = "development"
    app_secret: str = "local-development-only"
    database_url: str = "sqlite:///./latentsig.db"
    frontend_url: str = "http://localhost:5173"
    frontend_urls: str = "http://localhost:5173,http://127.0.0.1:5173"
    whatsapp_number: str = ""
    max_upload_bytes: int = 10 * 1024 * 1024
    default_phone_region: str = "IN"
    default_event_slug: str = "bts-2026"
    private_storage_dir: Path = BACKEND_ROOT / "private_storage"
    admin_email_allowlist: str = "raksha@latentsig.com,bhoomika@latentsig.com,bharat@latentsig.com,info@latentsig.com,shauryasharthak@latentsig.com"
    initial_admin_emails: str = "bharat@latentsig.com,bhoomika@latentsig.com"
    session_cookie_name: str = "latentsig_session"
    session_max_age_seconds: int = 28800
    redis_url: str = ""
    lead_rate_limit_count: int = 20
    lead_rate_limit_window_seconds: int = 600
    ocr_rate_limit_count: int = 10
    ocr_rate_limit_window_seconds: int = 300
    auth_rate_limit_count: int = 10
    auth_rate_limit_window_seconds: int = 300
    business_card_retention_days: int = 90
    consent_notice_version: str = "2026-10-21-v1"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemini-3.8-flash"
    ocr_provider: str = "openrouter"
    ocr_timeout_seconds: int = 20
    ocr_max_retries: int = 2
    ocr_max_output_tokens: int = 1000
    ocr_enabled: bool = True
    google_service_account_json: str = ""
    google_service_account_email: str = ""
    google_private_key: str = ""
    google_sheet_id: str = ""
    google_sheet_tab: str = "Leads"
    storage_provider: str = "local"
    storage_bucket: str = ""
    storage_endpoint: str = ""
    storage_access_key: str = ""
    storage_secret_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.frontend_urls.split(",") if origin.strip()]

    @property
    def admin_emails(self) -> set[str]:
        return {email.strip().lower() for email in self.admin_email_allowlist.split(",") if email.strip()}

    @property
    def initial_admins(self) -> set[str]:
        return {email.strip().lower() for email in self.initial_admin_emails.split(",") if email.strip()}

    @model_validator(mode="after")
    def validate_production_configuration(self):
        if self.ocr_timeout_seconds < 1 or self.ocr_timeout_seconds > 120:
            raise ValueError("OCR_TIMEOUT_SECONDS must be between 1 and 120.")
        if self.ocr_max_retries < 0 or self.ocr_max_retries > 5:
            raise ValueError("OCR_MAX_RETRIES must be between 0 and 5.")
        if self.ocr_max_output_tokens < 100 or self.ocr_max_output_tokens > 4000:
            raise ValueError("OCR_MAX_OUTPUT_TOKENS must be between 100 and 4000.")
        if self.ocr_provider.lower() != "openrouter":
            raise ValueError("OCR_PROVIDER must be openrouter.")
        if self.app_env.lower() == "production":
            if self.app_secret.strip().lower() in {
                "local-development-only", "replace-this-before-deployment", "replace-with-generated-random-value",
            } or len(self.app_secret) < 32:
                raise ValueError("APP_SECRET must be a unique secret of at least 32 characters in production.")
            if self.database_url.startswith("sqlite"):
                raise ValueError("Production requires PostgreSQL; SQLite is for local development only.")
            database_password = make_url(self.database_url).password
            if not database_password or database_password.strip().lower() in {
                "local-compose-password", "replace-with-generated-random-value", "password",
            } or len(database_password) < 32:
                raise ValueError("Production requires a unique PostgreSQL password of at least 32 characters.")
            if not self.redis_url:
                raise ValueError("Production requires REDIS_URL for distributed rate limiting.")
            origins = [self.frontend_url, *self.frontend_urls.split(",")]
            if any(urlparse(origin.strip()).scheme != "https" for origin in origins if origin.strip()):
                raise ValueError("Production frontend URLs must use HTTPS.")
            if not self.admin_email_allowlist.strip() or not self.initial_admin_emails.strip():
                raise ValueError("Production requires an explicit admin allowlist and initial admin list.")
            if not self.initial_admins.issubset(self.admin_emails):
                raise ValueError("Every initial admin must also be in ADMIN_EMAIL_ALLOWLIST.")
            if self.ocr_enabled and not self.openrouter_api_key:
                raise ValueError("OPENROUTER_API_KEY is required when OCR_ENABLED is true in production.")
        return self


settings = Settings()
