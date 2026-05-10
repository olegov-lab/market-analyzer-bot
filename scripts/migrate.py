"""Run Alembic migrations.

Usage:
    python scripts/migrate.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alembic.config import Config
from alembic.command import upgrade, stamp
from alembic.util.exc import CommandError

from btcbot.config import settings


def main() -> None:
    url = settings.database_url
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("+asyncpg", "")

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", url)

    try:
        stamp(alembic_cfg, "head")
        print("DB already at head (stamped)")
    except CommandError:
        print("Fresh DB — running migrations...")
        upgrade(alembic_cfg, "head")
        print("Migrations complete")


if __name__ == "__main__":
    main()
