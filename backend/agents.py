import json
import os
from typing import Optional

from openai import AsyncOpenAI

from btcbot.config import settings

AGENTS_DIR = os.path.join(os.path.dirname(__file__), "..", "agents")


GO_MODEL_MAP = {
    "deepseek-v4-pro": "deepseek-v4-pro",
    "deepseek v4 pro": "deepseek-v4-pro",
    "glm-5.1": "glm-5.1",
    "glm 5.1": "glm-5.1",
    "kimi-k2.6": "kimi-k2.6",
    "kimi k2.6": "kimi-k2.6",
}

# Models that work well for agentic tasks (fast, return content directly)
AGENT_MODEL = "qwen3.6-plus"

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.opencode_go_api_key,
            base_url=settings.opencode_go_endpoint,
            timeout=30.0,
            max_retries=0,
        )
    return _client


def _resolve_model(model_str: str) -> str:
    key = model_str.strip().lower()
    return GO_MODEL_MAP.get(key, "deepseek-v4-pro")


def load_agent(name: str) -> Optional[dict]:
    path = os.path.join(AGENTS_DIR, f"{name}.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_agents() -> list[dict]:
    agents = []
    for fname in sorted(os.listdir(AGENTS_DIR)):
        if fname.endswith(".json"):
            path = os.path.join(AGENTS_DIR, fname)
            with open(path, encoding="utf-8") as f:
                agent = json.load(f)
            agents.append({
                "name": agent.get("name", fname.replace(".json", "")),
                "model": _resolve_model(agent.get("model", "")),
                "style": agent.get("style", ""),
            })
    return agents


def build_system_prompt(agent: dict) -> str:
    instructions = agent.get("instructions", [])
    style = agent.get("style", "")
    base = style + "\n\n" if style else ""
    return base + "\n".join(instructions)


async def ask_agent(agent_name: str, prompt: str, temperature: Optional[float] = None) -> Optional[str]:
    agent = load_agent(agent_name)
    if not agent:
        return None

    model = _resolve_model(agent.get("model", ""))
    system = build_system_prompt(agent)
    temp = temperature if temperature is not None else agent.get("temperature", 0.7)

    client = _get_client()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temp,
            max_tokens=agent.get("max_tokens", 4096),
        )
        msg = resp.choices[0].message
        content = msg.content or ""
        reasoning = getattr(msg, "reasoning_content", None) or ""
        return content or reasoning or "[empty response]"
    except Exception as e:
        return f"[Agent error: {e}]"
