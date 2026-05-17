#!/bin/bash
PWD=$(cat /root/.pg_pass_new)

# Update .env
sed -i "s|DATABASE_URL=postgresql://postgres:.*@|DATABASE_URL=postgresql://postgres:${PWD}@|" /root/market-analyzer-bot/.env

# docker-compose collector + scheduler (internal docker network)
sed -i "s|postgresql://postgres:postgres@postgres:5432/btcbot|postgresql://postgres:${PWD}@postgres:5432/btcbot|g" /root/market-analyzer-bot/docker-compose.yml

# docker-compose api + bot (network_mode host)
sed -i "s|postgresql://postgres:postgres@localhost:5432/btcbot|postgresql://postgres:${PWD}@localhost:5432/btcbot|g" /root/market-analyzer-bot/docker-compose.yml

echo "PASSWORDS_UPDATED"

# Switch pg_hba to scram-sha-256
cat > /var/lib/docker/volumes/market-analyzer-bot_pgdata/_data/pg_hba.conf << 'HBA'
# TYPE  DATABASE  USER  ADDRESS        METHOD
local   all       all                   trust
host    all       all     127.0.0.1/32  scram-sha-256
host    all       all     ::1/128       scram-sha-256
host    all       all     172.0.0.0/8   scram-sha-256
host    all       all     10.0.0.0/8    reject
host    all       all     0.0.0.0/0     reject
HBA
chmod 0600 /var/lib/docker/volumes/market-analyzer-bot_pgdata/_data/pg_hba.conf
echo "HBA_UPDATED"
