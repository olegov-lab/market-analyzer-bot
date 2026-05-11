# BTC Monitor — Roadmap v2.0

## Консультация агентов: Sigma-Architect + UI/UX Designer + Market-Brain + Business Strategist

**Дата:** 11.05.2026  
**Агенты:** Sigma-Architect (GLM-5.1), UI/UX Designer (Kimi K2.6), Market-Brain (DeepSeek V4 Pro), Business Strategist (DeepSeek V4 Pro)

---

## Исправленный порядок фаз (Business Strategist — КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ)

> Монетизацию не откладывают на «когда продукт будет идеальным». Её запускают на том, что работает сейчас, и дорабатывают по деньгам клиентов.

| Фаза | Недели | Фокус |
|------|--------|-------|
| **1. UX + Монетизация MVP** | 1–2 | 4-button меню, тема, MVPS (80 ⭐ PRO) |
| **2. Аналитика + AI-саммари** | 3–4 | Consensus %, AI-интерпретация, Metcalfe |
| **3. AI-эволюция** | 5–7 | Голос, проактивные алерты, [Chart] в чате |
| **4. Геймификация** | 8–10 | Лиги, турниры, P&L-карточки, рефералы 2.0 |
| **5. Web3 / TON Connect** | 11–13 | Крипто-оплаты, NFT-бейджи |
| **6. Масштабирование** | 14+ | API-first, биржевые партнёрства, B2B |

---

## Фаза 1: UX + Монетизация MVP (Недели 1–2)

### 1.1 Reply-меню → 4 кнопки
**Файлы:** `bot/state.py`, `bot/handlers/btc.py`, `bot/handlers/info.py`, `bot/handlers/menu.py` (new)

```
Текущее: 14 кнопок
Новое:   [📊 Аналитика] [🧠 AI Чат] [🎮 Трейдинг] [📰 Новости]
```

`/btc` — объединяет цену + индикаторы + сигнал. Inline-кнопки: [📈 Прогноз] [📊 Волатильность] [🔔 Подписки]  
`/help` — хаб для `/learn`, `/subscribe`, `/alerts`, `/volatility` (inline)

### 1.2 Динамическая цветовая схема
**Файлы:** `miniapp/styles.css`, `miniapp/app.js`

CSS-переменные `--sentiment`, `--sentiment-rgb`, `--sentiment-glow`:
- Bullish → зелёный (#00c853)
- Bearish → красный (#ff1744)  
- Neutral → синий (#2481cc)

JS: `document.documentElement.setAttribute('data-sentiment', sentiment)`  
Telegram: `setHeaderColor()` + `setBackgroundColor()`

### 1.3 MVPS — монетизация Telegram Stars
**Файлы:** `btcbot/subscription.py` (new), `backend/api.py`, `bot/handlers/subscribe.py`

**PRO (80 ⭐/мес):** ∞ AI-вопросов, продвинутые алерты, безлимит сделок, бейдж PRO  
**PRO+ (200 ⭐/мес):** голос, упреждающие алерты, confidence score ML, персональный дашборд

**Бесплатный триал:** 3 дня PRO при первом `/start`

**Платёж:** Telegram Stars → `sendInvoice()` → `pre_checkout_query` → `successful_payment`

### 1.4 Лимиты для FREE
- 3 AI-вопроса/день (Redis `ask_count:{user_id}` TTL 24h)
- 3 сделки/день в симуляторе
- Базовые алерты (RSI, MA Cross, Volume Spike)

### 1.5 Haptic Feedback — усиление
**Файл:** `miniapp/app.js`

| Триггер | Тип |
|---------|-----|
| Переключение таймфрейма | `medium` |
| BUY/SELL в симуляторе | `medium` |
| Прибыльная сделка | `success` |
| Pull-to-refresh | `medium` |
| Переключение sub-tab | `selectionChanged` |

### KPI Фазы 1
- 500 установок, 40 DAU, Day-1 Retention ≥25%
- 5+ платящих (1% конверсия)
- Время до первой покупки ≤5 дней

---

## Фаза 2: Аналитика + AI-интерпретация (Недели 3–4)

### 2.1 Indicator Consensus %
**Файлы:** `btcbot/analyzer.py` — `compute_consensus()`, `backend/api.py` — `GET /miniapp/consensus`

13 индикаторов, 4 группы с весами:
- **Тренд (30%):** MA50, MA200, MACD
- **Моментум (25%):** RSI, BB-позиция, OBV
- **On-chain (25%):** MVRV Z, SOPR, NUPL, Puell
- **Сентимент (20%):** Fear & Greed, Funding Rate, L/S Ratio

Каждый голосует: +1 (bullish), -1 (bearish), 0 (neutral).  
Итог: `bullish_pct` 0–100% с бейджем low_confidence если <50% индикаторов доступны.

### 2.2 AI-саммари индикаторов
**Файлы:** `btcbot/summarizer.py` (new), `backend/api.py` — `GET /miniapp/summary`

5 групп для AI-интерпретации: Тренд, Моментум, Волатильность, On-chain, Сентимент.  
Промпт в `marketbrain.json` — строгие правила интерпретации (RSI>70=перекупленность, MVRV Z<0.5=недооценён, etc.).  
Кеш Redis 5 мин. Предварительный прогрев при старте.

### 2.3 Metcalfe Corridor
**Файлы:** `btcbot/analyzer.py` — `metcalfe_corridor()`, `backend/api.py` — `GET /miniapp/metcalfe`

Fair Value = (daily active addresses)² × k. Коридор: ×1.5 / ×0.5.  
Нужен сбор `active_addresses` — добавить в `collector.py` (Bitview/Glassnode).

### KPI Фазы 2
- 1,500 установок, 120 DAU, Day-7 Retention ≥18%
- 30+ платящих (2%), MRR ≥2,800 Stars

---

## Фаза 3: AI-эволюция (Недели 5–7)

### 3.1 Голосовой ввод
**Файлы:** `miniapp/index.html` — VAD-библиотека, `miniapp/app.js` — кнопка микрофона  
`backend/api.py` — `POST /miniapp/ask/voice` (multipart WAV → Whisper → AI → ответ)

### 3.2 Проактивные AI-алерты
**Файлы:** `btcbot/scheduler.py` — `check_proactive_triggers()`, `btcbot/breakout.py` (new)

Триггеры: MA50/MA200 пробой, BB-касание, RSI экстрим, MVRV-зона, F&G-экстрим.  
Кулдаун Redis: `proactive:cooldown:{user_id}:{trigger}` (2–24ч в зависимости от типа).  
Формат: 🚨 сигнал + AI-объяснение + [📊 График] [📈 Симулятор] [🔕 Отписаться]

### 3.3 [View on Chart] в AI-чате
**Файлы:** `agents/marketbrain.json` — инструкция по маркерам, `miniapp/app.js` — парсер

Маркер: `[CHART:1d:MA200]` → фронтенд заменяет на кликабельную кнопку.  
Telegram-бот: заменяет на inline-ссылку на Mini App с deep-link параметром.

### KPI Фазы 3
- 3,500 установок, 280 DAU, Day-30 Retention ≥12%
- 80+ платящих (2.3%), PRO+ ≥15%

---

## Фаза 4: Геймификация (Недели 8–10)

### 4.1 Лиги и Турниры
**Файлы:** `btcbot/game.py`, `migrations/versions/004_leagues.py`

Лиги: Bronze (<$0 P&L), Silver ($0-1K), Gold ($1K+).  
Турниры: «Битва за Халвинг» — сброс баланса, фиксированный срок, призы Stars.

### 4.2 P&L-карточки + Рефералы 2.0
**Файлы:** `btcbot/referral.py` (new), `backend/api.py` — `POST /miniapp/game/pnl-card`

Генератор PNG-карточек для историй (Pillow).  
Реферальная программа — бонусы «виртуальными долларами» на игровой счёт.

### KPI Фазы 4
- 5,500 установок, 500 DAU, Day-30 Retention ≥18%
- 150+ платящих, ≥50 рефералов

---

## Фаза 5: Web3 / TON Connect (Недели 11–13)

### 5.1 TON Connect 2.0
**Файлы:** `miniapp/tonconnect.js` (new), `miniapp/tonconnect-manifest.json`

Подключение Telegram Wallet + сторонних TON-кошельков.  
Верификация подписи → сохранение `wallet_address`.

### 5.2 Крипто-платежи
**Файлы:** `backend/api.py` — `POST /subscription/pay/ton`, `/pay/usdt`

TON/USDT-перевод → проверка через TON Center API → активация подписки.  
Оплата через Stars остаётся основным каналом.

### KPI Фазы 5
- 8,000 установок, 700 DAU
- 250+ платящих, ≥20% оплат криптой
- ≥3 B2B-клиента

---

## Фаза 6: Масштабирование (Недели 14+)

- API-first: роутеры `backend/routers/`, версионирование, OpenAPI для мобильных SDK
- Биржевые рефералки (Binance/OKX/Bybit)
- B2B White Label для крипто-каналов (2,900 ₽/мес)
- Мультиязычность (украинский, казахский)

---

## Конкурентные преимущества (на чём усилить фокус)

| Преимущество | Действие |
|-------------|----------|
| 25 AI-агентов на русском | PROMO: «25 AI-аналитиков в твоём кармане» |
| On-chain + Теханализ в одном окне | Страница `/whypro` — сравнение с CryptoQuant ($50) |
| Бумажная торговля | Ежедневные турниры, призы PRO-подпиской |
| ML-прогноз на 24 признаках | Показать историческую точность (бэктест) |
| Бесплатные on-chain метрики | Усилить до 10+ метрик (сейчас Bitview даёт 6) |

---

## Ценовые тиры

| Тир | Рубли | Stars | Что внутри |
|-----|-------|-------|------------|
| **FREE** | 0 ₽ | 0 ⭐ | Базовый анализ, 3 AI-вопроса/день, 3 сделки/день |
| **PRO** | 290 ₽ | 80 ⭐ | ∞ AI, продвинутые алерты, безлимит сделок, бейдж PRO |
| **PRO+** | 790 ₽ | 200 ⭐ | Голос, упреждающие алерты, confidence score, персональный дашборд |

---

## Файловая структура изменений (Фазы 1–3)

```
Новые файлы:
  btcbot/subscription.py      — Тир-модель, проверка подписки, статус-машина платежей
  btcbot/summarizer.py        — AI-генерация текстовых саммари
  btcbot/breakout.py          — Проактивные AI-алерты
  btcbot/referral.py          — Реферальная система
  bot/handlers/menu.py         — Централизованная фабрика inline-клавиатур
  bot/handlers/subscribe.py    — Обработчики Telegram Stars
  miniapp/tonconnect.js        — TON Connect интеграция
  migrations/versions/003_subscription_tiers.py

Изменяемые файлы:
  bot/state.py                 — menu_kb → 4 кнопки
  bot/handlers/btc.py          — Inline-клавиатуры в ответах
  bot/handlers/ask.py          — Лимит 3 вопроса + маркер CHART
  bot/handlers/info.py         — /help как хаб
  btcbot/analyzer.py           — compute_consensus(), metcalfe_corridor(), ai_summary()
  btcbot/db.py                 — user_subscription CRUD, on-chain metric queries
  btcbot/scheduler.py          — check_proactive_triggers(), check_price_alerts()
  btcbot/config.py             — тиры и фича-флаги
  backend/api.py               — Новые эндпоинты, @requires_pro декоратор
  agents/marketbrain.json      — Правила маркеров [CHART] и саммари
  miniapp/styles.css           — --sentiment переменные, premium-бейджи
  miniapp/app.js               — setSentiment(), parseChartMarkers(), haptic upgrade
  miniapp/index.html           — Микрофон (VAD), TON Connect SDK
```

---

## Стратегический чек-лист на первые 2 недели

- [ ] 4-button Reply-меню
- [ ] Динамическая цветовая схема (bullish/bearish)
- [ ] MVPS: Telegram Stars оплата (sendInvoice)
- [ ] Бесплатный 3-дневный триал
- [ ] Лимит 3 AI-вопроса/день для FREE
- [ ] Лимит 3 сделки/день для FREE
- [ ] Страница `/whypro` — сравнение с конкурентами
- [ ] Бейдж PRO в `/portfolio`
- [ ] Haptic upgrade (medium/success)
- [ ] Публичный запуск + Директ 5K ₽
