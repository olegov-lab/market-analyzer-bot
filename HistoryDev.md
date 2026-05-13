# BTC Monitor — История разработки

## Сессия 1: Проектирование (Prompt-Master, Market-Brain, Sigma-Architect)
- **Prompt-Master** — структурированный промпт для архитектора
- **Market-Brain** — источники: Binance WS, Glassnode, CoinGecko, CoinGlass. 3 группы индикаторов: технические (RSI, MACD, MA, BB), on-chain (MVRV, SOPR, NUPL), sentiment (F&G, Funding Rate). Прогнозы: 4H / 1W / >1W. Временные сигналы: сессии (Азия/Европа/США), почасовые паттерны, дни недели
- **Sigma-Architect** — 6 микросервисов: Telegram Interface (aiogram), Collector (WS+REST), Analyzer Engine (pandas_ta+LightGBM), Scheduler (APScheduler), Alert Manager, Internal REST API (FastAPI). PostgreSQL+TimescaleDB, Redis pub/sub

## Сессия 2: Реализация ядра (Rapid-Dev)
- `btcbot/config.py` — pydantic-settings
- `btcbot/models.py` — PriceRecord, Candle, IndicatorSet, Prediction, Alert
- `btcbot/db.py` — asyncpg + TimescaleDB (hypertable, continuous aggregates, retention)
- `btcbot/collector.py` — Binance WS + CoinGecko + Glassnode + CoinGlass
- `btcbot/analyzer.py` — pandas_ta индикаторы + LightGBM на 4H
- `btcbot/alerts.py` — день/ночь фильтры, weekend gate, RSI/MA/Volume триггеры
- `btcbot/scheduler.py` — APScheduler: индикаторы 5м, прогноз 30м, алерты 15/60м
- `bot/main.py` — aiogram: `/btc`, `/predict`, `/subscribe`, `/alerts`
- `backend/api.py` — FastAPI (порт 8000): `/btc/price`, `/btc/indicators`, `/btc/predict`
- Инфраструктура: Dockerfile, docker-compose.yml (6 сервисов), requirements.txt

## Сессия 3: Полная система прогнозов (Market-Brain)
- Short-term 4H: 24 признака × LightGBM (3 класса BUY/HOLD/SELL), ATR×2.5 = 95% CI
- Mid-term 1W: rule-based on-chain — 5 метрик с весами (MVRV 30%, SOPR 20%, NUPL 20%, Puell 15%, RHODL 15%)
- Long-term: MVRV Z-Score, 200W MA, халвинг, STH-SOPR — только контекст
- Liquidity zones: volume profile + локальные экстремумы ±2%
- Формат `/predict`: многоуровневый (Short/Mid/Long/ликвидность/нюансы)
- **Файлы:** analyzer.py (рефакторинг), models.py (LiquidityZone, OnChainScore), db.py (onchain методы)

## Сессия 4: Дубликаты подписок (Break-Hunter)
- `add_subscription()` — теперь UPSERT (user_id+symbol+interval) вместо INSERT
- `remove_alert_type()` — удаляет один тип, строка удаляется когда массив пуст
- Кнопки `del_{sub_id}_{alert_type}` в `/alerts`

## Сессия 5: Баг-фиксы — сбор OI и volume spike ночью
- `oi_change` был хардкод 0.0 → сбор Open Interest с CoinGlass + fallback proxy
- `_check_volume_spike` — параметр `check_volume` → `is_weekend`, добавлен `is_night`. Ночь/выходные: порог 2× вместо 3×

## Сессия 6: Команда `/news`
- CryptoCompare API → фильтр по релевантности BTC → кеш Redis 5 мин
- Кнопка в ReplyKeyboard, обновлён `/help`

## Сессия 7: Улучшение /news (08.05.2026)
- CryptoCompare отдавал 0 статей → Google News RSS (`news.google.com/rss/search`)
- Формат «Пульс рынка»: 🟢/🔴 настроение, счётчик бычьих/медвежьих, индекс тревоги
- Тональность: BULLISH_KEYWORDS / BEARISH_KEYWORDS, эмодзи на каждую новость
- Market-Brain → «Аналитик рынка» (русскоязычный бот)
- Счётчик: `(0 из 5)` → `▫️ Бычьих: N  Медвежьих: M`

## Сессия 8: Русские новости + единый стиль команд
- `hl=ru&gl=RU` — русскоязычные статьи
- Единый формат всех команд: `<emoji> *BTC Monitor — тема*` / `🕐 дата UTC` / `▸ **ключ:** значение` / `♻️ частота`
- Цвет нейтральных новостей: ⚪ → 🟡 (единообразие)

## Сессия 9: Архитектурное ревью (Sigma-Architect) — оценка 6/10
- DB write amplification — Binance WS пишет каждый тик отдельным INSERT (50–500/s)
- Нет volume mount для модели LightGBM (теряется при рестарте)
- CoinGlass без ключа — холостые 401 запросы

## Сессия 10: UI/UX ревью (UI Designer)
- Разделители `── Секция ──`, группировка в блоки, эмодзи семантически
- Футеры: `♻️ Обновление: реальное время` / `♻️ прогноз: каждый час · on-chain: раз в 6ч`

## Сессия 11: Контент-стратегия (Content Producer)
- `/morning` (ежедневная сводка), `/weekly` (дайджест), `/learn` (азбука крипты), опросы
- 20 уроков по всем метрикам проекта + навигация ◀️ ▶️

## Сессия 12: Бизнес-стратегия (Business Strategist)
- Позиционирование: бесплатный русскоязычный Telegram-хаб Bitcoin-аналитики
- Монетизация: Freemium + Binance referral + Telegram Stars
- Дорожная карта: 2 нед стабильность → 2 нед запуск → месяц рост → месяц удержание

## Сессия 13: Расширение `/btc` (Finance Analyst)
- BB(20,2) с позицией цены, MACD с направлением, MA50/100/200 одной строкой
- MVRV Z-Score с интерпретацией, фаза цикла + score

## Сессия 14: Архитектурное ревью 2 (Sigma-Architect) — оценка 4.3/10
- P0: DB write amplification + Analyzer создаётся многократно
- P1: N+1 в AlertManager
- P2: LightGBM блокирует event loop, мёртвый код

## Сессия 15: Критические блокеры (по Strategist)
- `PriceBuffer` — копит 100 записей или 10с → batch INSERT
- CoinGlass guard — `if not key: return`
- Volume mount `model_data` для модели
- Glassnode → Bitview.space (MVRV, SOPR, NUPL и др., без ключа)
- CoinGlass → Bybit/OKX (Funding Rate, L/S Ratio, OI, public API)
- CoinGecko → PriceBuffer, continuous aggregates `candles_1m`, retention 7→180 дней
- Analyzer — единый инстанс в bot/api/scheduler

## Сессия 16: Маркетинговая стратегия
- Twitter/X, Reddit r/BitcoinBeginners, Telegram-чаты, Pikabu/VC.ru
- Telegram Ads (15-30K ₽) + Яндекс.Директ (20-40K ₽), MVP-бюджет 65-130K ₽/мес
- KPI: 3K+ юзеров за 3 мес, >200 DAU, >15% подписок

## Сессия 17: Замечания архитектора — исправления
- P1 N+1 AlertManager: `get_users_with_subscriptions()` — JOIN + `unnest(alert_types)`
- P2 LightGBM event loop: `loop.run_in_executor()` для `lgb.train()`
- P2 Bitview loop: `while self._running` + `asyncio.sleep(3600)` (был разовый вызов)
- P2 Халвинг даты: динамический расчёт `genesis + n * 210000 * 600с`
- P3 Redis ключи: три отдельных → единый `btc:indicators` (JSON)
- P3 Мёртвый код: удалён `backend/providers/`, упрощены эндпоинты

## Сессия 18: Продвижение — настройка бота
- `promotion_strategy.md` ~32 KB — 10 разделов, 3 варианта бюджета (48K/200K/660K ₽)
- @BotFather: имя, описание, 7 команд, inline mode
- 6 каталогов РФ: catalogtelegram.ru, telepot.ru, tgram.me и др.
- Username: `Market04ekBot` (смена потребовала бы новый токен)

## Сессия 19: Деплой на Aeza + отладка сети (09.05.2026)
- Сервер: Ubuntu 24.04, 1 vCPU, 2GB RAM. Docker не был установлен
- `PYTHONUNBUFFERED: "1"` — логи не отображались из-за буферизации
- Docker bridge network не работал outbound HTTPS (iptables Aeza)
- `network_mode: host` для bot — обход проблемы
- Все 6 контейнеров запущены, бот отвечает

## Сессия 20: Аудит и фиксы (Sigma-Architect) — оценка 5.5/10
- Критические P0: дублирование Analyzer/Database, гонка `_lgb_model`, `network_mode: host`
- Удалены мёртвые конфиги: glassnode_api_key, coinglass_api_key, coinmarketcap_api_key
- Удалены мёртвые зависимости: onnxruntime (~500MB), scikit-learn
- Дедупликация алертов: cooldown 60 мин
- VolumeTracker в collector.py — пишет avg/current volume в Redis
- Утечка ClientSession: `_binance_ws_loop` использует внешнюю сессию
- Инциденты: `.env` удалён `git reset --hard` (восстановлен), токен очищен из git-истории

## Сессия 21: Telegram Mini App + Cloudflare Tunnel (28)
- `MenuButtonWebApp` — кнопка «📊 BTC Dashboard» слева от поля ввода
- SPA на Vanilla JS: `miniapp/index.html`, `app.js`, `styles.css`
- 5 вкладок: Цена, Прогноз, Новости, Уроки, Подписки
- API endpoints: `/miniapp/dashboard`, `/predict`, `/news`, `/lessons`, `/subscriptions`
- Auth: HMAC-SHA256 initData через `backend/miniapp_auth.py`
- Блокер: скрипты не загружались — URL без `/` на конце, CDN `telegram-web-app.js` удалён ошибочно, hash `tgWebAppData=` ломал роутер
- Cloudflare Tunnel: `cloudflared-wrapper.sh` — автообновление URL в `.env`, рестарт bot-контейнера
- Menu Button URL не обновлялся — `docker compose restart` НЕ перечитывает `.env`, переход на `up -d`
- `/start`: приветствие по времени суток + 3 новости с тональностью
- Кнопка меню: `📊 BTC Dashboard` → `📊 BTC`

## Сессия 22: Аудит и массовый фикс P0-P2 (29, 10.05.2026)
- Оценка: 4.5/10
- P0: `/btc/alert/subscribe` — `user_id = data.alert_type` (баг), нет auth. Добавлена `_get_user_id()`, убран SubscribeRequest
- P0: Массовое дублирование кода bot/api — созданы `btcbot/sentiment.py` + `btcbot/news.py`
- P0: Race condition `_lgb_model` — добавлен `threading.Lock`
- P0: Приоритет `&` перед `!=` — скобки: `... & (targets != -1)`
- P1: CORS `*` → `settings.miniapp_url_normalized`
- P1: `aiohttp.ClientSession` на каждый запрос → единая сессия
- P1: LightGBM predict блокирует event loop → `run_in_executor()`
- P2: Frontend XSS + error boundary — `escapeHtml`, `render()` обёрнут в try/catch
- P2: `ollama` удалён из requirements.txt
- P2: Rate limiting `slowapi` (30/20/10/60 req/min)
- P2: Postgres password в git → `${POSTGRES_PASSWORD:-postgres}`
- `.env.example` создан
- `/daily_news()` — фоновый таск, всем активным пользователям в 10:00 UTC

## Сессия 23: AI Chat `/ask` (32, 10.05.2026)
- Любой вопрос о Bitcoin → Market-Brain (DeepSeek V4 Pro)
- Rate limit: 30с между запросами (in-memory)
- `agents.py:ask_agent()` использует модель из конфига агента
- Кнопка `/ask` в ReplyKeyboard

## Сессия 24: Fear & Greed + Price Alerts (32-33)
- Fear & Greed Index: alternative.me API, Redis-кеш 1ч, stale fallback
- Отображается в `/miniapp/dashboard` (hero-rsi блок) и `/btc` (── Рынок ──)
- Price Alerts: `/alert 100000`, `/alert above/below`, `/alert_remove`. Таблица `price_alerts`, проверка каждые 5м
- API: `GET/POST/DELETE /miniapp/price-alerts`

## Сессия 25: AI Chat в Mini App + Price Chart + Volatility (33)
- Вкладка 🧠 AI в Mini App — POST `/miniapp/ask` + polling GET
- Price Chart: TradingView lightweight-charts v4.1.1, таймфреймы 1H/4H/1D/1W, типы свечи/линия/область
- Volatility Risk Meter: `compute_volatility()` (BB ширина + ATR + перцентиль 30д)
- `/volatility` в боте, gauge + sparkline в дашборде
- Volume mounts: `./btcbot:/app/btcbot`, `./backend:/app/backend`
- Фикс: catch-all роут 405 (порядок регистрации), pandas `&` на float (notna+boolean mask)

## Сессия 26: Полный codebase review 4 агентами (34)
- Sigma-Architect: `network_mode: host`, `return_exceptions=True` тихое глотание, race condition ML
- Market-Brain: всего ~18ч данных (ML/MA200/on-chain не работают), Google News ненадёжен, нет проверки `auth_date`
- Rapid-Dev: 14 багов — дубль роута `/miniapp/chart`, SQL injection в `time_bucket`, XSS в `showError()`, dead code `AGENT_MODEL`
- Break-Hunter: 22 бага + 3 race conditions + 12 edge cases + 7 уязвимостей
- Фиксы P0: PriceBuffer clear ПОСЛЕ save, safe_gather helper, дубль роута, SQL injection
- `btcbot/utils.py` — `safe_gather()` вместо `return_exceptions=True`

## Сессия 27: Mini App — 4 вкладки с группировкой (35)
- 7 вкладок → 4: 📊 Индикаторы, 🧠 AI анализ, 🎮 Мини App, 📰 Новости
- Hash-схема: `#indicators[/price|/predict|/alerts]`, `#chat`, `#miniapp[/lessons|/games]`, `#news[/general|/timothy]`
- Pill sub-tabs внутри каждой вкладки. Chart рендерится 1 раз, не пересоздаётся
- `parseHash()`, `navigate(page, sub)`, `renderSub()`, `renderIndicatorsPage()`, `renderMiniAppPage()`, `renderNewsPage()`

## Сессия 28: Фикс багов Mini App (36)
- Indicators tab бесконечный рендеринг — `renderDashboard()` вызывал `render()` вместо `renderSub()`
- News/Timothy пустое окно — WebView кеш старого app.js. Cache-bust: `v=20260510.3` → `.6`
- Chart HTTP 500 для 1H/1D/1W — `time_bucket($3::text)` не работал → f-строка `'{interval}'::interval`
- Postgres `scram-sha-256` → `trust` для Docker-сети
- Timothy Peterson AI: `GET /miniapp/news/timothy`, DeepSeek V4 Pro с рыночными данными, кеш 1ч
- `/alerts`: Markdown → HTML parse_mode, inline-кнопки отписки вместо текстовых команд

## Сессия 29: Bottom Tab Bar + Glassmorphism + График (37)
- График как sub-tab 📊 в Индикаторах (первый при входе)
- Bottom nav: 8+ CSS итераций, финальный glassmorphism (`blur(14px)`, `rgba(20,20,20,0.82)`)
- Telegram WebView кеш: переименование CSS (styles.css → styles-v2.css → app.css) + выход из приложения

## Сессия 30: Торговый симулятор (38)
- Виртуальный счёт $10,000. `/buy`, `/sell`, `/portfolio`, `/leaderboard`
- DB: `game_users`, `positions`, `trades`, `leaderboard_mv` + materialized view
- `btcbot/game.py` — GameEngine, транзакции с `SELECT ... FOR UPDATE`
- Mini App: лобби игр + trading UI (`#miniapp/games/trading`)
- Комиссия 0.1%, мин. $10, рейтинг: ROI×0.5 + WinRate×0.2 + ProfitFactor×0.3

## Сессия 31: Стратегический роадмап + Фаза 1 (39, 11.05.2026)
- 4 агента: Sigma-Architect (6 фаз), UI/UX Designer (4 кнопки, цветовая схема), Market-Brain (AI-саммари, consensus), Business Strategist (монетизация Stars)
- `ROADMAP.md` — полный план. Монетизация в Фазе 1 (не откладывать)
- Reply-меню: 14 → 4 + 1 кнопок. Текст-матчинг через `or_f(Command, F.text)`
- `/help` — хаб для `/learn`, `/subscribe`, `/alerts`, `/volatility`
- Динамическая цветовая схема: `--sentiment` CSS vars, `data-sentiment` на `<html>`
- MVPS: `btcbot/subscription.py`, таблица `user_subscriptions`, Tier: FREE/PRO/PRO_PLUS
- 72-часовой триал при `/start`. Лимиты: 3 AI/день, 3 сделки/день (Redis счётчики)
- Haptic: heavy/rigid/success/warning. PRO-бейдж в `/portfolio`
- `/start` — 4 команды + триал + "25 AI-агентов"

## Сессия 32: Фаза 2 — AI Сводка + Консенсус + Seed данных (40, 11.05.2026)
- `btcbot/summarizer.py` — AI-саммари 5 групп индикаторов (trend, momentum, volatility, onchain, sentiment) через Market-Brain (DeepSeek V4 Pro). Redis-кеш 5 мин, прогрев при старте API
- `analyzer.compute_consensus()` — 7+ индикаторов из 3 групп голосуют +1/-1/0, итог `bullish_pct` 0-100%
- Карточка `🧠 AI Сводка` в Mini App дашборде и секция `── AI Сводка ──` в `/btc`
- `btcbot/seed_history.py` — 90 дней истории BTC/USD из CoinGecko free API → 2,168 hourly свечей
- Continuous aggregates полный рефреш: candles_1m (2,322), candles_4h (541) — ML теперь работает
- P0 fix: `_lgb_model` race condition — `_is_training` флаг + `threading.Lock`
- P0 fix: `oi_change` pandas `.where()` shape mismatch
- P0 fix: `compute_consensus()` — `funding_rate` извлекается из БД (нет в IndicatorSet)
- P0 fix: `summarizer` — `indicators.atr_pct` и `indicators.funding_rate` заменены на `getattr()` (не в модели)
- P0 fix: `_get_onchain_df()` вызывался без `since` → TypeError → summary не генерировался
- Telegram WebView кеш: app.js → app.v11.js (переименование, bypass агрессивного кеша)
- Лейаут AI-карточки: вертикальный стек (заголовок группы сверху, текст снизу)
- `_warmup_summary_cache()` — прогрев AI-саммари при старте API

## Сессия 33: Upgrade на OpenCode Go модели (30)
- Ollama → OpenCode Go API: DeepSeek V4 Pro (9), GLM-5.1 (11), Kimi K2.6 (3)
- 25 агентов в `agents/*.json`, `/agents` и `/agents/{name}` API endpoints
- Техдолг: Alembic миграции, ATR-based spread, стемминг-сентимент (RU/EN)
- Перенос агрегации в БД: `get_4h_candles_since` — SQL `time_bucket` вместо pandas resample (240x меньше данных, 3x быстрее)
- `candles_4h` materialized view — ещё 10x ускорение
- Redis-кеш: индикаторы 30с, прогнозы 5 мин
- `asyncio.gather` для `_predict_4h`, `_predict_1w`, `_predict_long`

## Сессия 34: 5 надёжностных фиксов (11.05.2026)
- P0: Telegram Stars — `/upgrade` → `sendInvoice(XTR)` → `pre_checkout` → `successful_payment` → `activate_pro/pro_plus`. Новый файл `bot/handlers/subscribe.py`
- P0: `_ask_tasks` dict → Redis `btc:ask:{task_id}` (TTL 600с). Mini App AI-чат переживает рестарт API. Убран `_cleanup_old_tasks()`
- P1: `VolumeTracker` — `list` → `collections.deque`, prune раз в 30с вместо каждого тика. O(n) на тик → O(1)
- P2: `_user_pending: set` → Redis `btc:ask:pending:{uid}` (TTL 120с). Бот `/ask` переживает рестарт
- P2: `network_mode: host` — iptables ACCEPT + MASQUERADE испробованы, Network unreachable на уровне хостера. Оставлен host

## Сессия 35: Фаза 3 — AI Evolution (11.05.2026)
### 3.1 [CHART] маркеры в AI-ответах
- `agents/marketbrain.json` — инструкция: `[CHART:1d:MA200]` в ответах
- `bot/handlers/ask.py` — парсинг маркеров → inline-клавиатура с WebApp-кнопками
- `miniapp/app.js` — `parseHash()` deep-link `#indicators/chart/1d/MA200`, `_addChartOverlay()` (MA50/MA200/BB/RSI/VOL), JS-расчёт индикаторов из свечей

### 3.2 Проактивные алерты
- `btcbot/breakout.py` (новый) — `ProactiveAlertEngine`: 7 триггеров (MA cross, BB touch, RSI/MVRV/F&G экстрим, vol/funding spike), Redis cooldowns 2h-24h
- `btcbot/scheduler.py` — проверка каждые 2 мин, сохранение в очередь `btc:proactive:queue`
- `bot/main.py` — `_proactive_consumer()`: рассылка алертов всем активным юзерам с per-user cooldown 24h

### 3.3 Голосовой ввод
- `bot/handlers/ask.py` — `F.voice` handler, PRO+ gate. Полная обработка голоса отложена до интеграции Whisper API

### 3.4 AI Daily Story
- `btcbot/daily_story.py` (новый) — `generate_daily_story()` через Market-Brain с рыночным контекстом
- `btcbot/scheduler.py` — генерация в 9:00 UTC, кеш в Redis на 24h
- `bot/main.py` — `_story_consumer()`: рассылка всем активным юзерам

---

## Текущее состояние

**Меню бота:** `[📊 Аналитика] [🧠 AI Чат] [🎮 Трейдинг] [📰 Новости] [❓ Ещё]`

**Мини App вкладки:** 📊 Индикаторы | 🧠 AI анализ | 🎮 Мини App | 📰 Новости

**Индикаторы sub-tabs:** 📊 График, 💰 Цена, 🔮 Прогноз, 🔔 Подписки

**Работает:** AI-саммари, AI-чат (+ [CHART] маркеры), консенсус, график (4 таймфрейма), волатильность, Fear & Greed, торговый симулятор, подписки/алерты, уроки, новости с тональностью, Timothy Peterson AI, PRO-триал, Stars-оплата, проактивные алерты (7 триггеров), AI Daily Story

**Docker:** 6 контейнеров (postgres, redis, collector, scheduler, api, bot). Сервер Aeza (77.110.104.104, Ubuntu 24.04, 1 vCPU, 2GB)

**Данные:** 90 дней истории (CoinGecko seed), ~107K записей в prices, 541 свеча 4H

**ML:** RSI 53.2, MA50 $81,983, MA200 $81,632, направление HOLD, confidence 28%

**Известные проблемы:**
- `network_mode: host` для bot (iptables на уровне хостера блокирует Docker bridge outbound)
- Нет unit-тестов
- `chatMessages` массив без кепа (Mini App)
- `chartDataCache` без инвалидации (Mini App)

**Отложено:** Metcalfe Corridor, геймификация, Web3/TON Connect, Shareable Cards, Portfolio Dashboard
Краткий итог Фазы 3:
- CHART маркеры — AI может ссылаться на график, пользователь кликает → открывается график с наложенным индикатором
- Проактивные алерты — 7 триггеров, проверка каждые 2 мин, рассылка всем активным пользователям
- Голосовой ввод — заглушка с PRO+ гейтом (Whisper API позже)
- AI Daily Story — ежедневный обзор рынка в 9:00 UTC, рассылка всем
Фаза 3 завершена и деплоена. Проактивные алерты уже работают — задетекчены BB touch и volume spike (18.7x среднего). Все контейнеры запущены.
Фаза	Статус	Что
1 — UX + Монетизация	x1f7e2;	4 кнопки, цветовая схема, Stars, триал, лимиты
2 — Аналитика + AI	x1f7e2;	AI-саммари, консенсус, 90д истории, ML работает
3 — AI Evolution	x1f7e2;	[CHART] маркеры, проактивные алерты, голос (заглушка), Daily Story
4 — Геймификация	x1f4cb;	Лиги, турниры, XP, бейджи
5 — Web3/TON	x1f4cb;	TON Connect, кошелёк
6 — Масштабирование	x1f4cb;	API-first, B2B
Что дальше?
▣  Build · DeepSeek V4 Pro · 18m 58s
1 — UX + Монетизация	x1f7e2;	4 кнопки, цветовая схема, Stars, триал, лимиты где посмотреть?
Thinking: The user is asking where to see the Phase 1 features:
- 4 button Reply keyboard menu
- Color scheme (dynamic CSS)
- Stars payment
- Trial
- Limits
Let me point them to the specific files and code locations.
- 4 кнопки — bot/state.py:19-26 (ReplyKeyboardMarkup) + bot/handlers/btc.py:30 (текст-матчинг F.text == "📊 Аналитика")
- Цветовая схема — miniapp/app.css (CSS vars --sentiment), miniapp/app.js:setSentiment() + Telegram.setHeaderColor()
- Stars оплата — bot/handlers/subscribe.py (/upgrade → sendInvoice(XTR) → pre_checkout → successful_payment)
- Триал 72ч — btcbot/subscription.py:61 (activate_trial() → INSERT в user_subscriptions), вызывается из /start
- Лимиты — bot/handlers/ask.py:39-49 (3 AI/день), bot/handlers/game.py (3 сделки/день), счётчики через Redis ask_count:{uid} / trade_count:{uid}
▣  Build · DeepSeek V4 Pro · 14.6s
нет ничего такого
Thinking: The user is saying that when they look at the actual files/bot commands, they don't see any of these features. Let me check what's actually deployed and working. Maybe the features exist in code but aren't accessible through the bot UI, or maybe there's a disconnect between what I documented and what's actually visible.
Let me check the actual menu_kb to see if the 4 buttons are there, and check if /upgrade actually works, etc.
# Check actual deployed features
$ ssh -o ConnectTimeout=5 root@77.110.104.104 "grep -n 'menu_kb\|ReplyKeyboard' /bot/bot/state.py; echo '==='; grep -rn 'sendInvoice\|pre_checkout\|successful_payment\|/upgrade' /bot/bot/handlers/ 2>&1; echo '==='; docker logs bot-bot-1 --tail 5 2>&1; echo '==='; docker ps --format '{{.Names}} {{.Status}}'"
5:from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
19:menu_kb = ReplyKeyboardMarkup(
===
/bot/bot/handlers/ask.py:160:            "💎 Оформите PRO+ за 200 ⭐/мес — `/upgrade_plus`",
/bot/bot/handlers/subscribe.py:56:@dp.pre_checkout_query()
/bot/bot/handlers/subscribe.py:57:async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
/bot/bot/handlers/subscribe.py:58:    await pre_checkout_query.answer(ok=True)
/bot/bot/handlers/subscribe.py:61:@dp.message(F.successful_payment)
/bot/bot/handlers/subscribe.py:62:async def successful_payment(message: Message):
/bot/bot/handlers/subscribe.py:63:    payload = message.successful_payment.invoice_payload
…
Click to expand
Thinking: The code IS deployed. The bot menu_kb shows 4+1 buttons. The proactive alerts even worked and sent to 2 users. The Stars payment handlers are there in subscribe.py.
The user is saying "нет ничего такого" — meaning they can't SEE these features when using the bot. The issue might be:
1. The user is on an old cached version of the bot (need to /start to refresh menu_kb)
2. The /upgrade command isn't in the menu (it's a separate /command, not a button)
3. The user may be looking at the wrong bot
4. The bot menu_kb might not be showing because they haven't typed /start recently
Let me check what the menu_kb actually looks like and verify the bot responds to the buttons. Also let me check if /upgrade is actually a command that works.
Actually, looking at the menu_kb in state.py:
menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Аналитика"), KeyboardButton(text="🧠 AI Чат")],
        [KeyboardButton(text="🎮 Трейдинг"), KeyboardButton(text="📰 Новости")],
        [KeyboardButton(text="❓ Ещё")],
    ],
    resize_keyboard=True,
)
This shows 4 buttons + 1. The Stars payment isn't a menu button — it's a /upgrade command. The user may not know about it.
Let me tell the user what's actually visible and what's behind commands. The user seems frustrated that they can't see the features. Let me be honest about what's visible vs what's in code.
Код на сервере есть, всё деплоено. Проактивные алерты даже отправились 2 пользователям. Но интерфейс бота показывает не всё. Вот что реально видно:
Видно в меню (5 кнопок):
- 📊 Аналитика → /btc
- 🧠 AI Чат → /ask
- 🎮 Трейдинг → /portfolio, /buy, /sell
- 📰 Новости → /news
- ❓ Ещё → /help
Не видно — скрытые команды:
- /upgrade — оплата Stars (PRO)
- /upgrade_plus — оплата Stars (PRO+)
- /alert 100000 — ценовые сигналы
- /learn — уроки
Mini App (кнопка 📊 BTC слева от ввода):
- Цветовая схема — меняется по сигналу
- AI-саммари, консенсус, график
Хочешь, добавлю кнопки /upgrade и /learn в меню, чтобы было видно?
▣  Build · DeepSeek V4 Pro · 37.4s
обучение /learn уже есть в мини app /upgrade нужно както вмонтировать в мини апп посоветуйся с агентами
Thinking: The user wants to integrate the /upgrade (Stars payment) flow into the Mini App. Let me consult the UI/UX designers and Business Strategist for the best approach.
Currently:
- Bot: /upgrade sends a Telegram Stars invoice via sendInvoice()
- Mini App: no payment UI
The challenge: Telegram Stars payments work through the bot's sendInvoice() API, not through Mini App WebView. The Mini App can't directly process payments. But it CAN:
1. Show a "PRO" tab/card with features and pricing
2. Open the bot chat with /upgrade command via Telegram.WebApp.openTelegramLink()
3. Or use Telegram.WebApp.openInvoice() if available
Let me consult agents for the best Mini App integration approach.
General Task — Consult agents on PRO upgrade UI

---

## Сессия 36: Интеграция /upgrade в Mini App + техдолг (12.05.2026)
- **P0:** `/upgrade` в Mini App — вкладка «💎 PRO» в Мини App (3 sub-таба: Обучение/Игры/PRO), `sendData()` bridge → `web_app_data` handler → `sendInvoice(XTR)`
- Карточки тарифов FREE/PRO/PRO+: текущий тир, фичи, цены в Stars, кнопка подписки
- `GET /miniapp/subscription/status` — API endpoint: tier, trial_until, pro_until, pro_plus_until
- `F.content_type == ContentType.WEB_APP_DATA` — новый handler в subscribe.py
- **P0:** `chatMessages` кэп на 100 записей (сдвиг 20 при переполнении) → предотвращение memory leak в Mini App
- **P1:** `chartDataCache` TTL 60с (был бесконечный кэш) — ключ `{ data, _ts }` вместо сырых свечей
- **P1:** Bootstrap unit-тестов — `tests/` (conftest, test_subscription, test_auth), 19 тестов: Tier, Features, get_user_tier, has_feature, activate_pro/trial, HMAC-аутентификация
- **P2:** Дедупликация `app.js` / `app.v11.js` — удалён v11, index.html → `app.js?v=20260512`
- `pytest` + `pytest-asyncio` добавлены в requirements.txt
- `asyncpg` mock в conftest.py через `sys.modules` для обхода отсутствия нативного модуля на Windows

## Сессия 37: Редизайн Mini App — PRO в навигацию, AI bubble (12.05.2026)
- Bottom nav: 📊 Индикаторы | 🎮 Мини App | 📰 Новости | 💎 PRO (AI анализ убран из навигации)
- Floating AI bubble — круглая кнопка 🧠 над bottom-nav (справа), пульсирующая анимация `ai-glow` (box-shadow 3s ease-in-out) с цветом `--sentiment`
- Chat overlay — полноэкранный модал (z-index 200) с заголовком «🧠 AI Аналитика» и кнопкой закрытия ✕
- Кнопка PRO открывает `renderUpgradePage()` с карточками тарифов, `sendData()` → `sendInvoice(XTR)`
- `renderChat()` больше не вызывает `setActiveNav('chat')` — чат поверх всех вкладок
- `parseHash()` + `navigate()` + `routePage()` — добавлен роут `upgrade`
- CSS: `.chat-overlay`, `.chat-overlay-header`, `.chat-close-btn`, `@keyframes ai-glow`

## Сессия 38: Редизайн Mini App — орбитальная навигация (12.05.2026)
- Замена горизонтального `#bottom-nav` на `#orbital-nav` — 4 кнопки + мозг в одной линии
- 🧠 AI-мозг 72px в центре между Мини App и Новости, в 2× крупнее остальных кнопок, яркая пульсация `ai-glow`
- Кнопки: 📊 Индикаторы | 🎮 Мини App | 📰 Новости | 💎 PRO — на одной горизонтальной оси, зазор от мозга ~8px (под свечение)
- Стеклянная панель `::before` — blur 16px, opacity 0.92, скруглённые верхние углы, `border-top: 2px solid var(--sentiment)` — визуально объединяет навигацию
- Верхние sub-tabs приглушены (12px, opacity 0.85, прозрачные границы) — нижняя орбита читается как главная
- AI-чат — полноэкранный overlay при клике на мозг, кнопка закрытия ✕
- Убран авто-fade орбиты — всегда видима
- `setActiveNav()` переписан с `.nav-btn` на `.orbital-btn`

## Сессия 39: Деплой на новый сервер + HTTPS-туннель (13.05.2026)
- Новый сервер: **89.127.215.15** (Fornex, Ubuntu 24.04, 1 vCPU, 2GB RAM, 20GB SSD)
- Docker 29.4.3 + Docker Compose v5.1.3 установлены через `get.docker.com`
- Git clone `master`, создан `.env` (токен бота, API-ключ OpenCode Go, MINIAPP_URL)
- **P0 fix:** `btcbot/config.py` — `extra="allow"` в model_config, чтобы `POSTGRES_PASSWORD` из docker-compose не ронял сервисы
- **HTTPS Mini App:** Cloudflare quick tunnel → `https://pound-klein-delivery-headlines.trycloudflare.com/miniapp`
- `cloudflared-wrapper.sh` + systemd-сервис: автостарт тунеля, автообновление `.env` при смене URL, перезапуск бота через `up -d --force-recreate`
- Все 6 контейнеров запущены: postgres+redis healthy, collector (Binance WS + 2168 seed), scheduler, API (8000), bot
- API отвечает: `/health` → `{"status":"ok"}`, `/` → `{"status":"backend running"}`
- Кнопка `📊 BTC` в Telegram menu button работает через HTTPS

## Сессия 40: Коридор Меткалфа (13.05.2026)
- **Sigma-Architect** спроектировал архитектуру: модель, API, сбор данных, фронтенд
- `btcbot/metcalfe.py` — `MetcalfeEngine`: формула `price ∝ active_addresses²`, скользящая медиана `k` за 365 дней, коридор ±30%, сигнал overvalued/fair/undervalued
- `btcbot/models.py` — модель `MetcalfeCorridor` (12 полей + history)
- `btcbot/collector.py` — `_metcalfe_loop()`: сбор active_addresses с blockchain.info, раз в 6 часов в `onchain_metrics`
- `backend/api.py` — `GET /miniapp/metcalfe`: вычисление коридора, Redis-кеш 6ч
- `miniapp/app.js`:
  - Карточка «📐 Закон Меткалфа» на дашборде (справедливая цена, коридор, deviation %, адреса)
  - Кнопка 📐 в chart-controls — toggle overlay: 3 линии (upper 🔴, fair 🟡, lower 🟢) на графике
  - `_addLineSeries()` возвращает series для cleanup при переключении
- **Источник:** blockchain.info `n-unique-addresses` (free, no API key)

## Сессия 41: TON Connect + крипто-оплата (13.05.2026)
- **Sigma-Architect** спроектировал: DB, 5 API эндпоинтов, UI, флоу оплаты
- `btcbot/crypto.py` — `TONVerifier`: поиск входящих платежей через TONCenter API, верификация tx_hash
- `btcbot/config.py` — `TON_RECIPIENT_WALLET`, `TON_PRO_PRICE_TON`, `TON_PRO_PLUS_PRICE_TON`, `TONCENTER_API_URL`
- `btcbot/db.py` — таблица `crypto_payments` (user_id, amount_nano, tx_hash, tier, status), колонка `ton_wallet` в `user_subscriptions`
- `backend/api.py` — 5 эндпоинтов:
  - `GET /crypto/wallet/status` — статус кошелька
  - `POST /crypto/wallet/link` — привязка TON-адреса
  - `POST /crypto/payment/create` — создание платежа (ton://transfer URI)
  - `GET /crypto/payment/{id}` — статус (polling frontend)
  - `POST /crypto/payment/{id}/verify` — верификация + активация PRO
- `miniapp/app.js` — селектор оплаты (💎 Stars / 💠 TON), ввод адреса, карточка оплаты, кнопки «Открыть кошелёк» / «Я оплатил», polling статуса каждые 5с
- `miniapp/app.css` — стили `.payment-method-selector`, `.wallet-chip`, `.payment-address`, `.connect-wallet-wrap`
- Существующий Stars-флоу не тронут, крипта — альтернативный путь