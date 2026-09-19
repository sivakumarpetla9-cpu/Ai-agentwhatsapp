import asyncio
import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.database.session import check_db_connectivity


async def main() -> None:
    settings = get_settings()
    print(f"Testing database connectivity to: {settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}...")
    try:
        await check_db_connectivity()
        print("[SUCCESS] Database connectivity verified successfully!")
        sys.exit(0)
    except Exception as exc:
        print(f"[FAILED] Database connectivity failed: {exc}")
        print("\nNote: Ensure PostgreSQL is running. If running locally via Docker Compose, run:")
        print("  docker compose up -d postgres")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
