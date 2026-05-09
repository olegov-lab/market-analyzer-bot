cd /bot && test -f .env && echo "ENV_OK" || echo "ENV_MISSING" && docker compose build 2>&1 | tail -5 && docker compose up -d --force-recreate 2>&1
