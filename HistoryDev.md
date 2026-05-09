# История разработки — Market Analyzer Bot

## Сессия: Проектирование Telegram-бота для Bitcoin

### Участники
- **Prompt-Master** — создание промпта для архитектора
- **Market-Brain** — финансовый анализ, временные сигналы, индикаторы
- **Sigma-Architect** — проектирование архитектуры

### 1. Prompt-Master → промпт для Sigma-Architect
Prompt-Master составил структурированный промпт с разделами: модули системы, API и интеграции, БД, пайплайн данных, архитектура и масштабирование, безопасность.

### 2. Market-Brain → источники данных и метрики
- **Источники:** Binance (WebSocket), Glassnode (on-chain), CoinGecko (backup), CoinGlass (фьючерсы)
- **3 группы индикаторов:** технические (RSI, MACD, MA, Bollinger), on-chain (MVRV, SOPR, NUPL, Puell), sentiment (Fear & Greed, Funding Rate)
- **Прогнозы:** 4H (краткосрок), 1W (среднесрок), >1W (контекст)
- **Алерты:** RSI экстремумы, MA crossover, Fibonacci, MVRV, Funding Rate, аномалии объёма
- **Риски:** манипуляции, лаг данных, black swan, корреляция с TradFi, overfitting

### 3. Market-Brain → временные сигналы
- **Сессии:** Азия (00–09), Европа (07–16), США (13–22), Overlap EU/US (13–16, 60% объёма)
- **Почасовые сигналы (UTC):**
  - 06:00–08:00 → BUY | 08:00–12:00 → BUY/HOLD
  - 13:00–15:00 → BUY | 15:00–17:00 → SELL
  - 19:00–21:00 → BUY | 21:00–22:00 → SELL
  - 23:00–00:00 → BUY | 00:00–04:00 → HOLD/SELL
  - 04:00–06:00 → HOLD
- **Дни недели:** Пн–Чт трендовые, Пт фиксация, Сб–Вс избегать
- **Алерты:** 15 мин (06:00–22:00, ±0.5%), 60 мин (22:00–06:00, ±1.5%), weekend — только объём >3× avg

### 4. Итоговый промпт → Sigma-Architect
Объединённый промпт передан архитектору. Включает все разделы: модули, API, БД, пайплайн, аналитический движок, временные сигналы, безопасность.

### 5. Sigma-Architect — спроектированная архитектура

#### 5.1 Схема компонентов
```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker / systemd                          │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  Telegram    │  │  Collector   │  │   Analyzer Engine    │   │
│  │  Interface   │  │  (ws/rest)   │  │  (indicators / ML)   │   │
│  │  (aiogram)   │  │              │  │                      │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘   │
│         │                 │                      │               │
│  ┌──────┴───────┐  ┌──────┴───────┐  ┌──────────┴───────────┐  │
│  │  Alert       │  │  Scheduler   │  │   Internal REST API  │  │
│  │  Manager     │  │  (apsched)   │  │   (uvicorn/fastapi)  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │               │
│  ┌──────┴─────────────────┴──────────────────────┴───────────┐  │
│  │                     Redis  (cache / pubsub / queue)         │  │
│  └──────────────────────────────┬──────────────────────────────┘  │
│                                 │                                 │
│  ┌──────────────────────────────┴──────────────────────────────┐  │
│  │          PostgreSQL + TimescaleDB  (storage)                │  │
│  └─────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

#### 5.2 Модули (6 микросервисов)
1. **Telegram Interface** — aiogram 3.x, webhook (prod) / polling (dev)
2. **Collector** — WebSocket Binance + REST CoinGecko, публикует в Redis pub/sub
3. **Analyzer Engine** — 3 группы индикаторов + ML (LightGBM → ONNX)
4. **Scheduler** — APScheduler, триггеры 1m/1h/1d на анализ и алерты
5. **Alert Manager** — подписан на Redis, проверяет пороги, шлёт через Telegram
6. **Internal REST API** — FastAPI (порт 9090), `/health`, `/metrics`, `/models`

#### 5.3 База данных
- **PostgreSQL 16 + TimescaleDB 2.x** — hypertable `prices`, continuous aggregates `candles_1m`, retention policy
- Таблицы: prices, users, subscriptions, predictions, alerts, onchain_metrics
- Retention: raw prices — 7 дней, candles_1m — 90 дней, candles_1h — 1 год

#### 5.4 Пайплайн данных
```
Binance WS → Collector → Redis pub:price → DB Writer → TimescaleDB
                                                         ↓
Glassnode REST → Scheduler → onchain_metrics            ↓
                                                  Scheduler (1m)
                                                         ↓
                                              continuous aggregate candles_1m
                                                         ↓
                                              indicator calculation (pandas_ta)
                                                         ↓
                                              feature vector → ML model → prediction
                                                         ↓
                                              Alert Manager → Redis queue → Telegram
```

#### 5.5 ML-пайплайн
- **Модель:** LightGBM → ONNX, 24 признака (тех. + on-chain + временные)
- **Прогнозы:** short-term 4H (диапазон + вероятность), mid-term 1W (rule-based)
- **Обучение:** раз в неделю offline

#### 5.6 Алерты и временные сигналы
- Day (06-22 UTC): интервал 15 мин, чувствительность ±0.5%
- Night (22-06 UTC): интервал 60 мин, чувствительность ±1.5%
- Weekend: только при объёме >3× avg
- Сессии: Asia (HOLD/SELL), Europe (BUY/HOLD), US overlap (BUY)

#### 5.7 Безопасность
- `.env` + pydantic-settings для secrets
- Graceful shutdown (SIGTERM → flush → close)
- Docker Compose с `restart: unless-stopped` + HEALTHCHECK
- Логирование loguru (JSON, ротация 100MB, 7 дней)

### 6. Rapid-Dev — реализация

#### 6.1 Созданные модули (btcbot/)

| Модуль | Файл | Назначение |
|---|---|---|
| **Config** | `btcbot/config.py` | Pydantic-settings: TELEGRAM_BOT_TOKEN, DATABASE_URL, REDIS_URL, GLASSNODE_API_KEY, COINGECKO_API_KEY |
| **Models** | `btcbot/models.py` | PriceRecord, Candle, IndicatorSet, Prediction, Alert, User, Subscription, OnchainMetric (pydantic) |
| **DB** | `btcbot/db.py` | asyncpg + TimescaleDB: hypertable prices, continuous aggregate candles_1m, retention policy. Таблицы: users, subscriptions, predictions, alerts, onchain_metrics |
| **Collector** | `btcbot/collector.py` | Binance WebSocket (aggTrade + depth5), CoinGecko REST (simple/price), Glassnode (on-chain metrics), CoinGlass (funding rate). Асинхронный сбор с fallback и реконнектом |
| **Analyzer** | `btcbot/analyzer.py` | pandas_ta: RSI(14), MACD(12,26,9), MA(50/100/200), Bollinger Bands(20,2), OBV. On-chain: MVRV, SOPR, NUPL. Sentiment: Fear & Greed, Funding Rate. ML: LightGBM-прогноз на 4H |
| **Alerts** | `btcbot/alerts.py` | День/ночь фильтры (+0.5%/+1.5%), weekend volume gate, RSI экстремумы (25/80), MA crossover (50×200), volume spike (>3×avg) |
| **Scheduler** | `btcbot/scheduler.py` | APScheduler: индикаторы каждые 5м, прогноз каждые 30м, алерты 15м (днём) / 60м (ночью), on-chain каждый час |

#### 6.2 Дополненные модули

**Telegram Interface** (`bot/main.py`):
- `/btc` — текущая цена BTC + значения ключевых индикаторов
- `/predict` — последний прогноз (направление, диапазон, уверенность)
- `/subscribe` — inline-кнопки для подписки на типы алертов (RSI, MA Cross, Volume, On-chain)
- `/alerts` — просмотр и отписка от текущих подписок

**Internal REST API** (`backend/api.py`):
- `GET /btc/price` — текущая цена BTC из Redis/БД
- `GET /btc/indicators` — текущие значения всех индикаторов
- `GET /btc/predict` — последний сгенерированный прогноз
- `POST /btc/alert/subscribe` — создание подписки на алерт

#### 6.3 Инфраструктура
- **Dockerfile** — мультистейдж билд с python:3.12-slim
- **docker-compose.yml** — 6 сервисов: postgres+timescale, redis, collector, scheduler, api, bot
- **requirements.txt** — исправлены конфликты версий (pandas, numpy, pandas-ta); добавлены: asyncpg, APScheduler, loguru, redis, pydantic-settings, websockets, scikit-learn, lightgbm, onnxruntime
- Установлены все зависимости (pip install), модули проверены на импорт
- Исправлена Docker-сеть: DATABASE_URL и REDIS_URL переопределены через `environment:` в docker-compose.yml (service name вместо localhost)
- Удалён устаревший атрибут `version` из docker-compose.yml

#### 6.4 Запуск проекта
- **Docker:** `docker-compose up` (весь стек: postgres, redis, collector, scheduler, api, bot)
- **Без Docker:**
  ```bash
  python -m btcbot.collector    # сборщик данных
  python -m btcbot.scheduler    # планировщик
  uvicorn backend.api:app       # REST API (порт 9090)
  python bot/main.py            # Telegram бот
  ```

### 7. Реализация полной системы прогнозов (Market-Brain → Rapid-Dev)

#### 7.1 Short-term 4H — ML модель
- **24 признака:** 8 ценовых (return, volatility, volume, BB%, MA distance), 8 технических (RSI, MACD, ATR, ADX, Williams %R), 4 временных (sin/cos), 4 on-chain прокси (funding rate, L/S ratio)
- **Модель:** LightGBM (3 класса: BUY/HOLD/SELL), lazy-load, retrain раз в неделю
- **Диапазон:** ATR × 2.5 = 95% доверительный интервал
- **Зоны ликвидности:** volume profile + локальные экстремумы ±2%
- **Confidence:** `p_direction * (1 - entropy / log(3))`

#### 7.2 Mid-term 1W — Rule-based on-chain
- 5 метрик с весами: MVRV (30%), SOPR (20%), NUPL (20%), Puell (15%), RHODL (15%)
- Фазы: ACCUMULATION (score>0.4), MARKUP (0.1-0.4), DISTRIBUTION (-0.1-0.1), MARKDOWN (<-0.1)

#### 7.3 Long-term — Контекст
- MVRV Z-Score, 200W MA, халвинг, STH-SOPR, Reserve Risk
- Только информационно, без прогноза направления

#### 7.4 Формат /predict
```
Short-term: BUY/SELL/HOLD + цель $X–$Y + вероятность + зоны ликвидности
Mid-term: фаза цикла + score + ключевые on-chain метрики
Long-term: контекст (200W MA, халвинг)
```
При недостатке данных — ⏳ с оценкой времени ожидания

#### 7.5 Технические изменения
- **analyzer.py** — полный рефакторинг: `_build_4h_candles()`, `_compute_24_features()`, `_predict_4h()`, `_predict_1w()`, `_predict_long()`, `_load_or_train_model()`, `_liquidity_zones()`
- **models.py** — добавлены LiquidityZone, OnChainScore
- **db.py** — добавлены `get_onchain_metric_since()`, `get_all_onchain_metrics_since()`
- **scheduler.py** — добавлены `_retrain_model()` (еженедельно), `_make_prediction_1w()` (ежедневно)
- **bot/main.py** — переписан `/predict` с форматированным многоуровневым выводом
- **Dockerfile** — добавлен `libgomp1` для LightGBM

### 8. Исправление дубликатов подписок (Break-Hunter)

#### 8.1 Проблема
Каждый вызов `add_subscription()` создавал новую строку в БД для одного и того же пользователя/символа/интервала. При повторном нажатии на кнопку подписки появлялись дубликаты.

#### 8.2 Фикс
- **db.py `add_subscription()`** — проверяет существующую запись (user_id + symbol + interval), объединяет alert_types через `set()` вместо вставки нового ряда
- **db.py `remove_alert_type()`** — новый метод: удаляет один тип алерта из массива, строка удаляется когда массив пуст
- **bot/main.py `handle_delete()`** — кнопка `del_{sub_id}_{alert_type}` удаляет один тип; подписка удаляется когда не осталось типов

### 9. Исправление багов (Market-Brain Rapid-Dev, срочно)

#### 9.1 Мёртвый признак `oi_change`
**Проблема:** `oi_change` в `analyzer.py:260` всегда = 0.0 (хардкод). Open Interest не собирался.

**Фикс:**
- **collector.py** — добавлен сбор Open Interest с CoinGlass
- **analyzer.py `_get_onchain_df()`** — добавлена колонка `open_interest` с fallback 0.0
- **analyzer.py `_compute_24_features()`** — `oi_change` вычисляется как `pct_change()` от `open_interest`, fallback на прокси `funding_rate * volume_change_4h`

#### 9.2 Баг `_check_volume_spike` — ночная проверка
**Проблема:** `is_night` вычислялась в `_check_alert()` но не передавалась. Параметр назывался `check_volume` (некорректно). В выходные проверка делалась менее чувствительной (ошибка логики).

**Фикс:**
- **alerts.py `_check_volume_spike()`** — параметр переименован в `is_weekend`, добавлен `is_night`
- Ночь (22–6) и выходные: порог 2× (вместо 3×)
- `is_weekend` корректно передаётся

### 10. Новая фича: `/news`

#### 10.1 Что реализовано
- **bot/main.py** — команда `/news`: 5 последних новостей о Bitcoin с CryptoCompare
- Кнопка `/news` в ReplyKeyboard-меню
- `/help` обновлён
- Новости кешируются в Redis на 5 минут
- Каждая новость: заголовок, источник, ссылка

#### 10.2 Технические детали
- Источник: `min-api.cryptocompare.com/data/v2/news/`
- Парсинг: JSON, фильтр по релевантности (BTC/Bitcoin в заголовке)
- Кеш: Redis key `btc:news`, TTL 300 секунд

### 11. Текущее состояние

#### 11.1 Меню бота
`/btc` `/predict` `/subscribe` `/alerts` `/news` `/help`

#### 11.2 Расписание
- Short-term: каждый час (CronTrigger минута=0, час=*/1)
- Mid-term: каждые 6ч (0:00, 6:00, 12:00, 18:00)
- Long-term: по запросу
- Индикаторы: каждые 5 мин
- Модель: переобучение раз в неделю (пн 3:00)

### 12. Известные проблемы
- **On-chain метрики:** Glassnode API key не настроен → mid-term прогноз и long-term контекст без on-chain данных
- **LightGBM:** не хватает исторических данных для ML-прогноза (нужно 48+ часов)
- **CoinGlass OI:** может не работать без API ключа; fallback на прокси-признак

### 13. Улучшение /news и исправление багов (сессия 08.05.2026)

#### 13.1 CryptoCompare → Google News RSS
**Проблема:** CryptoCompare API возвращал 0 статей (возможно, изменились условия бесплатного тарифа).
**Фикс:** заменён на `news.google.com/rss/search?q=bitcoin+crypto` — парсинг XML, без ключа, 100+ статей.

#### 13.2 Формат /news — «Пульс рынка» (по совету Market-Brain)
Новый формат вывода:
- Заголовок `📊 Bitcoin — Пульс рынка`
- Строка настроения: `🟢 Бычье / 🔴 Медвежье / 🟡 Нейтральное`
- Счётчик: `Бычьих: N  Медвежьих: M`
- Индекс тревоги: `🟢 Низкий / 🟡 Средний / 🔴 Высокий` (доля медвежьих)
- Каждая новость с эмодзи тональности: 🟢 бычья, 🔴 медвежья, ⚪ нейтральная
- Комментарий от `Аналитик рынка` (бывший Market-Brain) — динамический, зависит от соотношения
- **Тональность:** ключевые слова (BULLISH_KEYWORDS / BEARISH_KEYWORDS), сравнительный подсчёт

#### 13.3 Market-Brain → Аналитик рынка
**Проблема:** англоязычное "Market-Brain" выглядит чужеродно в русскоязычном боте.
**Решение:** переименован в "Аналитик рынка" (по рекомендации самого Market-Brain).

#### 13.4 Исправление отображения счётчика
**Проблема:** `(0 из 5)` в строке настроения вводило в заблуждение — пользователь думал, что это "0 из 5 возможных настроений".
**Фикс:** заменено на две строки:
```
▫️ Бычьих: 0  Медвежьих: 2
```

### 14. Текущее состояние

#### 14.1 Меню бота
`/btc` `/predict` `/subscribe` `/alerts` `/news` `/help`

#### 14.2 Формат /news
```
📊 Bitcoin — Пульс рынка

▫️ Настроение: 🟢 Бычье
▫️ Бычьих: 3  Медвежьих: 1
▫️ Индекс тревоги: 🟡 Средний

1. 🟢 [заголовок] — источник
2. 🔴 [заголовок] — источник
...

💬 Аналитик рынка: комментарий по тону новостей

♻️ Обновление каждые 5 мин
```

#### 14.3 Баги (исправлены)
- `oi_change` больше не 0.0 — собирается OI с CoinGlass + fallback-прокси
- `_check_volume_spike` — корректно учитывает ночь и выходные (порог 2× вместо 3×)
- `/news` — переведён на Google News RSS (CryptoCompare отдавал 0 статей)
- Счётчик настроений — убран путающий формат `(X из Y)`

### 15. Русские новости (сессия 08.05.2026, продолжение)

#### 15.1 Google News RSS → русскоязычный
**Проблема:** новости были на английском.
**Фикс:** `hl=ru&gl=RU` — Google News отдаёт русскоязычные статьи о Bitcoin.
- Добавлены русские ключевые слова для тональности: рост/падение/обвал/приток и т.д.

#### 15.2 Цвет нейтральных новостей
**Проблема:** в шапке нейтральное = 🟡, а напротив новостей был ⚪ — разнобой.
**Фикс:** `emoji_map["neutral"] = "🟡"` — теперь везде 🟡.

#### 15.3 Единый стиль команд (по гайду Prompt-Master)
Все команды приведены к формату:
```
<emoji> *BTC Monitor — <тема>*
🕐 <дата, время> UTC

▸ **<ключ>:** <значение>
▸ **<ключ>:** <значение>
...

_♻️ <частота обновления>_
```

**Изменения по командам:**
- **/start** — обновлён список кнопок (6 вместо 4), команды в моноширинном `/code`
- **/btc** — единый заголовок, таймстамп, маркеры `▸`, сигнал в строку
- **/predict** — компактный: 5 строк вместо 18, процент вместо `0 из 100`, `▸ **Риск:**` вместо `💡 Нюанс:`
- **/news** — `▸` маркеры, `▸ **Настроение:**`, `▸ **Бычьих:** / **Медвежьих:**`, убрана нумерация, эмодзи перед ссылкой
- **/help** — кратко, единый подвал
- **/subscribe** — `▸` в описании типов алертов
- **/alerts** — заголовок `🔔 *BTC Monitor — Подписки*`
- **callbacks** — единый формат `✅ *BTC Monitor — <тема>*`

#### 15.4 Уточнение подвалов
- `/btc`: `_♻️ данные обновляются в реальном времени_` (было `по запросу`)
- `/predict`: `_♻️ прогноз: каждый час · on-chain: раз в 6ч_` (было `ежечасно / раз в 6ч`)

#### 15.5 Архитектурный обзор (Sigma-Architect)
Оценка: **6/10**

**Топ-3 проблемы:**
1. DB write amplification — Binance WS пишет каждый тик отдельным INSERT (50–500 запросов/с)
2. Нет volume mount для модели LightGBM — теряется при рестарте
3. CoinGlass без API ключа — каждые 5 мин 401 ошибка

**Отложено до следующей сессии:** батчинг записи, volume mount + CoinGlass guard, graceful degradation mid-term

### 16. Текущее состояние

#### 16.1 Меню бота
`/btc` `/predict` `/subscribe` `/alerts` `/news` `/help`

#### 16.2 Единый формат команд
```
<emoji> *BTC Monitor — <тема>*
🕐 <дата, время> UTC

▸ **<ключ>:** <значение>
▸ **<ключ>:** <значение>
...

_♻️ <частота обновления>_
```

#### 16.3 Известные проблемы
- Glassnode API key не настроен
- LightGBM: не хватает 48ч истории
- DB write amplification (без батчинга)
- Нет volume mount для модели
- CoinGlass без ключа шлёт холостые запросы
- Нет тестов

### 17. UI/UX-ревью и улучшения (сессия 08.05.2026)

#### 17.1 UI-дизайнер — ревью визуального стиля
**Рекомендации:**
- Единый шаблон заголовков (`·` вместо `—`)
- Чёткая визуальная иерархия через разделители `──`
- Emoji семантически, не декоративно
- Группировка связанных данных в блоки
- Унификация футеров `♻️`

**Реализовано:**
- `/btc` — разделители `── Цена ──` / `── Технические ──` / `── Сигнал ──`, футер `♻️ Обновление: реальное время`
- `/predict` — секции `── Сегодня ──` / `── Риски ──` / `── Неделя ──` / `── Долгосрочно ──`
- `/help`, `/subscribe`, `/alerts`, `/news` — единый заголовок `·` и футер
- `/alerts` и `/subscribe` — добавлен Markdown (был сырой текст)
- Ошибки — краткий формат без `— Ошибка`

### 18. Контент-стратегия (сессия 08.05.2026)

#### 18.1 Content Producer — контент-стратегия
**Новые рубрики:** `/morning` (ежедневная сводка), `/weekly` (дайджест недели), `/learn` (азбука крипты), опросы и квизы
**Улучшение existing:** `/btc` — динамика 24ч, `/predict` — человеческий язык, `/subscribe` — on-chain алерты
**Задействование агентов:** marketbrain → анализ, teacher → уроки, writer → тексты, editor → вычистка, smm_specialist → вовлечение

#### 18.2 Реализовано: `/learn` — Азбука крипты
- 20 уроков по всем метрикам проекта (RSI, MA, MACD, BB, OBV, MVRV, SOPR, FR, F&G, Volume, ATR, ADX, W%R, NUPL, Puell, RHODL, STH-SOPR, Reserve Risk, L/S Ratio, OI)
- Навигация: ◀️ ▶️ между уроками, 📋 назад к списку
- inline-кнопки, уроки созданы агентом `teacher` (qwen2.5:14b)

### 19. Бизнес-стратегия (сессия 08.05.2026)

#### 19.1 Business Strategist (deepseek-r1:32b) — стратегический анализ
**Позиционирование:** бесплатный русскоязычный Telegram-хаб Bitcoin-аналитики. Прямых аналогов нет.
**Монетизация:** Freemium + Binance referral + Telegram Stars (Premium)
**Топ-3 действия:**
1. Исправить критические блокеры (batch insert, CoinGlass guard, volume mount, Glassnode)
2. Запустить бота публично
3. Добавить базовую аналитику
**Дорожная карта:** 2 нед стабильность → 2 нед запуск → месяц роста → месяц удержания

### 20. Расширение индикаторов (сессия 08.05.2026)

#### 20.1 Finance Analyst (deepseek-r1:32b) — какие индикаторы добавить
**🟢 Добавлено в `/btc`:**
- BB(20,2) — три полосы + позиция цены
- MACD — линия, сигнал, гистограмма + бычье/медвежье
- MA50 | MA100 | MA200 — одной строкой
- MVRV Z-Score — интерпретация (недооценён/справедливо/переоценён)
- Цикл — фаза + score

### 21. Архитектурное ревью (сессия 08.05.2026)

#### 21.1 Sigma-Architect (deepseek-r1:32b) — оценка 4.3/10
**Топ-5 проблем:**
1. **P0** DB write amplification — CoinGecko без буфера, нет continuous aggregates
2. **P0** Analyzer создаётся многократно (бот, api, scheduler)
3. **P1** N+1 в AlertManager
4. **P2** LightGBM блокирует event loop
5. **P2** Мертвый код (Bitview разовый, CoinGecko дубль)

### 22. Технические исправления (сессия 08.05.2026)

#### 22.1 Критические блокеры (по Strategist)
- **Batch insert:** `PriceBuffer` — копит 100 записей или 10 сек → batch INSERT
- **CoinGlass guard:** добавлен `coinglass_api_key`, guard `if not key: return`
- **Volume mount:** `model_data` volume для bot и scheduler в docker-compose.yml

#### 22.2 Замена платных API на бесплатные
- **Glassnode → Bitview.space:** MVRV, SOPR, NUPL, Puell, RHODL, STH-SOPR, Reserve Risk (без ключа)
- **CoinGlass → Bybit/OKX:** Funding Rate, Long/Short Ratio, Open Interest (public API)
- Больше не требует API-ключей для on-chain

#### 22.3 DB write amplification (по Architect)
- **CoinGecko** переведён на `PriceBuffer` (было прямое `save_price`)
- **Continuous aggregate `candles_1m`** — OHLCV свечи через TimescaleDB
- **Retention policy** — сырые цены удаляются через 7 дней

#### 22.4 Analyzer — единый инстанс (по Architect)
- `bot/main.py` — Analyzer создаётся 1 раз в `on_startup()`, global
- `backend/api.py` — Analyzer создаётся 1 раз в `startup()`, global
- `scheduler.py` — уже был единый инстанс

### 23. Маркетинговая стратегия (сессия 08.05.2026)

#### 23.1 Мнение агентов по продвижению
**`@smm_specialist`:** Twitter/X c ежедневными сводками, Reddit r/BitcoinBeginners с уроками, Telegram-чаты крипто-трейдеров, Pikabu/VC.ru
**`@advertiser`:** 2 недели бесплатно → Telegram Ads (15–30K ₽) + Яндекс.Директ (20–40K ₽). MVP-бюджет 65–130K ₽/мес
**`@seo_specialist`:** Ключи «биткоин цена», «прогноз BTC». SEO-статьи на VC.ru/Habr
**`@business_strategist`:** ProductHunt, `/invite` (рефералка), опрос NPS. Сигнал к web — когда бот перестаёт вмещать функции
**`@pr_specialist`:** Не обещать точность 95%, отвечать на негатив за час, микро-инфлюенсеры

**KPI успеха для веб-платформы:** 3K+ юзеров за 3 мес, >200 DAU, >15% подписок

### 24. Исправление замечаний архитектора (сессия 08.05.2026)

#### 24.1 P1 — N+1 в AlertManager
- **Проблема:** `check_alerts()` делал 1 SELECT users + N SELECT subscriptions в цикле
- **Решение:** Добавлен метод `get_users_with_subscriptions()` в `db.py` — один JOIN с `unnest(alert_types)`, группировка по user_id в Python
- **Итого:** 2 запроса вместо 1+N

#### 24.2 P2 — run_in_executor для LightGBM
- **Проблема:** `lgb.train()` в `_train_model()` блокировал event loop
- **Решение:** Обёртка `loop.run_in_executor(None, lambda: lgb.train(...))`

#### 24.3 P2 — Bitview loop (периодический сбор on-chain)
- **Проблема:** `_bitview_loop()` выполнялся 1 раз при старте, несмотря на название
- **Решение:** Добавлен `while self._running` + `asyncio.sleep(3600)` — сбор раз в час

#### 24.4 P2 — Хардкод дат халвинга
- **Проблема:** Даты халвинга (2024, 2028) зашиты в коде `_predict_long()`
- **Решение:** Динамический расчёт: `genesis + n * 210000 * 600с`

#### 24.5 P3 — Redis ключи в один JSON
- **Проблема:** Три отдельных ключа `btc:indicator:rsi`, `ma_50`, `ma_200`
- **Решение:** Единый ключ `btc:indicators` (JSON), `model_dump(mode="json")` для сериализации datetime
- **Заодно:** Исправлена старая ошибка `TypeError: datetime is not JSON serializable` в `_compute_indicators`

#### 24.6 P3 — Мёртвый код backend/providers
- **Проблема:** `OllamaProvider` импортировался в `api.py` для 3 эндпоинтов, но не использовался ботом
- **Решение:** Удалён `backend/providers/` + `backend/config.py`, упрощены эндпоинты `/` и `/health`

#### 24.7 Пересборка и перезапуск
- Все контейнеры пересобраны (`docker-compose build`) и перезапущены (`docker-compose up -d --force-recreate`)

### 25. Продвижение (сессия 08.05.2026)

#### 25.1 Стратегия продвижения
- Создан `promotion_strategy.md` ~32 KB — полный план на 3 месяца
- **10 разделов:** текущее состояние, ЦА (4 сегмента), organic growth, product-led growth, paid acquisition, community, конверсия в web, KPI, roadmap, бюджет (3 варианта: 48K / 200K / 660K ₽)
- **Roadmap:** неделя 1 — @BotFather + каталоги + Twitter; месяц 2 — Telegram Ads + Яндекс.Директ; месяц 3 — геймификация + анонс web

#### 25.2 Настройка бота через Telegram API
- Исправлено имя: `BTC Monitor: кракозябры → BTC Monitor`
- Установлены описание, краткое описание, 7 команд (`/btc`, `/predict`, `/news`, `/learn`, `/subscribe`, `/alerts`, `/help`) через `setMyDescription`, `setMyName`, `setMyCommands`
- Включён inline mode (@BotFather → `/setinline`)

#### 25.3 Каталоги
- Проверены ссылки: `tlgrm.ru/bot/add` (404), `botlist.me` (Discord-каталог, не для Telegram)
- Найдены 6 рабочих каталогов РФ: `catalogtelegram.ru`, `telepot.ru`, `tgram.me`, `katalogtelegram.ru`, `protelegram.ru`, `tlgbot.ru`
- Поданы заявки во все каталоги

#### 25.4 Замечания
- **Username:** `Market04ekBot` (не `BTCMonitorBot`, как планировалось) — смена через BotFather потребовала бы новый токен, решено оставить
- **Inline mode:** включён через @BotFather

### 26. Деплой на сервер и отладка сети (сессия 09.05.2026)

#### 26.1 Проблема
При деплое на сервер Aeza (Ubuntu 24.04, 1 vCPU, 2GB RAM) бот не отвечал в Telegram. Контейнеры падали в restart loop без видимых логов.

```
Container bot-bot-1... Exited (137)
```

#### 26.2 Установка Docker
На сервере не был установлен Docker. Установлены: `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-compose-plugin`.

#### 26.3 Настройка `.env`
В `.env` добавлены `DATABASE_URL` и `REDIS_URL` с правильными именами хостов (`postgres`/`redis` вместо `localhost`).

#### 26.4 Python buffering (Break-Hunter)
**Проблема:** логи бота не отображались — Python буферизирует stdout.
**Фикс:** добавлен `PYTHONUNBUFFERED: "1"` в `environment` сервиса `bot` в `docker-compose.yml`.

#### 26.5 Диагностика сети (Live-Debug)
**Проблема:** в логах появилась ошибка `TelegramNetworkError: Request timeout error` при вызове `bot.me()` (getMe).
**Причина:** из Docker bridge network не работали исходящие HTTPS-соединения на 443 порт (DNS резолвился, TCP connection timeout).

Проверка из контейнера:
```
$ curl -v --connect-timeout 10 https://api.telegram.org
*   Trying 149.154.166.110:443...
* Connection timed out after 10002 milliseconds
```

С хоста при этом `ping api.telegram.org` проходил (45ms). Проблема — в настройках сети Aeza (возможно, iptables/nat для Docker bridge).

#### 26.6 Фикс сети
**Решение:** сервис `bot` переведён на `network_mode: host` — использует сеть хоста напрямую, минуя Docker bridge.
- `DATABASE_URL` в сервисе `bot` изменён на `localhost:5432`
- `REDIS_URL` в сервисе `bot` изменён на `localhost:6379`

#### 26.7 Результат
- Бот отвечает в Telegram
- `pending_update_count: 0` — polling работает
- В логах: `Database connected` + предупреждения анализатора (не хватает данных для 4H-прогноза — нормально)
- Все 6 контейнеров: postgres, redis, collector, scheduler, api, bot — запущены

#### 26.8 Текущие известные проблемы
- **Docker bridge network** — исходящие HTTPS не работают (требуется `network_mode: host` для любых сервисов, которым нужен outbound HTTPS)
- **Glassnode API key** не настроен
- **LightGBM** — не хватает 48ч истории для ML-прогноза

---

## Сессия 27: Аудит Sigma-Architect и исправление критических замечаний

### Участники
- **Sigma-Architect** (`deepseek-r1:14b`) — аудит проекта
- **Главный разработчик** — исправление кода

### 27.1 Sigma-Architect: результаты аудита

Оценка: **5.5/10**

**Критические проблемы:**
1. Дублирование `Analyzer`/`Database` — каждый процесс (bot, api, scheduler) создаёт свои экземпляры
2. `_lgb_model` — гонка между API и Scheduler при одновременном predict/train
3. `network_mode: host` — полный доступ к сети хоста (небезопасно)

**Высокие:**
4. Нет миграций БД — схема создаётся `CREATE TABLE IF NOT EXISTS`
5. Мёртвые конфиги: `glassnode_api_key`, `coinglass_api_key`, `coinmarketcap_api_key`
6. Мёртвые зависимости: `onnxruntime` (~500MB), `scikit-learn`

**Средние:**
7. `_binance_ws_loop` — новая `aiohttp.ClientSession` на каждое переподключение
8. Нет дедупликации алертов — RSI > 70 спамит каждые 15 мин
9. `_train_model` блокирует event loop
10. RSI fallback — хардкод 2% вместо ATR
11. Volume Spike ключи никогда не пишутся

### 27.2 Исправления

| # | Проблема | Фикс | Файл |
|---|----------|------|------|
| 🔴 3 | `network_mode: host` — небезопасно | Оставлен для бота (Telegram timeout в bridge); остальные сервисы используют Docker DNS | `docker-compose.yml` |
| 🟠 5 | Мёртвые конфиги | Удалены `glassnode_api_key`, `coinglass_api_key`, `coinmarketcap_api_key` | `btcbot/config.py` |
| 🟠 6 | `onnxruntime`, `scikit-learn` | Удалены из зависимостей (-500MB к образу) | `requirements.txt` |
| 🟡 8 | Дедупликация алертов | Cooldown 60 мин на user+тип | `btcbot/alerts.py` |
| 🟡 11 | Volume Spike | Добавлен `VolumeTracker` — пишет avg/current volume в Redis | `btcbot/collector.py` |
| 🟡 7 | Утечка `ClientSession` | `_binance_ws_loop` использует внешнюю сессию | `btcbot/collector.py` |
| 🔴 2 | Модель не расшарена | `model_data` volume добавлен в API-сервис | `docker-compose.yml` |

### 27.3 Дополнительные проблемы в продакшне

В ходе деплоя обнаружены и исправлены:

- **`.env` удалён `git reset --hard`** — после force-push очищенной истории `git reset --hard` удалил `.env` (файл был в git-индексе как `deleted`). Восстановлен вручную.
- **БД `btcbot` не существовала** — postgres volume был инициализирован без `POSTGRES_DB` или база была повреждена. Создана заново, пароль сброшен.
- **Токен в git-истории** — очищен через `git filter-branch`, force-push на GitHub, сервер синхронизирован.

### 27.4 Оставшиеся замечания архитектора

- **🔴 P0:** Убрать дублирование Analyzer (единый сервис инференса) — requires рефакторинг
- **🟠 P1:** Alembic миграции для БД
- **🟡 P2:** `run_in_executor` для тяжёлых pandas/ML операций
- **🟡 P2:** ATR-based spread вместо 2% в RSI fallback
- **🟢 P3:** Стемминг для новостного сентимента
- **🟢 P3:** Юнит-тесты (сейчас 0)
