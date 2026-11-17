"""AI disclosure (EU AI Act Art. 50): the caller hears it first, once per call, and again on handover."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from receptionist.agent import build_llm
from receptionist.app import build_receptionist, create_app
from receptionist.config import Settings
from receptionist.disclosure import DEFAULT_HANDOVER
from receptionist.signature import HEADER, sign

KB = Path(__file__).resolve().parent.parent / "data" / "knowledge_base.md"
URL = "https://receptionist.example.com"
CALL = {"id": "call-1", "customer": {"number": "+44 7700 900123"}}


def _llm(settings):
    return build_llm(settings.business_name, "Europe/London", KB, URL, disclosure=settings.disclosure)


def test_begin_message_discloses_ai_by_default():
    llm = _llm(Settings(business_name="Harbour Dental Clinic"))
    assert llm["start_speaker"] == "agent"
    assert llm["begin_message"] == "Hi, this is Cimo, an AI assistant for Harbour Dental Clinic. How can I help today?"
    assert "You are an AI assistant, not a person" in llm["general_prompt"]


def test_custom_disclosure_text_and_name():
    s = Settings(business_name="Bay Vets", agent_name="Ava",
                 ai_disclosure="Hello, I'm {name}, the AI assistant at {business}.")
    assert _llm(s)["begin_message"].startswith("Hello, I'm Ava, the AI assistant at Bay Vets.")


def test_blank_disclosure_without_written_request_falls_back(monkeypatch):
    monkeypatch.setenv("AI_DISCLOSURE", "")
    monkeypatch.delenv("AI_DISCLOSURE_REMOVED_BY_WRITTEN_REQUEST", raising=False)
    s = Settings.from_env()
    assert "an AI assistant for" in _llm(s)["begin_message"]
    assert s.handover_notice == DEFAULT_HANDOVER


def test_removed_only_with_recorded_written_request(monkeypatch):
    monkeypatch.setenv("AI_DISCLOSURE", "")
    monkeypatch.setenv("AI_DISCLOSURE_REMOVED_BY_WRITTEN_REQUEST", "2026-11-17 email from J. Client")
    s = Settings.from_env()
    assert "AI assistant" not in _llm(s)["begin_message"]
    assert s.handover_notice == ""


def test_create_agent_dry_run_sends_the_disclosure(capsys, monkeypatch):
    import scripts.create_agent as ca
    monkeypatch.delenv("AI_DISCLOSURE", raising=False)
    monkeypatch.delenv("AI_DISCLOSURE_REMOVED_BY_WRITTEN_REQUEST", raising=False)
    assert ca.main(["--server-url", URL, "--dry-run"]) == 0
    assert "an AI assistant for" in capsys.readouterr().out


def test_disclosure_not_repeated_in_ordinary_function_results(receptionist):
    assert "AI assistant" not in receptionist.run("check_availability", {"date": "tomorrow"}, CALL)


def test_handover_tells_the_caller_an_ai_is_passing_them_to_a_person(receptionist):
    out = receptionist.run("handover", {"caller_name": "Jo", "reason": "wants a person"}, CALL)
    assert out.startswith(DEFAULT_HANDOVER)
    again = receptionist.run("handover", {"reason": "b"}, {"id": "call-2"})
    assert again.startswith(DEFAULT_HANDOVER)


def test_handover_over_the_signed_retell_endpoint(tmp_path):
    key = "key_test"
    s = Settings(data_dir=tmp_path, retell_api_key=key)
    client = TestClient(create_app(s))
    raw = json.dumps({"name": "handover", "call": {"call_id": "c-9", "call_type": "web_call"},
                      "args": {"reason": "wants a person"}})
    r = client.post("/retell/tool/handover", content=raw,
                    headers={"Content-Type": "application/json", HEADER: sign(raw, key)})
    assert r.status_code == 200 and r.json()["result"].startswith(DEFAULT_HANDOVER)


def test_service_respects_a_recorded_removal(tmp_path):
    r = build_receptionist(Settings(data_dir=tmp_path, ai_disclosure_removed_by_written_request="2026-11-17 ref"))
    assert r.handover_notice == ""
    assert build_receptionist(Settings(data_dir=tmp_path)).handover_notice == DEFAULT_HANDOVER
