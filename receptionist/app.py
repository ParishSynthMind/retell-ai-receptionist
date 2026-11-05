"""FastAPI service Retell talks to: custom-function calls in, short spoken results out, call events logged.

Endpoints
- POST /retell/tool/{name}   one URL per custom function (check_availability, book_appointment,
                             send_summary, handover). Body per Retell's spec: {"name", "call", "args"}
                             (or the bare args if the tool has args_at_root on).
- POST /retell/webhook       call_started / call_ended / call_analyzed. Answers 204.
- GET  /calls, /calendar.ics admin views, bearer ADMIN_TOKEN.
- GET  /health

Every Retell request must carry a valid X-Retell-Signature (HMAC of the raw body with the Retell
API key, timestamp within 5 minutes). Without RETELL_API_KEY the service refuses Retell traffic
(503) unless ALLOW_UNSIGNED=1 is set for local development.
"""
from __future__ import annotations

import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from .calendar.local import LocalCalendar
from .calllog import CallLog
from .config import Settings
from .notify import Notifier, OutboxNotifier, SmtpNotifier
from .scheduling import Scheduler
from .signature import HEADER, verify
from .tools import Receptionist, _clean

log = logging.getLogger("receptionist")


def build_receptionist(settings: Settings, calendar=None, notifier: Optional[Notifier] = None) -> Receptionist:
    if calendar is None:
        if settings.calendar_backend == "google":
            from .calendar.google import GoogleCalendar, service_account_token_provider
            info = json.loads(settings.google_service_account_json) if settings.google_service_account_json else None
            calendar = GoogleCalendar(settings.google_calendar_id,
                                      service_account_token_provider(settings.google_service_account_file, info),
                                      timezone=settings.timezone)
        else:
            calendar = LocalCalendar(settings.data_dir / "calendar.sqlite3")
    if notifier is None:
        if settings.smtp_host and settings.team_email:
            notifier = SmtpNotifier(settings.smtp_host, settings.smtp_port, settings.smtp_user,
                                    settings.smtp_password, settings.smtp_from, settings.team_email)
        else:
            notifier = OutboxNotifier(settings.data_dir / "outbox.jsonl")
    scheduler = Scheduler(calendar, settings.timezone, settings.hours, settings.slot_minutes,
                          settings.min_notice_minutes)
    return Receptionist(scheduler, calendar, notifier, CallLog(settings.data_dir / "calls.sqlite3"),
                        settings.business_name)


def call_context(call: Dict[str, Any]) -> Dict[str, Any]:
    """Retell's call object -> the small dict the tools use (id, caller number, kind)."""
    return {"id": call.get("call_id"), "type": call.get("call_type"),
            "customer": {"number": call.get("from_number")}}


def _iso(ms: Any) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _cost(call: Dict[str, Any]) -> Optional[float]:
    cost = call.get("call_cost") or {}
    value = cost.get("combined_cost")
    return float(value) / 100 if isinstance(value, (int, float)) else None  # Retell reports cents


def create_app(settings: Optional[Settings] = None, receptionist: Optional[Receptionist] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    rec = receptionist or build_receptionist(settings)
    app = FastAPI(title="Retell AI Receptionist")
    app.state.receptionist = rec

    async def signed_body(request: Request) -> Dict[str, Any]:
        raw = (await request.body()).decode("utf-8")
        if settings.retell_api_key:
            if not verify(raw, settings.retell_api_key, request.headers.get(HEADER)):
                log.warning("rejected a request with a missing, wrong or stale %s", HEADER)
                raise HTTPException(status_code=401, detail="Unauthorized")
        elif not settings.allow_unsigned:
            raise HTTPException(status_code=503, detail="RETELL_API_KEY is not set, so requests can't be verified")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="body is not JSON") from None
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="body must be a JSON object")
        return body

    def check_admin(request: Request) -> None:
        given = request.headers.get("authorization", "")
        if not settings.admin_token or not hmac.compare_digest(given, f"Bearer {settings.admin_token}"):
            raise HTTPException(status_code=401, detail="Unauthorized")

    @app.get("/health")
    def health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.post("/retell/tool/{name}")
    async def tool(name: str, request: Request) -> Dict[str, str]:
        body = await signed_body(request)
        if "args" in body or "call" in body:  # the standard wrapper: {"name", "call", "args"}
            if body.get("name") and body["name"] != name:
                raise HTTPException(status_code=400, detail="function name does not match the URL")
            args, call = body.get("args") or {}, body.get("call") or {}
        else:  # "Payload: args only"
            args, call = body, {}
        if name not in rec.handlers:
            raise HTTPException(status_code=404, detail=f"no function called {name}")
        ctx = call_context(call)
        if ctx["id"]:
            rec.log.call_seen(ctx["id"], ctx["type"], ctx["customer"]["number"])
        result = rec.run(name, args if isinstance(args, dict) else {}, ctx)
        log.info("function %s answered (%d characters)", name, len(result))  # no caller details in logs
        return {"result": result}

    @app.post("/retell/webhook", status_code=204)
    async def webhook(request: Request) -> Response:
        body = await signed_body(request)
        event, call = body.get("event"), body.get("call") or {}
        call_id = call.get("call_id")
        if not call_id or not event:
            return Response(status_code=204)
        if not rec.log.first_delivery(call_id, event):
            return Response(status_code=204)  # a Retell retry of something already handled
        ctx = call_context(call)
        rec.log.call_seen(call_id, ctx["type"], ctx["customer"]["number"])

        if event == "call_started":
            rec.log.mark(call_id, started_at=_iso(call.get("start_timestamp")))
        elif event == "call_ended":
            duration = call.get("duration_ms")
            rec.log.end_of_call(call_id, {
                "started_at": _iso(call.get("start_timestamp")),
                "ended_at": _iso(call.get("end_timestamp")),
                "ended_reason": call.get("disconnection_reason"),
                "duration_seconds": duration / 1000 if isinstance(duration, (int, float)) else None,
                "cost": _cost(call),
                "transcript": call.get("transcript"),
            })
        elif event == "call_analyzed":
            analysis = call.get("call_analysis") or {}
            rec.log.mark(call_id, analysis_summary=analysis.get("call_summary"),
                         sentiment=analysis.get("user_sentiment"))
            row = rec.log.get(call_id) or {}
            if call.get("call_status") == "error" and not call.get("transcript") and not row.get("transcript"):
                # The caller never joined (Retell: error_user_not_joined and the like). Nobody to
                # report on, so log it and send no email; the live test found these were just noise.
                rec.log.mark(call_id, outcome=row.get("outcome") or
                             f"Never connected ({call.get('disconnection_reason') or 'error'})")
            elif not row.get("summary_emailed"):
                # The agent didn't send a summary during the call (caller hung up early, or the
                # model skipped it): send Retell's own summary so no call goes unreported.
                fallback = "web call" if call.get("call_type") == "web_call" else "unknown number"
                caller = _clean(call.get("from_number") or fallback, 40)
                body_text = (f"Call summary (written by Retell after the call; the agent did not send one)\n\n"
                             f"Caller: {caller}\nCall id: {call_id}\n"
                             f"Ended: {row.get('ended_reason') or call.get('disconnection_reason') or 'unknown'}\n"
                             f"Sentiment: {analysis.get('user_sentiment') or 'n/a'}\n\n"
                             f"What happened:\n{_clean(analysis.get('call_summary') or 'No summary.', 1500)}\n\n"
                             f"Outcome logged: {row.get('outcome') or 'none'}\n")
                rec.notifier.send(f"Call summary: {caller}", body_text)
                rec.log.mark(call_id, summary_emailed=1)
        return Response(status_code=204)

    @app.get("/calls")
    def calls(request: Request, limit: int = 20):
        check_admin(request)
        return rec.log.calls(limit)

    @app.get("/calendar.ics", response_class=PlainTextResponse)
    def ics(request: Request):
        check_admin(request)
        export = getattr(rec.calendar, "export_ics", None)
        if export is None:
            raise HTTPException(status_code=404, detail="calendar backend has no .ics export")
        return PlainTextResponse(export(settings.business_name), media_type="text/calendar")

    return app
