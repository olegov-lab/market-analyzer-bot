# Agent Configuration

## Ollama Connection
- **Host**: http://localhost:11434
- **Python package**: `ollama` (installed)
- **Usage**: `ollama.Client(host="http://localhost:11434")`

## Available Models
- deepseek-r1:14b (Sigma-Architect)
- deepseek-coder-v2:16b (Rapid-Dev)
- qwen2.5:14b (Market-Brain, Break-Hunter)
- llama3.1:8b (Prompt-Master)
- deepseek-r1:8b, deepseek-r1:32b
- codellama:7b-instruct, deepcoder:14b

## Agents
Agents defined in `agents/*.json` — each has name, model, style, and instructions.

## Backend
- `uvicorn backend.api:app --reload` to start
- Endpoints: `/`, `/health`, `/models`, `/agents`

## Bot
- Telegram bot in `bot/main.py`
- Token from `.env` -> `TELEGRAM_BOT_TOKEN`
