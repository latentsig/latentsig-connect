from pathlib import Path
from urllib.parse import urlparse
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
        if self.app_env.lower() == "production":
            if self.app_secret in {"local-development-only", "replace-this-before-deployment"} or len(self.app_secret) < 32:
                raise ValueError("APP_SECRET must be a unique secret of at least 32 characters in production.")
            if self.database_url.startswith("sqlite"):
                raise ValueError("Production requires PostgreSQL; SQLite is for local development only.")
            if not self.redis_url:
                raise ValueError("Production requires REDIS_URL for distributed rate limiting.")
            origins = [self.frontend_url, *self.frontend_urls.split(",")]
            if any(urlparse(origin.strip()).scheme != "https" for origin in origins if origin.strip()):
                raise ValueError("Production frontend URLs must use HTTPS.")
            if not self.admin_email_allowlist.strip() or not self.initial_admin_emails.strip():
                raise ValueError("Production requires an explicit admin allowlist and initial admin list.")
            if not self.initial_admins.issubset(self.admin_emails):
                raise ValueError("Every initial admin must also be in ADMIN_EMAIL_ALLOWLIST.")
        return self


settings = Settings()
