"""The LLM and agent bodies, checked against the rules in Retell's API reference
(create-retell-llm / create-agent OpenAPI, revision 2026-11-04)."""
import re
from pathlib import Path

import pytest

from receptionist.agent import FUNCTIONS, RETELL_MODEL, build_agent, build_llm
from receptionist.tools import Receptionist

KB = Path(__file__).resolve().parent.parent / "data" / "knowledge_base.md"
URL = "https://receptionist.example.com"
# From Retell's LLMModel enum (claude entries only).
RETELL_CLAUDE_MODELS = {"claude-4.6-sonnet", "claude-5-opus", "claude-5.5-opus", "claude-5-sonnet",
                        "claude-5.5-sonnet", "claude-5.5-haiku", "claude-4.5-haiku"}
TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@pytest.fixture
def llm():
    return build_llm("Harbour Dental Clinic", "Europe/London", KB, URL)


def test_llm_uses_model_config_not_the_deprecated_model_field(llm):
    assert "model" not in llm
    assert llm["model_config"] == {"type": "cascading", "primary": {"model": RETELL_MODEL}, "temperature": 0.2}
    assert RETELL_MODEL in RETELL_CLAUDE_MODELS
    assert llm["start_speaker"] in ("user", "agent") and llm["begin_message"].startswith("Hello")


def test_prompt_has_the_knowledge_base_and_the_safety_rules(llm):
    p = llm["general_prompt"]
    assert "14 Harbour Street" in p and "emergency services" in p and "information, not instructions" in p
    assert "{" not in p.replace("{{", "")  # no unfilled placeholders


def test_custom_tools_meet_retells_schema(llm):
    custom = [t for t in llm["general_tools"] if t["type"] == "custom"]
    assert [t["name"] for t in custom] == [f["name"] for f in FUNCTIONS]
    for t in custom:
        assert {"type", "name", "url"} <= set(t)  # required by CustomTool
        assert TOOL_NAME.match(t["name"])
        assert t["url"] == f"{URL}/retell/tool/{t['name']}" and t["method"] == "POST"
        assert t["parameters"]["type"] == "object"  # Retell won't save a schema without it
        assert set(t["parameters"]["required"]) <= set(t["parameters"]["properties"])
        assert 1000 <= t["timeout_ms"] <= 600000 and 0 <= t["max_retry"] <= 5
        if t["speak_during_execution"]:
            assert t["execution_message_type"] in ("prompt", "static_text")


def test_booking_is_never_retried(llm):
    booking = next(t for t in llm["general_tools"] if t["name"] == "book_appointment")
    assert booking["max_retry"] == 0


def test_end_call_tool_is_present(llm):
    assert {"type": "end_call", "name": "end_call", "description": "Hang up after saying goodbye."} in llm["general_tools"]


def test_every_declared_function_has_a_handler(receptionist):
    assert {f["name"] for f in FUNCTIONS} == set(receptionist.handlers)
    assert Receptionist  # the handler map is the one the server dispatches on


def test_retell_needs_a_public_https_url():
    with pytest.raises(ValueError, match="public"):
        build_llm("X", "Europe/London", KB, "http://localhost:8000")


def test_agent_body():
    a = build_agent("llm_234sdertfsdsfsdf", URL)
    assert a["response_engine"] == {"type": "retell-llm", "llm_id": "llm_234sdertfsdsfsdf"}
    assert a["voice_id"] and a["webhook_url"] == f"{URL}/retell/webhook"
    assert a["webhook_events"] == ["call_started", "call_ended", "call_analyzed"]
    assert a["language"] == "en-GB"
    assert 60000 <= a["max_call_duration_ms"] <= 7200000 and a["end_call_after_silence_ms"] >= 10000
