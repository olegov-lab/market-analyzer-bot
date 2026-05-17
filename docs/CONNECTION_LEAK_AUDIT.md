# Connection Leak Audit Checklist

## 1. Паттерн `pool.acquire()` — везде ли async with?

### ПЛОХО (ручное acquire/release — можно забыть release):
```python
conn = await pool.acquire()
try:
    await conn.execute("SELECT ...")
finally:
    await pool.release(conn)  # легко забыть или пропустить при раннем return
```

### ХОРОШО (контекстный менеджер — гарантированное возвращение в пул):
```python
async with pool.acquire() as conn:
    await conn.execute("SELECT ...")
# conn автоматически возвращается в пул при выходе из блока
```

### Текущий код — все 60+ мест используют `async with` ✅
**Файлы:** `btcbot/db.py:54` и далее, `backend/api.py:319`, `btcbot/game.py:471`

---

## 2. Время жизни соединения — не держать conn во время AI-вызова

### ПЛОХО (соединение занято всё время AI-запроса):
```python
async with pool.acquire() as conn:
    price = await conn.fetchval("SELECT price FROM prices ORDER BY time DESC LIMIT 1")
    # AI-запрос 5-30 секунд — соединение простаивает в пуле
    answer = await call_ai(price)
    await conn.execute("INSERT INTO answers ...", answer)
```

### ХОРОШО (acquire только на SQL, AI — вне блока):
```python
async with pool.acquire() as conn:
    price = await conn.fetchval("SELECT price FROM prices ORDER BY time DESC LIMIT 1")
# conn вернулся в пул
answer = await call_ai(price)  # AI может длиться минуты — не блокирует пул
async with pool.acquire() as conn:
    await conn.execute("INSERT INTO answers ...", answer)
```

### Текущий код:
- **`/miniapp/ask` (api.py:683-719)**: AI-вызов вне `pool.acquire()` — данные берутся из Redis кэша ✅
- **`_run_ask_task`**: читает market context через Redis, не держит conn ❓
- **`_fetch_timothy_analysis`**: не использует БД внутри — все данные переданы параметрами ✅

---

## 3. Таймауты acquire — чтобы не виснуть в очереди пула

### Рекомендация: добавлять timeout при acquire
```python
async with pool.acquire(timeout=5.0) as conn:  # ждать conn не более 5с
    await conn.execute("...")
```

### Текущий код: timeout НЕ указан нигде ❌
Если все 3 соединения заняты, очередной acquire будет ждать бесконечно.
Это приведёт к зависшим запросам и HTTP 500 по таймауту uvicorn (30с).

---

## 4. Размер пула — достаточно ли max_size?

### Текущее: `max_size=3` на весь проект 🔴
С 3 соединениями:
- 1 занято collector (сохранение цен)
- 1 занято scheduler (аналитика)
- 1 занято api/bot → всё, пул исчерпан

При пике в 200 пользователей каждое соединение будет ждать в очереди.

### Рекомендация:
```python
# Для API (api.py) — отдельный пул
self.pool = await asyncpg.create_pool(self.dsn, min_size=2, max_size=10)

# Для бота (bot/main.py) — отдельный пул
self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)

# Для collector/scheduler — можно оставить min=1, max=3
```

### Итого: разнести пулы по сервисам:
| Сервис | min | max | Обоснование |
|--------|-----|-----|-------------|
| api | 2 | 10 | Пиковые нагрузки от Mini App |
| bot | 1 | 5 | Пользовательские команды |
| collector | 1 | 2 | Пакетная вставка цен |
| scheduler | 1 | 2 | Фоновые задачи |

---

## 5. Мониторинг пула asyncpg

Добавить в `db.py`:
```python
async def pool_stats(self) -> dict:
    if not self.pool:
        return {}
    return {
        "min": self.pool._minsize,
        "max": self.pool._maxsize,
        "current": self.pool._pool.qsize(),
        "free": self.pool._queue.qsize(),  # не документировано
    }
```

И endpoint `/debug/pool` (только для админа):
```python
@app.get("/debug/pool")
async def debug_pool():
    return await db.pool_stats()
```

---

## 6. Транзакции — не блокировать долго

### ПЛОХО (долгая транзакция):
```python
async with pool.acquire() as conn:
    async with conn.transaction():
        # 10 INSERT-ов с паузами
        for item in items:
            await conn.execute("INSERT ...", item)
            await asyncio.sleep(0.1)  # 🔴 транзакция открыта!
```

### ХОРОШО (транзакция только на критическую секцию):
```python
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("UPDATE ...")
        await conn.execute("INSERT ...")
    # транзакция закрыта, conn вернулся в пул
```

### Текущий код — `close_position` (db.py:736):
```python
async with self.pool.acquire() as conn:
    async with conn.transaction():
        ...
```
Внутри транзакции только SQL — нет async-пауз ✅

---

## 7. MATERIALIZED VIEW REFRESH — блокировка таблиц

### `refresh_leaderboard` (db.py:774):
```python
async with self.pool.acquire() as conn:
    await conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY leaderboard")
```
Использует `CONCURRENTLY` ✅ — не блокирует чтение.
Но требует уникального индекса на вьюхе — если его нет, `CONCURRENTLY` упадёт с ошибкой.
`get_leaderboard` (db.py:781) — обычный SELECT, locks не создаёт ✅

---

## 8. AI-блокировки — не держать GIL

### Текущий код:
- `_run_ask_task` — запускается в `asyncio.create_task` ✅ (фоновый)
- AI-вызовы через `httpx.AsyncClient` / `openai.AsyncOpenAI` ✅ (асинхронные)
- `run_in_executor` для LightGBM (analyzer.py) ✅ (вынесено из main-thread)

### Проблемное место: `_predict_4h` (analyzer.py:623)
```python
loop = asyncio.get_event_loop()
prediction = await loop.run_in_executor(None, model.predict, features)
```
Это НЕ блокирует соединения БД, но нагружает CPU.

---

## 9. Redis как буфер для игр

### Текущая архитектура:
- **Mining cooldown**: хранится в Redis с TTL ✅
- **Roulette cooldown**: Redis с TTL ✅
- **Roulette history**: Redis list ✅
- **AI task results**: Redis с TTL 600с ✅
- **Ask tasks**: Redis очередь ✅

Это правильно — игровые сессии не нагружают PostgreSQL лишними записями.
Основная БД используется только для:
- `add_stars` (после игры)
- `mine_click` (сохранение сатошей)
- `roulette_spin` (сохранение результата)

---

## ИТОГО: 3 критических finding

| # | Проблема | Серьёзность | Фикс |
|---|----------|-------------|------|
| 1 | `max_size=3` на все сервисы | 🔴 HIGH | Разнести пулы, api=10, bot=5 |
| 2 | Нет `timeout` в acquire | 🟠 MEDIUM | Добавить `acquire(timeout=5)` |
| 3 | Нет мониторинга пула | 🟡 LOW | Добавить `/debug/pool` endpoint |
