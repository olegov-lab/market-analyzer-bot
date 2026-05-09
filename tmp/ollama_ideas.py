import ollama
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open('bot/main.py', 'r', encoding='utf-8') as f:
    source = f.read()

funcs = {}
for name in ['btc', 'predict', 'news_cmd']:
    start = source.find(f'async def {name}(')
    end = source.find('@dp.message', start + 1)
    if end == -1:
        end = source.find('async def ', start + 1)
    if end == -1:
        end = len(source)
    funcs[name] = source[start:end]

client = ollama.Client(host='http://localhost:11434')

# UI Designer prompt
ui_prompt = f"""Ты — UI-дизайнер Telegram ботов. Вот код трёх функций бота BTC Monitor:

Функция btc():
{funcs['btc'][:1500]}

Функция predict():
{funcs['predict'][:1500]}

Функция news_cmd():
{funcs['news_cmd'][:1500]}

Дай 7 конкретных, готовых к реализации предложений по улучшению визуального оформления ответов.

Для КАЖДОГО предложения:
- Название
- Что менять (конкретно, строка кода или структура)
- Почему это улучшит восприятие
- Пример форматирования (покажи как будет выглядеть результат в Telegram)

Telegram поддерживает: Markdown (**жирный**, *курсив*, `код`, ~~зачёркнутый~~, ||спойлер||) и HTML (<b>, <i>, <code>, <s>, <tg-spoiler>). Цвет текста НЕ поддерживается. Emoji можно.

Пиши на русском языке. Будь максимально конкретен."""

resp1 = client.chat(model='llama3.1:8b', messages=[{'role': 'user', 'content': ui_prompt}], options={'num_predict': 4096})
print('=== UI DESIGNER (llama3.1:8b) ===')
print()
print(resp1['message']['content'])
print()
print('=' * 60)
print()

# UX Designer prompt
ux_prompt = f"""Ты — UX-дизайнер Telegram ботов. Проанализируй пользовательский опыт бота BTC Monitor.

Как сейчас выглядит ответ /btc:
{funcs['btc'][:2000]}

Как сейчас выглядит ответ /predict:
{funcs['predict'][:2000]}

Дай 5 конкретных рекомендаций по улучшению читаемости и пользовательского опыта.

Учти:
- Пользователь читает с мобильного телефона
- Важна скорость восприятия (scanability)
- Первое, что видит пользователь — заголовок
- Информация должна быть сгруппирована логически
- Должен быть виден статус/состояние

Для каждой рекомендации: проблема -> решение -> пример кода форматирования.

Пиши на русском."""

resp2 = client.chat(model='qwen2.5:14b', messages=[{'role': 'user', 'content': ux_prompt}], options={'num_predict': 4096})
print('=== UX DESIGNER (qwen2.5:14b) ===')
print()
print(resp2['message']['content'])
