import ollama
import json

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

combined = "\n\n---\n\n".join(v[:1200] for v in funcs.values())

ui_prompt = f"""Ты UI-дизайнер Telegram ботов. Код трёх функций бота:

{combined}

Дай 7 идей улучшения визуала ответов. Telegram: Markdown(**жирный**,*курсив*,`код`,~~зачёркнутый~~,||спойлер||) + HTML. Цвета текста НЕТ.

Формат:
## Название
- Что менять
- Почему
- Пример форматирования

На русском."""

resp1 = client.chat(model='llama3.1:8b', messages=[{'role': 'user', 'content': ui_prompt}])
with open('tmp/ui_designer_output.txt', 'w', encoding='utf-8') as f:
    f.write(resp1['message']['content'])

ux_prompt = f"""Ты UX-дизайнер. Тот же бот:

{combined}

5 рекомендаций по читаемости с мобильного. Проблема->Решение->Пример. На русском."""

resp2 = client.chat(model='qwen2.5:14b', messages=[{'role': 'user', 'content': ux_prompt}])
with open('tmp/ux_designer_output.txt', 'w', encoding='utf-8') as f:
    f.write(resp2['message']['content'])

print("DONE")
