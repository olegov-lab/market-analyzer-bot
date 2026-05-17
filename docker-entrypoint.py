"""Entrypoint: ensure DB exists, run migrations, optionally seed history, then exec target command."""
import os
import sys
import subprocess


def _ensure_database() -> None:
    """Create the target database if it does not exist."""
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return
    try:
        from urllib.parse import urlparse
        parsed = urlparse(db_url)
        db_name = parsed.path.lstrip("/")
        # connect to default 'postgres' database to check/create target
        base_url = f"{parsed.scheme}://{parsed.netloc}/postgres"
        import asyncpg
        import asyncio
        async def check() -> None:
            conn = await asyncpg.connect(base_url)
            exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
            if not exists:
                await conn.execute(f'CREATE DATABASE "{db_name}"')
                print(f"[entrypoint] Created missing database: {db_name}")
            else:
                print(f"[entrypoint] Database {db_name} already exists")
            await conn.close()
        asyncio.run(check())
    except Exception as exc:
        print(f"[entrypoint] Database check skipped ({exc})")


def main() -> None:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    _ensure_database()

    if os.environ.get("SKIP_MIGRATIONS", "0") != "1":
        print("[entrypoint] Running migrations...")
        result = subprocess.run(
            [sys.executable, "-m", "scripts.migrate"],
            capture_output=False,
        )
        if result.returncode != 0:
            print(f"[entrypoint] Migration failed (exit code {result.returncode}), continuing...")
        else:
            print("[entrypoint] Migrations OK")

    if os.environ.get("SEED_HISTORY", "0") == "1":
        print("[entrypoint] Seeding history...")
        result = subprocess.run(
            [sys.executable, "-m", "btcbot.seed_history"],
            capture_output=False,
        )
        if result.returncode == 0:
            print("[entrypoint] Seed OK")
        else:
            print(f"[entrypoint] Seed failed (exit code {result.returncode}), continuing...")

    cmd = sys.argv[1:]
    if cmd:
        os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
