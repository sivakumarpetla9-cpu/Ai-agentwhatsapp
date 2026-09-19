from app.core.config import Settings


def test_default_settings() -> None:
    settings = Settings(
        POSTGRES_SERVER="localhost",
        POSTGRES_PORT=5432,
        POSTGRES_USER="postgres",
        POSTGRES_PASSWORD="secretpassword",
        POSTGRES_DB="test_db",
    )
    assert settings.PROJECT_NAME == "WhatsApp Dine-In Ordering API"
    assert settings.API_V1_STR == "/api/v1"
    assert settings.DATABASE_URL == "postgresql+asyncpg://postgres:secretpassword@localhost:5432/test_db"
    assert settings.SYNC_DATABASE_URL == "postgresql+psycopg://postgres:secretpassword@localhost:5432/test_db"


def test_custom_database_url_override() -> None:
    custom_url = "sqlite+aiosqlite:///test.db"
    settings = Settings(CUSTOM_DATABASE_URL=custom_url)
    assert settings.DATABASE_URL == custom_url


def test_render_postgres_url_normalization() -> None:
    render_url = "postgres://restaurant_user:prod_secret@dpg-c123-a.oregon-postgres.render.com/restaurant_db"
    settings = Settings(DATABASE_URL=render_url)
    assert settings.DATABASE_URL == "postgresql+asyncpg://restaurant_user:prod_secret@dpg-c123-a.oregon-postgres.render.com/restaurant_db"
    assert settings.SYNC_DATABASE_URL == "postgresql+psycopg://restaurant_user:prod_secret@dpg-c123-a.oregon-postgres.render.com/restaurant_db"


def test_production_rejects_sqlite() -> None:
    import pytest
    with pytest.raises(ValueError, match="SQLite is not permitted in production"):
        Settings(
            ENVIRONMENT="production",
            DEBUG=False,
            SECRET_KEY="A" * 32,
            DATABASE_URL="sqlite+aiosqlite:///production.db",
        )


def test_production_accepts_render_postgres() -> None:
    render_url = "postgres://restaurant_user:prod_secret@dpg-c123-a.oregon-postgres.render.com/restaurant_db"
    settings = Settings(
        ENVIRONMENT="production",
        DEBUG=False,
        SECRET_KEY="A" * 32,
        DATABASE_URL=render_url,
        WHATSAPP_MODE="mock",
    )
    assert settings.DATABASE_URL.startswith("postgresql+asyncpg://")
    assert not settings.DEBUG

