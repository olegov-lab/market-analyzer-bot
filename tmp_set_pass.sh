#!/bin/bash
PWD=$(python3 /tmp/gen_pass.py)
echo "NEW_PASS=$PWD"
echo "$PWD" > /root/.pg_pass_new
chmod 600 /root/.pg_pass_new
docker exec market-analyzer-bot-postgres-1 psql -U postgres -h localhost -d btcbot -c "ALTER USER postgres WITH PASSWORD '$PWD';"
echo "PASSWORD_CHANGED_OK"
