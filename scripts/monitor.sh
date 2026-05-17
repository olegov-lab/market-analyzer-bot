#!/bin/bash
# monitor.sh — запускать в 4 параллельных терминалах во время стресс-теста
# Terminal 1: Пул соединений PostgreSQL
# Terminal 2: Память/SWAP
# Terminal 3: Потребление RAM по контейнерам
# Terminal 4: HTTP ошибки в реальном времени

echo "=== Terminal 1: PostgreSQL connection pool & locks ==="
echo "watch -n 1 'docker exec market-analyzer-bot-postgres-1 psql -U postgres -h localhost -d btcbot -c \"SELECT count(*) AS active_conns FROM pg_stat_activity WHERE state = '"'"'active'"'"' AND pid <> pg_backend_pid();\"'"
echo ""
echo "=== Terminal 2: Memory & SWAP ==="
echo "watch -n 1 'free -h; echo; echo SWAP详细:; swapon --show; vmstat 1 1 | tail -1 | awk \"{print \\\"swap_in/s:\\\" \\\$7 \\\" swap_out/s:\\\" \\\$8}\" '"
echo ""
echo "=== Terminal 3: Container RAM usage ==="
echo "watch -n 2 'docker stats --no-stream --format \"table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}\" | sort -k3 -h'"
echo ""
echo "=== Terminal 4: HTTP errors & latency ==="
echo 'watch -n 2 "tail -100 /var/lib/docker/containers/*/*-json.log 2>/dev/null | grep -E \"HTTP/1.1\" | grep -v \"200 OK\" | tail -20"'
echo ""
echo ""
echo "=== Дополнительные команды ==="

cat << 'CMDS'
# Pool usage (подробно):
docker exec market-analyzer-bot-postgres-1 psql -U postgres -h localhost -d btcbot -c "
SELECT state, count(*) as count
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
GROUP BY state
ORDER BY count DESC;"

# Активные запросы (не idle):
docker exec market-analyzer-bot-postgres-1 psql -U postgres -h localhost -d btcbot -c "
SELECT pid, usename, query_start, now() - query_start as duration, state, substring(query, 1, 80)
FROM pg_stat_activity
WHERE state = 'active' AND pid <> pg_backend_pid()
ORDER BY query_start;"

# Блокировки (deadlocks):
docker exec market-analyzer-bot-postgres-1 psql -U postgres -h localhost -d btcbot -c "
SELECT blocked_locks.pid AS blocked_pid,
       blocked_activity.usename AS blocked_user,
       blocking_locks.pid AS blocking_pid,
       blocking_activity.usename AS blocking_user,
       blocked_activity.query AS blocked_query,
       blocking_activity.query AS blocking_query
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks ON blocking_locks.locktype = blocked_locks.locktype
  AND blocking_locks.DATABASE IS NOT DISTINCT FROM blocked_locks.DATABASE
  AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
  AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
  AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
  AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
  AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
  AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
  AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
  AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
  AND blocking_locks.pid <> blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.GRANTED;"

# OOM killer в реальном времени:
journalctl -f -k -n 0 --since "1 min ago" | grep -i "oom\|killed\|postgres\|out of memory"

# Swap usage per process (top consumers):
for pid in $(ps -eo pid:1,comm:15,%mem:5 --sort=-%mem | head -10 | awk '{print $1}'); do
  swap=$(grep -i "Swap:" /proc/$pid/status 2>/dev/null | awk '{print $2}');
  if [ "$swap" != "0" ] && [ -n "$swap" ]; then
    echo "PID $pid: $(ps -p $pid -o comm= 2>/dev/null) SWAP: ${swap}kB";
  fi;
done

# Docker events (restarts/OOM):
docker events --filter 'type=container' --filter 'event=oom' --filter 'event=die' --since 1m

# Connection pool hit ratio (из asyncpg):
# Включить логирование пула: asyncpg создаёт логи при pool_stats
# watch -n 2 "docker logs --tail 20 market-analyzer-bot-api-1 2>&1 | grep -i 'pool\|acquire\|release\|timeout'"
CMDS
