#!/bin/bash
PASS=$(cat /root/.pg_pass_new)
echo "Testing connection with new password..."
PGPASSWORD=$PASS docker exec -i market-analyzer-bot-postgres-1 psql -U postgres -h localhost -d btcbot -c "SELECT count(*) FROM prices;"
echo "DONE"
