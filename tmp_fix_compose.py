f = open('/root/market-analyzer-bot/docker-compose.yml', 'r')
c = f.read()
f.close()
# Add back port mapping, bound to localhost only
c = c.replace('volumes:\n      - pgdata:/var/lib/postgresql/data', 'ports:\n      - "127.0.0.1:5432:5432"\n    volumes:\n      - pgdata:/var/lib/postgresql/data')
# Also for redis
c = c.replace('healthcheck:\n      test: ["CMD", "redis-cli", "ping"]', 'ports:\n      - "127.0.0.1:6379:6379"\n    healthcheck:\n      test: ["CMD", "redis-cli", "ping"]')
f = open('/root/market-analyzer-bot/docker-compose.yml', 'w')
f.write(c)
f.close()
print('FIXED')
