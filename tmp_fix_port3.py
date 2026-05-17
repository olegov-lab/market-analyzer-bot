f = open('/root/market-analyzer-bot/docker-compose.yml', 'r')
c = f.read()
f.close()
import re
c = re.sub(r'\n\s*ports:\s*\n\s*\n', '\n', c)
c = re.sub(r'\n\s*ports:\s*\n', '\n', c)
# Also remove empty redis ports
c = re.sub(r'\n\s*ports:\s*\n\s*\n', '\n', c)
f = open('/root/market-analyzer-bot/docker-compose.yml', 'w')
f.write(c)
f.close()
print('OK')
