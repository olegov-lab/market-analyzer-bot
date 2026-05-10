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

## Workflow
- **All coding must be done in collaboration with Sigma-Architect (DeepSeek-R1:14b) and Rapid-Dev (DeepSeek-Coder-V2:16b).**
- Before making ANY code changes: consult the architect first via the `task` tool with subagent_type="general".
- The architect provides detailed implementation plans; the developer implements them exactly.
- Rapid-Dev assists with implementation details, code review, and debugging.
- After implementation, deploy and verify on the server: `scp` → `docker cp` → `docker restart`.
