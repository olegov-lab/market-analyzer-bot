#!/usr/bin/env python3
import re
with open('/root/market-analyzer-bot/data/postgresql.conf', 'r') as f:
    c = f.read()
c = c.replace('log_connections = off', 'log_connections = on')
c = c.replace('log_disconnections = off', 'log_disconnections = on')
if 'log_line_prefix' not in c:
    c += "\nlog_line_prefix = '%t [%p]: user=%u,db=%d,client=%h '\n"
with open('/root/market-analyzer-bot/data/postgresql.conf', 'w') as f:
    f.write(c)
print('CONF_UPDATED')
