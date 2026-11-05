"""The server as Retell sees it: signed custom-function calls and signed webhooks, with payloads in the
shapes from Retell's docs ({"name", "call", "args"} and {"event", "call"})."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from receptionist.app import create_app
from receptionist.config import Settings
from receptionist.signature import HEADER, sign

KEY = "key_test_webhook_badge"
ADMIN = "admin-token"
CALL = {"call_type": "phone_call", "from_number": "+12137771234", "to_number": "+12137771235",
        "direction": "inbound", "call_id": "Jabr9TXYYJHfvl6Syypi88rdAHYHmcq6",
        "agent_id": "oBeDLoLOeuAbiuaMFXRtDOLriTJ5tSxD", "call_status": "ongoing", "start_timestamp": 1762333200000}


@pytest.fixture
def client(tmp_path, receptionist):
    app = create_app(Settings(data_dir=tmp_path, retell_api_key=KEY, admin_token=ADMIN), receptionist=receptionist)
    return TestClient(app)


def signed(client, path, payload, key=KEY, ts=None, raw=None):
    raw = raw if raw is not None else json.dumps(payload)
    headers = {"Content-Type": "application/json"}
    if key is not None:
        headers[HEADER] = sign(raw, key, ts)
    return client.post(path, content=raw, headers=headers)


def fn(client, name, args, **kw):
    return signed(client, f"/retell/tool/{name}", {"name": name, "call": CALL, "args": args}, **kw)


def admin(client, path):
    return client.get(path, headers={"Authorization": f"Bearer {ADMIN}"})


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_unsigned_wrong_key_and_replayed_requests_are_refused(client):
    assert fn(client, "check_availability", {}, key=None).status_code == 401
    assert fn(client, "check_availability", {}, key="someone-else").status_code == 401
    stale = int(time.time() * 1000) - 6 * 60 * 1000
    assert fn(client, "check_availability", {}, ts=stale).status_code == 401
    assert signed(client, "/retell/webhook", {"event": "call_started", "call": CALL}, key=None).status_code == 401


def test_without_an_api_key_the_server_refuses_retell_traffic(tmp_path, receptionist):
    c = TestClient(create_app(Settings(data_dir=tmp_path), receptionist=receptionist))
    assert fn(c, "check_availability", {}).status_code == 503
    dev = TestClient(create_app(Settings(data_dir=tmp_path, allow_unsigned=True), receptionist=receptionist))
    assert fn(dev, "check_availability", {}, key=None).status_code == 200


def test_check_availability_round_trip(client):
    r = fn(client, "check_availability", {"date": "tomorrow"})
    assert r.status_code == 200 and "2025-11-04" in r.json()["result"]


def test_every_function_over_http(client, notifier):
    book = {"name": "Sam", "phone": "1", "reason": "Clean", "date": "2025-11-04", "time": "14:00"}
    assert fn(client, "book_appointment", book).json()["result"].startswith("Booked.")
    assert fn(client, "send_summary", {"summary": "s"}).json()["result"] == "Summary sent to the team."
    assert "alerted" in fn(client, "handover", {"reason": "wants a person", "urgent": True}).json()["result"]
    assert [s for s, _ in notifier.sent][1].startswith("URGENT Handover")


def test_double_booking_is_refused_in_plain_words(client):
    book = {"name": "Sam", "phone": "1", "reason": "Clean", "date": "2025-11-04", "time": "14:00"}
    fn(client, "book_appointment", book)
    assert "is not available" in fn(client, "book_appointment", {**book, "name": "Alex"}).json()["result"]


def test_args_only_payload_is_accepted(client):
    r = signed(client, "/retell/tool/check_availability", {"date": "friday"})
    assert r.status_code == 200 and "Friday" in r.json()["result"]


def test_name_in_body_must_match_the_url_and_unknown_functions_404(client):
    r = signed(client, "/retell/tool/check_availability", {"name": "book_appointment", "call": CALL, "args": {}})
    assert r.status_code == 400
    assert fn(client, "delete_everything", {}).status_code == 404


def test_bad_json_is_a_400_not_a_crash(client):
    assert signed(client, "/retell/tool/check_availability", None, raw="{not json").status_code == 400
    assert signed(client, "/retell/tool/check_availability", None, raw="[1, 2]").status_code == 400


def test_the_model_cannot_choose_who_gets_the_email(client, notifier):
    fn(client, "send_summary", {"summary": "hi", "to": "attacker@example.com", "email": "attacker@example.com"})
    subject, body = notifier.sent[0]
    assert "attacker" not in subject + body


def test_team_email_must_be_one_address():
    with pytest.raises(ValueError):
        Settings(team_email="a@example.com, b@example.com")


def test_caller_number_comes_from_the_call_object(client, notifier):
    fn(client, "handover", {"reason": "question about invoices"})
    assert "+12137771234" in notifier.sent[0][1]


def webhook(client, event, **call_fields):
    return signed(client, "/retell/webhook", {"event": event, "call": {**CALL, **call_fields}})


def test_call_lifecycle_is_logged_and_the_summary_written(client):
    fn(client, "book_appointment", {"name": "Sam", "phone": "1", "reason": "Clean", "date": "2025-11-04",
                                    "time": "15:00"})
    assert webhook(client, "call_started").status_code == 204
    r = webhook(client, "call_ended", call_status="ended", end_timestamp=1762333354000, duration_ms=154000,
                disconnection_reason="agent_hangup", transcript="Agent: Hello\nUser: Hi",
                call_cost={"combined_cost": 31})
    assert r.status_code == 204 and r.content == b""
    webhook(client, "call_analyzed", call_analysis={"call_summary": "Booked a clean.", "user_sentiment": "Positive",
                                                    "call_successful": True, "in_voicemail": False})
    c = admin(client, "/calls").json()[0]
    assert c["call_id"] == CALL["call_id"] and c["caller"] == "+12137771234" and c["kind"] == "phone_call"
    assert c["ended_reason"] == "agent_hangup" and c["duration_seconds"] == 154 and c["cost"] == 0.31
    assert c["started_at"].startswith("2025-11-05T09:00:00") and c["transcript"].startswith("Agent: Hello")
    assert c["analysis_summary"] == "Booked a clean." and c["sentiment"] == "Positive"
    assert c["outcome"].startswith("Booked") and c["tool_events"][0]["tool"] == "book_appointment"


def test_webhook_retries_are_handled_once(client, notifier):
    for _ in range(3):
        assert webhook(client, "call_analyzed", call_analysis={"call_summary": "Asked about parking."}).status_code == 204
    assert len(notifier.sent) == 1


def test_no_summary_from_the_agent_means_retell_summary_is_emailed_once(client, notifier):
    webhook(client, "call_ended", disconnection_reason="user_hangup")
    webhook(client, "call_analyzed", call_analysis={"call_summary": "Caller hung up after asking the price.",
                                                    "user_sentiment": "Neutral"})
    assert len(notifier.sent) == 1
    subject, body = notifier.sent[0]
    assert subject == "Call summary: +12137771234" and "agent did not send one" in body
    assert "user_hangup" in body and "Caller hung up after asking the price." in body


def test_summary_already_sent_by_the_agent_is_not_sent_again(client, notifier):
    fn(client, "send_summary", {"summary": "Booked a clean."})
    webhook(client, "call_analyzed", call_analysis={"call_summary": "Booked a clean."})
    assert len(notifier.sent) == 1


def test_events_without_a_call_id_and_unknown_events_are_acknowledged(client):
    assert signed(client, "/retell/webhook", {"event": "call_started", "call": {}}).status_code == 204
    assert webhook(client, "transcript_updated").status_code == 204


def test_admin_views_need_the_token(client):
    fn(client, "book_appointment", {"name": "Sam", "phone": "1", "reason": "Clean", "date": "2025-11-04",
                                    "time": "16:00"})
    r = admin(client, "/calendar.ics")
    assert r.status_code == 200 and "SUMMARY:Sam: Clean" in r.text
    assert client.get("/calendar.ics").status_code == 401
    assert client.get("/calls", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_admin_views_are_closed_when_no_token_is_set(tmp_path, receptionist):
    c = TestClient(create_app(Settings(data_dir=tmp_path, retell_api_key=KEY), receptionist=receptionist))
    assert c.get("/calls", headers={"Authorization": "Bearer "}).status_code == 401


def test_a_call_that_books_and_asks_for_a_person_keeps_both_outcomes(client):
    fn(client, "book_appointment", {"name": "Sam", "phone": "1", "reason": "Clean", "date": "2025-11-04",
                                    "time": "11:00"})
    fn(client, "handover", {"reason": "payment plans"})
    outcome = admin(client, "/calls").json()[0]["outcome"]
    assert outcome.startswith("Booked Tuesday 4 November at 11am") and outcome.endswith("Handed over: payment plans")


def test_server_log_has_no_caller_details(client, caplog):
    caplog.set_level("INFO", logger="receptionist")
    fn(client, "handover", {"caller_name": "Sam Private", "callback_number": "+447700900999", "reason": "x"})
    assert "Sam Private" not in caplog.text and "+447700900999" not in caplog.text and "handover" in caplog.text
