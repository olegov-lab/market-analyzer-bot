import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents import (
    _resolve_model,
    build_system_prompt,
    load_agent,
    list_agents,
    ask_agent,
    GO_MODEL_MAP,
    AGENT_MODEL,
    AGENTS_DIR,
)


class TestResolveModel:
    def test_exact_match(self):
        assert _resolve_model("deepseek-v4-pro") == "deepseek-v4-pro"
        assert _resolve_model("glm-5.1") == "glm-5.1"
        assert _resolve_model("kimi-k2.6") == "kimi-k2.6"

    def test_case_insensitive_with_spaces(self):
        assert _resolve_model("DeepSeek V4 Pro") == "deepseek-v4-pro"
        assert _resolve_model("GLM 5.1") == "glm-5.1"

    def test_unknown_model_defaults(self):
        assert _resolve_model("unknown-model") == "deepseek-v4-pro"
        assert _resolve_model("") == "deepseek-v4-pro"

    def test_go_model_map_complete(self):
        assert len(GO_MODEL_MAP) == 6
        assert "deepseek-v4-pro" in GO_MODEL_MAP


class TestBuildSystemPrompt:
    def test_with_style_and_instructions(self):
        agent = {
            "style": "professional",
            "instructions": ["Be concise.", "Use Russian."],
        }
        prompt = build_system_prompt(agent)
        assert "professional" in prompt
        assert "Be concise." in prompt
        assert "Use Russian." in prompt

    def test_without_style(self):
        agent = {
            "instructions": ["Just do it."],
        }
        prompt = build_system_prompt(agent)
        assert "Just do it." in prompt
        assert not prompt.startswith("\n")

    def test_empty_instructions(self):
        agent = {
            "style": "casual",
            "instructions": [],
        }
        prompt = build_system_prompt(agent)
        assert "casual" in prompt


class TestLoadAgent:
    def test_loads_existing_agent(self):
        agent = load_agent("marketbrain")
        assert agent is not None
        assert agent["name"] == "Market-Brain"
        assert "model" in agent

    def test_returns_none_for_missing_agent(self):
        agent = load_agent("nonexistent_agent_xyz")
        assert agent is None

    def test_agent_has_instructions(self):
        agent = load_agent("marketbrain")
        assert isinstance(agent["instructions"], list)
        assert len(agent["instructions"]) > 0


class TestListAgents:
    def test_returns_list_of_dicts(self):
        agents = list_agents()
        assert isinstance(agents, list)
        assert len(agents) > 0
        for a in agents:
            assert "name" in a
            assert "model" in a

    def test_contains_marketbrain(self):
        agents = list_agents()
        names = [a["name"] for a in agents]
        assert "Market-Brain" in names

    def test_all_agents_have_valid_model(self):
        agents = list_agents()
        valid = set(GO_MODEL_MAP.keys())
        for a in agents:
            if a["model"] != "deepseek-v4-pro":
                assert a["model"] in valid, f"Unknown model: {a['model']}"


class TestAskAgent:
    @pytest.mark.asyncio
    async def test_returns_none_for_missing_agent(self):
        result = await ask_agent("nonexistent", "hello")
        assert result is None

    @pytest.mark.asyncio
    async def test_successful_response(self):
        mock_client = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.content = "Hello from AI"
        mock_msg.reasoning_content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("backend.agents._get_client", return_value=mock_client), \
             patch("backend.agents.load_agent") as mock_load:
            mock_load.return_value = {
                "name": "Test",
                "model": "glm-5.1",
                "instructions": ["Be helpful."],
                "style": "friendly",
            }

            result = await ask_agent("test", "Hi", temperature=0.5)
            assert result == "Hello from AI"

    @pytest.mark.asyncio
    async def test_falls_back_to_reasoning_content(self):
        mock_client = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.content = ""
        mock_msg.reasoning_content = "Thinking process..."
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("backend.agents._get_client", return_value=mock_client), \
             patch("backend.agents.load_agent") as mock_load:
            mock_load.return_value = {
                "name": "Test",
                "model": "deepseek-v4-pro",
                "instructions": [],
                "style": "",
            }

            result = await ask_agent("test", "Hi")
            assert result == "Thinking process..."

    @pytest.mark.asyncio
    async def test_empty_response_returns_placeholder(self):
        mock_client = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.content = None
        mock_msg.reasoning_content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("backend.agents._get_client", return_value=mock_client), \
             patch("backend.agents.load_agent") as mock_load:
            mock_load.return_value = {
                "name": "Test",
                "model": "kimi-k2.6",
                "instructions": [],
                "style": "",
            }

            result = await ask_agent("test", "Hi")
            assert result == "[empty response]"

    @pytest.mark.asyncio
    async def test_api_error_returns_agent_error(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Connection timeout")
        )

        with patch("backend.agents._get_client", return_value=mock_client), \
             patch("backend.agents.load_agent") as mock_load:
            mock_load.return_value = {
                "name": "Test",
                "model": "glm-5.1",
                "instructions": [],
                "style": "",
            }

            result = await ask_agent("test", "Hi")
            assert "[Agent error:" in result
            assert "Connection timeout" in result

    @pytest.mark.asyncio
    async def test_default_temperature_from_agent_config(self):
        mock_client = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.content = "OK"
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=mock_msg)]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("backend.agents._get_client", return_value=mock_client), \
             patch("backend.agents.load_agent") as mock_load:
            mock_load.return_value = {
                "name": "Test",
                "model": "glm-5.1",
                "instructions": [],
                "style": "",
                "temperature": 0.3,
            }

            await ask_agent("test", "Hi")
            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_global_client_reused(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="OK"))])
        )

        with patch("backend.agents._get_client", return_value=mock_client), \
             patch("backend.agents.load_agent") as mock_load:
            mock_load.return_value = {
                "name": "Test",
                "model": "glm-5.1",
                "instructions": [],
                "style": "",
            }
            await ask_agent("test", "Q1")
            await ask_agent("test", "Q2")
            assert mock_client.chat.completions.create.call_count == 2
