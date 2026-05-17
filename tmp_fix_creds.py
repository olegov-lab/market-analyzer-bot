import re
with open('/root/market-analyzer-bot/docker-compose.yml', 'r') as f:
    c = f.read()
pwd = open('/root/.pg_pass_new').read().strip()
c = c.replace('postgres:postgres@', 'postgres:' + pwd + '@')
with open('/root/market-analyzer-bot/docker-compose.yml', 'w') as f:
    f.write(c)
print('CREDS_UPDATED')
