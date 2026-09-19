from decimal import Decimal
from functools import lru_cache
from typing import List, Optional
from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application Settings loaded from environment variables or .env file.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # General App Configuration
    PROJECT_NAME: str = "WhatsApp Dine-In Ordering API"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "insecure-default-change-in-production"
    BILL_TAX_RATE: Decimal = Decimal("0.00")
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]

    # WhatsApp Cloud API Configuration
    WHATSAPP_MODE: str = "mock"  # "mock" | "meta"
    WHATSAPP_ACCESS_TOKEN: Optional[str] = None
    WHATSAPP_API_TOKEN: Optional[str] = None  # Backward-compatibility alias
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_BUSINESS_ACCOUNT_ID: Optional[str] = None
    WHATSAPP_APP_SECRET: Optional[str] = None
    WHATSAPP_VERIFY_TOKEN: str = "dine_in_webhook_verify_token"
    WHATSAPP_API_VERSION: str = "v21.0"
    WHATSAPP_API_URL: Optional[str] = None
    WHATSAPP_USE_MOCK: bool = True
    WHATSAPP_WEBHOOK_VERIFY_SIGNATURE: bool = False
    WHATSAPP_REQUEST_TIMEOUT: float = 10.0
    DEFAULT_RESTAURANT_ID: Optional[str] = None

    @property
    def is_meta_mode(self) -> bool:
        return self.WHATSAPP_MODE.lower() == "meta" or not self.WHATSAPP_USE_MOCK

    @property
    def effective_whatsapp_token(self) -> Optional[str]:
        return self.WHATSAPP_ACCESS_TOKEN or self.WHATSAPP_API_TOKEN

    @property
    def effective_whatsapp_api_url(self) -> str:
        if self.WHATSAPP_API_URL:
            return self.WHATSAPP_API_URL.rstrip("/")
        version = self.WHATSAPP_API_VERSION.strip()
        if not version.startswith("v"):
            version = f"v{version}"
        return f"https://graph.facebook.com/{version}"

    # PostgreSQL Database Parameters
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "restaurant_ordering"

    # Database Configuration (can be provided via DATABASE_URL or individual parameters)
    DATABASE_URL: Optional[str] = None
    CUSTOM_DATABASE_URL: Optional[str] = None

    # Connection Pool Settings
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_PRE_PING: bool = True

    # Logging Settings
    LOG_LEVEL: str = "INFO"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SYNC_DATABASE_URL(self) -> str:
        """
        Synchronous database URL used by migration tools or sync scripts.
        """
        url = self.DATABASE_URL or ""
        if "postgresql+asyncpg://" in url:
            return url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
        if "sqlite+aiosqlite://" in url:
            return url.replace("sqlite+aiosqlite://", "sqlite://")
        return url.replace("+asyncpg", "").replace("+aiosqlite", "")

    @model_validator(mode="after")
    def validate_and_normalize_configuration(self) -> "Settings":
        """
        Normalize database URLs (e.g. Render's postgres:// to postgresql+asyncpg://)
        and enforce strict security validation when running in production environment
        or when WHATSAPP_MODE=meta.
        """
        # 1. Normalize DATABASE_URL
        raw_db_url = self.DATABASE_URL or self.CUSTOM_DATABASE_URL
        if raw_db_url:
            if raw_db_url.startswith("postgres://"):
                self.DATABASE_URL = raw_db_url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif raw_db_url.startswith("postgresql://") and not raw_db_url.startswith("postgresql+"):
                self.DATABASE_URL = raw_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
            else:
                self.DATABASE_URL = raw_db_url
        else:
            self.DATABASE_URL = (
                f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )

        # 2. Synchronize WHATSAPP_MODE and legacy WHATSAPP_USE_MOCK
        if self.WHATSAPP_MODE.lower() == "meta":
            self.WHATSAPP_USE_MOCK = False
        elif not self.WHATSAPP_USE_MOCK:
            self.WHATSAPP_MODE = "meta"

        # 3. Synchronize WHATSAPP_ACCESS_TOKEN and WHATSAPP_API_TOKEN
        effective_token = self.WHATSAPP_ACCESS_TOKEN or self.WHATSAPP_API_TOKEN
        if effective_token:
            if not self.WHATSAPP_ACCESS_TOKEN:
                self.WHATSAPP_ACCESS_TOKEN = effective_token
            if not self.WHATSAPP_API_TOKEN:
                self.WHATSAPP_API_TOKEN = effective_token

        # 4. Production Security Hardening
        if self.ENVIRONMENT.lower() == "production":
            if self.DEBUG:
                raise ValueError("DEBUG mode must be False in production.")
            if self.SECRET_KEY in (
                "insecure-default-change-in-production",
                "change_this_to_a_secure_secret_key_in_production",
            ) or len(self.SECRET_KEY) < 32:
                raise ValueError(
                    "A secure SECRET_KEY (minimum 32 characters) must be configured in production."
                )
            if "sqlite" in (self.DATABASE_URL or "").lower():
                raise ValueError(
                    "SQLite is not permitted in production. A production PostgreSQL database is required."
                )
            if (
                self.POSTGRES_PASSWORD == "postgres"
                and self.DATABASE_URL
                and ("@localhost" in self.DATABASE_URL or "@127.0.0.1" in self.DATABASE_URL)
            ):
                raise ValueError(
                    "Default POSTGRES_PASSWORD ('postgres') on localhost is not permitted in production."
                )
            if not self.WHATSAPP_USE_MOCK:
                if (
                    not effective_token
                    or not self.WHATSAPP_PHONE_NUMBER_ID
                    or not self.WHATSAPP_APP_SECRET
                ):
                    raise ValueError(
                        "WHATSAPP_ACCESS_TOKEN (or WHATSAPP_API_TOKEN), WHATSAPP_PHONE_NUMBER_ID, "
                        "and WHATSAPP_APP_SECRET must be configured when WHATSAPP_USE_MOCK is False."
                    )

        # In any environment, if WHATSAPP_MODE is explicitly 'meta', enforce required Meta credentials
        if self.WHATSAPP_MODE.lower() == "meta":
            if (
                not effective_token
                or not self.WHATSAPP_PHONE_NUMBER_ID
                or not self.WHATSAPP_APP_SECRET
            ):
                raise ValueError(
                    "WHATSAPP_ACCESS_TOKEN (or WHATSAPP_API_TOKEN), WHATSAPP_PHONE_NUMBER_ID, "
                    "and WHATSAPP_APP_SECRET must be configured when WHATSAPP_MODE='meta'."
                )

        return self


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings factory.
    """
    return Settings()
