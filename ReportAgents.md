# BTC Monitor — Сводка для агентов

## Проект
Telegram-бот для аналитики Bitcoin (тех. индикаторы + on-chain + ML-прогноз + новости + обучение). В будущем — веб-платформа для анализа финансов и инвестиций.

## Текущий статус
- **Оценка архитектуры (Sigma-Architect):** 4.3/10
- **Пользователей:** 0 (не запущен публично)
- **DAU:** 0

## Стек
- **Бэкенд:** Python 3.12, asyncpg, TimescaleDB, Redis, aiogram 3.x, FastAPI
- **ML:** LightGBM → ONNX (24 признака, 3 класса: BUY/HOLD/SELL)
- **Инфра:** Docker Compose (6 сервисов: postgres, redis, collector, scheduler, api, bot)
- **Данные:** Binance WS (цены), Bitview.space (on-chain), Bybit/OKX (фьючерсы), CoinGecko (backup), Google News RSS

## Команды бота
| Команда | Описание |
|---|---|
| `/btc` | Цена, тех. индикаторы (RSI, BB, MACD, MA50/100/200), сигнал, on-chain (MVRV, цикл) |
| `/predict` | 3-уровневый прогноз: 4h (ML), 1w (on-chain), long-term (контекст) |
| `/news` | Пульс рынка: тональность новостей, индекс тревоги, комментарий Аналитика |
| `/learn` | 20 уроков азбуки крипты (все метрики проекта) |
| `/subscribe` | Подписка на алерты (RSI, MA Cross, Volume Spike) |
| `/alerts` | Управление подписками |
| `/start` | Приветствие, список команд |
| `/help` | Справка |

## Агенты (25 шт)
`accountant` · `advertiser` · `architect` · `business_consultant` · `business_strategist` · `content_producer` · `data_analyst` · `developer` · `editor` · `finance_analyst` · `hr_recruiter` · `lawyer` · `marketbrain` · `pr_specialist` · `project_manager` · `promptmaster` · `screenwriter` · `seller` · `seo_specialist` · `smm_specialist` · `teacher` · `tester` · `ui_designer` · `ux_designer` · `writer`

## Последние изменения (сессия 08.05.2026)

### UI/UX (ui_designer)
- Единый стиль заголовков через `·`
- Разделители `──` для иерархии
- Унифицированные футеры `♻️ Обновление: ...`
- Markdown во всех командах

### Контент (content_producer, teacher)
- `/learn` — 20 уроков по индикаторам и метрикам

### Стратегия (business_strategist)
- **Топ-3:** стабильность → запуск → аналитика
- Монетизация: Freemium + Binance referral → Telegram Stars Premium

### Индикаторы (finance_analyst)
- В `/btc` добавлены: BB, MACD, MA100, MVRV, фаза цикла

### Архитектура (Sigma-Architect)
- Оценка 4.3/10, топ-5 проблем
- **Исправлено:** batch insert, CoinGlass guard, volume mount, Analyzer singleton
- **Заменены API:** Glassnode → Bitview, CoinGlass → Bybit/OKX (всё бесплатно)
- **Добавлено:** continuous aggregate `candles_1m`, retention policy 7 дней

### Маркетинг (smm, advertiser, seo, pr, business_strategist)
- 2 нед бесплатно → Telegram Ads + Яндекс.Директ
- Каналы: Twitter/X, Reddit, Pikabu/VC.ru, Telegram-чаты
- **KPI для веб-платформы:** 3K+ юзеров, >200 DAU, >15% подписок за 3 мес

## Известные проблемы
- LightGBM не обучен (нет 48ч истории)
- Нет тестов
- Нет CI/CD
- Нет мониторинга
- Нет публичного запуска (@BotFather)

## Контакты
- **Бот:** @ нет (не запущен)
- **API:** localhost:8000
- **История разработки:** HistoryDev.md
