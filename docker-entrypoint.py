"""Entrypoint: run migrations, then exec the target command."""
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

    cmd = sys.argv[1:]
    if cmd:
        os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
