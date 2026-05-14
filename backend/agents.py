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

OPENROUTER_MODEL_MAP = {
    "deepseek-v4-pro": "minimax/minimax-m2.5:free",
    "glm-5.1": "minimax/minimax-m2.5:free",
    "kimi-k2.6": "minimax/minimax-m2.5:free",
}

AGENT_MODEL = "qwen3.6-plus"

_client: Optional[AsyncOpenAI] = None
_openrouter_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.opencode_go_api_key,
            base_url=settings.opencode_go_endpoint,
            timeout=45.0,
            max_retries=1,
        )
    return _client


def _get_openrouter_client() -> AsyncOpenAI:
    global _openrouter_client
    if _openrouter_client is None:
        _openrouter_client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=60.0,
            max_retries=2,
        )
    return _openrouter_client


def _resolve_model(model_str: str) -> str:
    key = model_str.strip().lower()
    return GO_MODEL_MAP.get(key, "deepseek-v4-pro")


def _resolve_openrouter_model(model_str: str) -> str:
    key = model_str.strip().lower()
    return OPENROUTER_MODEL_MAP.get(key, settings.openrouter_model)


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

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    if settings.openrouter_api_key:
        return await _ask_openrouter(agent, messages, temp)

    return await _ask_opencode(model, messages, temp)


async def _ask_opencode(model: str, messages: list, temperature: float) -> Optional[str]:
    client = _get_client()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=4096,
        )
        msg = resp.choices[0].message
        content = msg.content or ""
        reasoning = getattr(msg, "reasoning_content", None) or ""
        return content or reasoning or "[empty response]"
    except Exception as e:
        return f"[Agent error: {e}]"


async def _ask_openrouter(agent: dict, messages: list, temperature: float) -> Optional[str]:
    model = _resolve_openrouter_model(agent.get("model", ""))
    max_tokens = agent.get("max_tokens", 4096)
    client = _get_openrouter_client()

    extra_headers = {
        "HTTP-Referer": "https://github.com/anomalyco/opencode",
        "X-Title": "BTC Monitor",
    }

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_headers=extra_headers,
        )
        msg = resp.choices[0].message
        content = msg.content or ""
        reasoning = getattr(msg, "reasoning", None) or ""
        return content or reasoning or "[empty response]"
    except Exception as e:
        return f"[Agent error: {e}]"
