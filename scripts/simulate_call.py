"""Play one phone call against a running server the way Retell would, with real signatures.

  RETELL_API_KEY=local-test-key uvicorn receptionist.main:app --port 8000      (in one terminal)
  RETELL_API_KEY=local-test-key python scripts/simulate_call.py                 (in another)

Sends, in order: call_started, check_availability, book_appointment, handover, send_summary,
call_ended (twice, as Retell does when a reply is slow), call_analyzed, then a forged request that
must be refused. Request shapes follow Retell's docs: {"name", "call", "args"} for functions and
{"event", "call"} for webhooks, each signed in X-Retell-Signature.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from receptionist.signature import HEADER, sign  # noqa: E402

CALL = {"call_type": "phone_call", "from_number": "+447700900123", "to_number": "+442071234567",
        "direction": "inbound", "call_id": "sim_call_0001", "agent_id": "sim_agent", "call_status": "ongoing"}


def send(client: httpx.Client, key: str, path: str, payload: dict, forged: bool = False) -> httpx.Response:
    raw = json.dumps(payload)
    sig = sign(raw, "not-the-key" if forged else key)
    return client.post(path, content=raw, headers={"Content-Type": "application/json", HEADER: sig})


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--server", default="http://localhost:8000")
    a = p.parse_args()
    key = os.environ.get("RETELL_API_KEY")
    if not key:
        raise SystemExit("set RETELL_API_KEY to the same value the server uses")
    day = date.today() + timedelta(days=1)
    while day.weekday() >= 5:  # a weekday, so the clinic is open all day
        day += timedelta(days=1)
    now_ms = int(time.time() * 1000)
    steps = [
        ("webhook", {"event": "call_started", "call": {**CALL, "start_timestamp": now_ms}}),
        ("tool", ("check_availability", {"date": day.isoformat()})),
        ("tool", ("book_appointment", {"name": "Sam Taylor", "phone": "+447700900123", "reason": "New patient check-up",
                                       "date": day.isoformat(), "time": "10:30"})),
        ("tool", ("book_appointment", {"name": "Alex Moore", "phone": "+447700900456", "reason": "Hygienist clean",
                                       "date": day.isoformat(), "time": "10:30"})),
        ("tool", ("handover", {"caller_name": "Sam Taylor", "callback_number": "+447700900123",
                               "reason": "Asked about payment plans", "urgent": False})),
        ("tool", ("send_summary", {"caller_name": "Sam Taylor", "phone": "+447700900123",
                                   "summary": "New patient booked a check-up. Asked about payment plans.",
                                   "follow_up": "Call back about payment plans"})),
        ("webhook", {"event": "call_ended", "call": {**CALL, "call_status": "ended", "start_timestamp": now_ms,
                                                     "end_timestamp": now_ms + 154000, "duration_ms": 154000,
                                                     "disconnection_reason": "agent_hangup",
                                                     "transcript": "Agent: Hello...\nUser: Hi, I'd like to book...",
                                                     "call_cost": {"combined_cost": 31}}}),
        ("webhook-retry", {"event": "call_ended", "call": {**CALL, "call_status": "ended"}}),
        ("webhook", {"event": "call_analyzed", "call": {**CALL, "call_status": "ended", "call_analysis": {
            "call_summary": "The caller booked a new patient check-up and asked about payment plans.",
            "user_sentiment": "Positive", "call_successful": True, "in_voicemail": False}}}),
    ]
    with httpx.Client(base_url=a.server, timeout=20) as c:
        for kind, item in steps:
            if kind.startswith("webhook"):
                r = send(c, key, "/retell/webhook", item)
                print(f"webhook {item['event']:<14}{' (retry)' if kind == 'webhook-retry' else '':<8} -> HTTP {r.status_code}")
            else:
                name, args = item
                r = send(c, key, f"/retell/tool/{name}", {"name": name, "call": CALL, "args": args})
                print(f"function {name:<19} -> HTTP {r.status_code}: {r.json().get('result', r.text)}")
        r = send(c, key, "/retell/tool/book_appointment",
                 {"name": "book_appointment", "call": CALL, "args": {"name": "Mallory"}}, forged=True)
        print(f"forged signature                  -> HTTP {r.status_code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
