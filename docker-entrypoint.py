"""Entrypoint: run migrations, optionally seed history, then exec the target command."""
import os
import sys
import subprocess


def main() -> None:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

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
