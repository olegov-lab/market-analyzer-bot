#!/usr/bin/env python3
"""BTC Monitor — health check with Telegram alerts. Run via cron every 30 min."""
import subprocess, json, os, sys, urllib.request, urllib.parse
from datetime import datetime, timezone

# Load .env for cron execution (no shell env vars available)
ENV_FILE = "/root/market-analyzer-bot/.env"
if os.path.exists(ENV_FILE):
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)

STATE_FILE = "/root/market-analyzer-bot/data/health_state.json"

def shell(cmd, timeout=10):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()

def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("ALERT_CHAT_ID", "")
    if not token or not chat_id:
        return
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        urllib.request.urlopen(url, data=data, timeout=10)
    except Exception as e:
        print(f"[HEALTH] Telegram send failed: {e}")

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_oom_ts": "", "last_low_mem_ts": "", "container_start_times": {}}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def get_container_info():
    """Return dict of container -> (status, started_at in ms)."""
    raw = shell("docker inspect $(docker ps -q) --format '{{.Name}}|{{.State.Status}}|{{.State.StartedAt}}' 2>/dev/null")
    info = {}
    for line in raw.split("\n"):
        if not line:
            continue
        parts = line.split("|")
        if len(parts) != 3:
            continue
        name = parts[0].lstrip("/")
        info[name] = (parts[1], parts[2])
    return info

def check_oom(state):
    """Check for OOM kills since last run."""
    oom_log = shell("dmesg 2>/dev/null | grep -i 'oom-kill' | tail -5", timeout=5)
    if not oom_log:
        return state, []

    new_kills = []
    lines = oom_log.split("\n")
    last_known = state.get("last_oom_ts", "")

    BOT_CONTAINERS = ["postgres", "redis", "collector", "scheduler", "api", "bot"]
    for line in lines:
        if "oom-kill" in line.lower() or "killed process" in line.lower():
            ts = line[:20].strip()
            if ts > last_known:
                line_lower = line.lower()
                # Skip OOM from non-bot processes (MySQL, system, etc.)
                if not any(c in line_lower for c in BOT_CONTAINERS):
                    continue
                proc = "unknown"
                for part in line.split():
                    if "docker" in part or "btc" in part or "market" in part:
                        proc = part
                        break
                new_kills.append(f"OOM: {proc} — {line[:120]}")

    if new_kills:
        state["last_oom_ts"] = lines[-1][:20].strip()
    return state, new_kills

def check_low_memory(state):
    """Alert if available memory < 20%."""
    mem = shell("free -m | awk '/Mem:/ {print $7 \" \" $2}'")
    try:
        avail, total = map(int, mem.split())
        pct = round(avail / total * 100, 1)
    except ValueError:
        return state, False, 100

    cooldown = state.get("last_low_mem_ts", "")
    now = datetime.now(timezone.utc).isoformat()

    if pct < 20 and (not cooldown or (datetime.fromisoformat(now) - datetime.fromisoformat(cooldown)).total_seconds() > 3600):
        state["last_low_mem_ts"] = now
        return state, True, pct

    if pct >= 20:
        state["last_low_mem_ts"] = ""
    return state, False, pct

def check_container_restarts(state):
    """Detect container restarts since last run."""
    current = get_container_info()
    prev = state.get("container_start_times", {})
    restarts = []

    for name, (status, started) in current.items():
        prev_started = prev.get(name, "")
        if prev_started and prev_started != started and "Up" in status:
            restarts.append(f"{name} перезапущен (был: {prev_started[:19]}, стал: {started[:19]})")

    state["container_start_times"] = {n: s for n, (_, s) in current.items()}
    return state, restarts

checks = {}

# Disk
df = shell("df / | tail -1 | awk '{print $5 \" \" $4}'")
pct, avail = df.split()
checks["disk_pct"] = int(pct.replace("%", ""))
checks["disk_avail_kb"] = int(avail)

# Memory
mem = shell("free -m | awk '/Mem:/ {print $3 \" \" $2 \" \" $7}'")
used, total, avail_mb = map(int, mem.split())
checks["mem_pct"] = round(used / total * 100, 1)
checks["mem_avail_pct"] = round(avail_mb / total * 100, 1)
checks["mem_used_mb"] = used
checks["mem_total_mb"] = total
checks["swap"] = shell("free -m | awk '/Swap:/ {print $3}'")

# Docker
ps = shell("docker ps --format '{{.Names}} {{.Status}}'")
lines = [l for l in ps.split("\n") if l]
checks["containers_total"] = len(lines)
checks["containers_running"] = sum(1 for l in lines if "Up" in l)
checks["containers_healthy"] = sum(1 for l in lines if "healthy" in l)
checks["containers_unhealthy"] = sum(1 for l in lines if "unhealthy" in l)

# API health
api = shell("curl -sf -o /dev/null -w '%{http_code}' http://localhost:8000/health 2>/dev/null || echo '000'", timeout=15)
checks["api_http"] = api

# Tunnel
tunnel = shell("curl -sf -o /dev/null -w '%{http_code}' https://btc.smartmarkettoday.com/miniapp 2>/dev/null || echo '000'", timeout=15)
checks["tunnel_http"] = tunnel

# Load
load = shell("cat /proc/loadavg | awk '{print $1, $2, $3}'")
checks["load_1m"], checks["load_5m"], checks["load_15m"] = map(float, load.split())

state = load_state()

# Check OOM
state, oom_kills = check_oom(state)
if oom_kills:
    checks["oom_kills"] = oom_kills

# Check low memory
state, low_mem, avail_pct = check_low_memory(state)
checks["mem_low"] = low_mem

# Check container restarts
state, restarts = check_container_restarts(state)
if restarts:
    checks["container_restarts"] = restarts

# Build alerts
alerts = []
telegram_msgs = []

if checks["disk_pct"] > 85:
    alerts.append("DISK_LOW")
    telegram_msgs.append(f"<b>Docker USAGE</b> {checks['disk_pct']}%")

if low_mem:
    alerts.append("MEM_LOW")
    telegram_msgs.append(f"<b>Memory MARGIN</b> {avail_pct}% free")

if checks["mem_pct"] > 90:
    alerts.append("MEM_HIGH")
    telegram_msgs.append(f"<b>Memory high</b> {checks['mem_pct']}%")

if api != "200":
    alerts.append("API_DOWN")
    telegram_msgs.append(f"<b>API DOWN</b> (HTTP {api})")

if tunnel != "200":
    alerts.append("TUNNEL_DOWN")
    telegram_msgs.append(f"<b>Cloudflare tunnel error</b> (HTTP {tunnel})")

if oom_kills:
    alerts.append("OOM_KILL")
    for k in oom_kills:
        telegram_msgs.append(f"<b>OOM killed container</b> {k}")

if restarts:
    alerts.append("CONTAINER_RESTART")
    for r in restarts:
        telegram_msgs.append(f"<b>Container restarted</b> {r}")

if checks["containers_unhealthy"]:
    alerts.append("UNHEALTHY_CONTAINERS")
if checks["containers_running"] < 6:
    alerts.append("MISSING_CONTAINERS")

checks["alerts"] = alerts
checks["ts"] = datetime.now(timezone.utc).isoformat()

save_state(state)

path = "/root/market-analyzer-bot/data/health.json"
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f:
    json.dump(checks, f, indent=2)

if telegram_msgs:
    msg = f"<b>BTC Monitor Alert</b>\n{chr(10)}".join(telegram_msgs)
    send_telegram(msg)

if alerts:
    print(f"[HEALTH] ALERTS: {', '.join(alerts)}")
    sys.exit(1)
else:
    print(f"[HEALTH] OK — disk:{checks['disk_pct']}% mem:{checks['mem_pct']}% avail:{avail_pct}% api:{api} tunnel:{tunnel}")
