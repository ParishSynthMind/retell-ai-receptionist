"""Retell's REST API, mocked at the HTTP layer with the paths, status codes and bodies from its
API reference (201 on create, 204 on delete, {"status": "error", "message": ...} on errors)."""
import json
import sys
from pathlib import Path

import httpx
import pytest

from receptionist.retell_api import BASE, RetellAPI, RetellError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import create_agent  # noqa: E402

KEY = "key_test_not_a_real_key"


class FakeRetell:
    def __init__(self):
        self.llms, self.agents, self.requests = {}, {}, []
        self.rate_limited = 0
        self.fail = None  # (status, message) for the next create

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["authorization"] == f"Bearer {KEY}"
        if self.rate_limited:
            self.rate_limited -= 1
            return httpx.Response(429, json={"status": "error",
                                             "message": "Account rate limited, please throttle your requests."})
        if self.fail and request.method == "POST":
            status, message = self.fail
            self.fail = None
            return httpx.Response(status, json={"status": "error", "message": message})
        path, body = request.url.path, json.loads(request.content) if request.content else None
        if path == "/create-retell-llm":
            llm = {**body, "llm_id": f"llm_{len(self.llms) + 1:04d}", "version": 0, "is_published": False,
                   "last_modification_timestamp": 1762333200000}
            self.llms[llm["llm_id"]] = llm
            return httpx.Response(201, json=llm)
        if path == "/create-agent":
            assert body["response_engine"]["llm_id"] in self.llms
            agent = {**body, "agent_id": f"agent_{len(self.agents) + 1:04d}", "version": 0,
                     "last_modification_timestamp": 1762333200000}
            self.agents[agent["agent_id"]] = agent
            return httpx.Response(201, json=agent)
        kind, _, ident = path.strip("/").partition("/")
        store = self.llms if "retell-llm" in kind else self.agents
        if ident not in store:
            return httpx.Response(422, json={"status": "error", "message": "Item not found"})
        if kind.startswith("update"):
            store[ident].update(body)
            store[ident]["version"] += 1
            return httpx.Response(200, json=store[ident])
        if kind.startswith("delete"):
            del store[ident]
            return httpx.Response(204)
        return httpx.Response(404)


@pytest.fixture
def fake():
    return FakeRetell()


def api_for(fake, **kw):
    client = httpx.Client(base_url=BASE, transport=httpx.MockTransport(fake.handler))
    return RetellAPI(KEY, client=client, sleep=lambda s: None, **kw)


def test_create_llm_and_agent(fake):
    api = api_for(fake)
    llm = api.create_llm({"start_speaker": "agent", "general_prompt": "hi"})
    agent = api.create_agent({"response_engine": {"type": "retell-llm", "llm_id": llm["llm_id"]},
                              "voice_id": "retell-Cimo"})
    assert llm["llm_id"] == "llm_0001" and agent["agent_id"] == "agent_0001"
    assert str(fake.requests[0].url) == "https://api.retellai.com/create-retell-llm"


def test_errors_show_retells_message_but_never_the_key(fake):
    fake.fail = (400, "Invalid request format, please check API reference.")
    with pytest.raises(RetellError) as exc:
        api_for(fake).create_llm({})
    assert "HTTP 400: Invalid request format" in str(exc.value) and KEY not in str(exc.value)


def test_429_is_retried_then_succeeds(fake):
    fake.rate_limited = 2
    assert api_for(fake).create_llm({"general_prompt": "x"})["llm_id"]
    assert len(fake.requests) == 3


def test_429_that_never_clears_is_reported(fake):
    fake.rate_limited = 10
    with pytest.raises(RetellError, match="429: Account rate limited"):
        api_for(fake, retries_429=2).create_llm({})


def test_delete_returns_nothing_on_204(fake):
    api = api_for(fake)
    llm = api.create_llm({})
    assert api.delete_llm(llm["llm_id"]) is None and fake.llms == {}
    with pytest.raises(RetellError, match="422"):
        api.delete_llm(llm["llm_id"])


def test_script_dry_run_needs_no_key(capsys, monkeypatch):
    monkeypatch.delenv("RETELL_API_KEY", raising=False)
    assert create_agent.main(["--server-url", "https://r.example.com", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "POST /create-retell-llm" in out and '"url": "https://r.example.com/retell/tool/book_appointment"' in out


def test_script_creates_updates_and_deletes(fake, tmp_path, capsys):
    ids = tmp_path / "ids.json"
    api = api_for(fake)
    assert create_agent.main(["--server-url", "https://r.example.com", "--ids-file", str(ids)], api=api) == 0
    saved = json.loads(ids.read_text())
    agent = fake.agents[saved["agent_id"]]
    assert agent["webhook_url"] == "https://r.example.com/retell/webhook"
    assert agent["response_engine"]["llm_id"] == saved["llm_id"]
    assert fake.llms[saved["llm_id"]]["model_config"]["primary"]["model"] == "claude-5.5-sonnet"

    assert create_agent.main(["--server-url", "https://new.example.com", "--ids-file", str(ids), "--update"],
                             api=api) == 0
    assert fake.agents[saved["agent_id"]]["webhook_url"] == "https://new.example.com/retell/webhook"
    assert fake.llms[saved["llm_id"]]["version"] == 1

    assert create_agent.main(["--delete", "--ids-file", str(ids)], api=api) == 0
    assert fake.llms == {} and fake.agents == {} and not ids.exists()


def test_script_reports_a_failed_create(fake, tmp_path, capsys):
    fake.fail = (401, "API key is missing or invalid.")
    code = create_agent.main(["--server-url", "https://r.example.com", "--ids-file", str(tmp_path / "i.json")],
                             api=api_for(fake))
    assert code == 1 and "API key is missing or invalid." in capsys.readouterr().err
