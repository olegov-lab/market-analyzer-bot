# BTC Monitor — История разработки (сокр.)

## 1-2: Проектирование + ядро
6 микросервисов (Telegram/Collector/Analyzer/Scheduler/Alerts/API), PostgreSQL+TimescaleDB+Redis, Binance WS+CoinGecko+Glassnode+CoinGlass. LightGBM на 4H, pandas_ta индикаторы.

## 3: Полная система прогнозов
Short-term: LightGBM (BUY/HOLD/SELL, ATR×2.5=95%CI). Mid-term: rule-based on-chain (MVRV/SOPR/NUPL/Puell/RHODL). Long-term: MVRV Z-Score, 200W MA, халвинг. Liquidity zones.

## 4-5: Баг-фиксы
UPSERT подписок, сбор OI с CoinGlass, volume spike ночью/выходные 2x вместо 3x.

## 6-8: Новости + русский язык
Google News RSS с тональностью (BULLISH/BEARISH), русскоязычные статьи, единый стиль команд.

## 9-12: Ревью + стратегия
Arch Rev 6/10: DB write amplification, нет volume mount. UI/UX: разделители, футеры. Content: /learn 20 уроков. Business: Freemium + Binance referral + Telegram Stars.

## 13: Расширение /btc
BB(20,2), MACD, MA50/100/200, MVRV Z-Score, фаза цикла.

## 14-15: Архитектурные блокеры
PriceBuffer (batch INSERT), CoinGlass guard, Glassnode→Bitview.space, CoinGlass→Bybit/OKX public API, единый Analyzer, continuous aggregates, retention 7→180 дней.

## 16: Маркетинг
Twitter/Reddit/Telegram/Pikabu/VC.ru + Telegram Ads + Яндекс.Директ, бюджет 65-130K ₽/мес.

## 17: Архитектор — исправления
N+1 → JOIN+unnest, LightGBM в run_in_executor, Bitview loop, Redis единый ключ.

## 18: Продвижение
BotFather настройка, 6 каталогов РФ. Username: Market04ekBot.

## 19: Деплой на Aeza
Ubuntu 24.04, Docker, network_mode:host из-за iptables хостера.

## 20: Аудит (5.5/10)
Удалены мёртвые конфиги/зависимости (onnxruntime ~500MB), дедупликация алертов, VolumeTracker, утечка ClientSession. Инцидент: .env удалён git reset --hard.

## 21: Telegram Mini App + Cloudflare
SPA (Vanilla JS, 5 вкладок), MenuButton, HMAC-SHA256 auth, Cloudflare tunnel. /start с новостями.

## 22: Массовый фикс P0-P2 (4.5/10)
P0: баг user_id=alert_type, дублирование кода, race condition _lgb_model. P1: CORS, единая сессия, run_in_executor. P2: XSS, rate limiting, .env.example. /daily_news.

## 23: AI Chat /ask
Market-Brain (DeepSeek V4 Pro), rate limit 30с.

## 24: Fear & Greed + Price Alerts
alternative.me API, price alerts таблица.

## 25: AI Chat Mini App + Chart + Volatility
TradingView lightweight-charts, volatility risk meter.

## 26: Codebase review 4 агентами
14+22 бага, SQL injection, XSS. Фиксы: safe_gather, PriceBuffer clear.

## 27-29: Mini App редизайн
4 вкладки, hash-схема, bottom nav glassmorphism, график как sub-tab.

## 30: Торговый симулятор
$10K виртуальный счёт, /buy/sell/portfolio/leaderboard, GameEngine.

## 31: Фаза 1 — MVPS + монетизация
ROADMAP.md, 72h trial, FREE/PRO/PRO_PLUS, Telegram Stars, динамическая цветовая схема.

## 32: Фаза 2 — AI Сводка + Консенсус + Seed
summarizer, compute_consensus(), seed 90 дней истории CoinGecko. 5 P0 fix.

## 33: OpenCode Go модели
Ollama→OpenCode Go, 25 агентов, SQL time_bucket, candles_4h materialized view, Redis-кеш.

## 34: 5 fix надёжности
Stars оплата sendInvoice(XTR), Redis для ask_tasks, VolumeTracker deque.

## 35: Фаза 3 — AI Evolution
[CHART] маркеры в AI-ответах, ProactiveAlertEngine (7 триггеров), голосовой ввод, AI Daily Story.

## 36: /upgrade в Mini App + техдолг
PRO вкладка, chatMessages кэп 100, chartDataCache TTL 60с, 19 unit-тестов.

## 37-38: Редизайн навигации
Floating AI bubble, орбитальная навигация (4 кнопки + 🧠 72px в центре).

## 39: Деплой на Fornex + HTTPS
89.127.215.15, Cloudflare quick tunnel, cloudflared-wrapper.

## 40: Коридор Меткалфа
price ∝ active_addresses², скользящая медиана 365д, коридор ±30%. blockchain.info.

## 41: TON Connect
Крипто-оплата: TONCenter API, ton://transfer, 5 API эндпоинтов.

## 42: Геймификация — Арена
Лиги (B/S/G/Platinum), турниры, рефералы ($5 бонус), P&L-карточка.

## 43: Голосовой ввод Whisper
OpenAI Whisper → Google STT fallback, ffmpeg конвертация.

## 44-45: Инциденты деплоя
2 бота с одним токеном, смена токена. Критический инцидент: 5 причин (токен, .env, cloudflared loop, postgres password, .pyc cache). LAST_URL dedup.

## 46: Перезапуск
restart:unless-stopped, Docker DNS 8.8.8.8, postgres password сброс. 6 OpenCode sub-агентов.

## 47: Оптимизация AI
asyncio.gather summarizer, timeout 30s, async dashboard, ~500ms (было 5-15с).

## 48: OpenRouter fallback
OpenCode Zen 500 → OpenRouter free tier, rule-based fallback при недоступности AI.

## 49: Локальные агенты Ollama
8 моделей, 26 .md агентов, конвертация из JSON.

## 50: Стабилизация
Named Tunnel (btc.smartmarkettoday.com), memory limits, health_check.py, OOMScoreAdjust, Docker prune.

## 51: Три игры
🔮 Угадай цену (ежедневный конкурс до 50⭐), 🏅 16 ачивок, ⛏ Майнинг tap-to-earn (Redis).

## 52: Апгрейд сервера + OOM-стаб
2 vCPU/3GB/25GB, 2GB swap, memory limits увеличены, Telegram-алерты в health_check.

## 53: Оптимизация
pool_size 60→18 коннектов, FREE-лимиты убраны, рефералы активированы, /donate.

## 54: Биткоин-рулетка
1-10⭐, x0(40%)/x1.5(30%)/x2(20%)/x3(9%)/💎x5(1%). 32 теста.

## 55: Auto-seed + /timezone
_auto_seed(), /timezone 15 поясов, _ts_for() user-timezone, _rsi_bar восстановлена.

## 56: AI fix + мини-игры
OpenRouter rate-limit → OpenCode Go primary, 13 команд в меню, OOM-фильтр, _clear_tz_cache.

## 57: Рефакторинг + OOM Postgres
_rsi_bar модульная, update_rsi_cache. P0: get_all_onchain_metrics_since без LIMIT → OOM. Добавлены LIMIT 10000/2000, get_latest_onchain_metrics(), sequential await.

---
**Текущее:** Сервер Fornex 2vCPU/3GB/25GB. 6 контейнеров. Named Tunnel btc.smartmarkettoday.com. 90 дней истории, LightGBM+Metcalfe. Известно: network_mode:host, нет кэп chatMessages.
