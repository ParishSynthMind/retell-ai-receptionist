"""The four custom functions Retell calls during a call. Each returns a short sentence the agent can speak."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from .calendar.base import Booking, CalendarAdapter
from .calllog import CallLog
from .notify import Notifier
from .scheduling import Scheduler, parse_time, resolve_day, spoken


def _clean(value: Any, limit: int = 200) -> str:
    """Caller-supplied text goes into calendars and emails: strip control characters and cap the length."""
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()
    return text[:limit]


class ToolError(Exception):
    """A problem the caller should hear about in plain words (bad date, slot taken), not a crash."""


class Receptionist:
    def __init__(self, scheduler: Scheduler, calendar: CalendarAdapter, notifier: Notifier, log: CallLog,
                 business_name: str):
        self.scheduler = scheduler
        self.calendar = calendar
        self.notifier = notifier
        self.log = log
        self.business_name = business_name
        self.handlers: Dict[str, Callable[..., str]] = {
            "check_availability": self.check_availability,
            "book_appointment": self.book_appointment,
            "send_summary": self.send_summary,
            "handover": self.handover,
        }

    def _add_outcome(self, call_id: Optional[str], text: str, **fields: Any) -> None:
        """A call can book AND ask for a person; keep every outcome, not just the last one."""
        if not call_id:
            return
        before = (self.log.get(call_id) or {}).get("outcome")
        self.log.mark(call_id, outcome=f"{before}; {text}" if before else text, **fields)

    def run(self, name: str, args: Dict[str, Any], call: Dict[str, Any]) -> str:
        call_id = call.get("id")
        handler = self.handlers.get(name)
        if handler is None:
            result = f"Unknown tool {name}."
        else:
            try:
                result = handler(args, call)
            except ToolError as e:
                result = str(e)
            except Exception as e:  # never leave the caller in silence; log and say something useful
                result = ("Sorry, I couldn't reach the booking system just now. "
                          "Offer to take a message and have the team call back.")
                self.log.tool_event(call_id, name, args, f"ERROR {type(e).__name__}: {e}")
                return result
        self.log.tool_event(call_id, name, args, result)
        return result

    # check_availability --------------------------------------------------------------------------
    def check_availability(self, args: Dict[str, Any], call: Dict[str, Any]) -> str:
        now = self.scheduler.now()
        today = now.date()
        day = resolve_day(args.get("date"), today)
        if args.get("date") and day is None:
            raise ToolError(f"I couldn't work out the date '{_clean(args.get('date'), 40)}'. "
                            f"Ask the caller for a day of the week or a date. Today is {now:%A %d %B %Y}.")
        if day is not None and day < today:
            raise ToolError(f"That date has passed. Today is {now:%A %d %B %Y}.")
        if day is not None:
            slots = self.scheduler.free_slots(day, now)
            if slots:
                def times(part):
                    return ", ".join(spoken(s).split(" at ")[1] for s in part) or "none"
                morning = [s for s in slots if s.hour < 12]
                afternoon = [s for s in slots if s.hour >= 12]
                return (f"Today is {now:%A %d %B %Y}. Free 30-minute slots on {day:%A %d %B} "
                        f"(date {day.isoformat()}). Morning: {times(morning)}. Afternoon: {times(afternoon)}.")
            alt = next(self.scheduler.next_days_with_slots(day, 14, now), None)
            if alt is None:
                return f"Today is {now:%A %d %B %Y}. Nothing free on {day:%A %d %B} or in the two weeks after."
            d, s = alt
            return (f"Today is {now:%A %d %B %Y}. Nothing free on {day:%A %d %B}. The next free day is "
                    f"{d:%A %d %B} (date {d.isoformat()}): " + ", ".join(spoken(x).split(" at ")[1] for x in s[:6]) + ".")
        found = list(self.scheduler.next_days_with_slots(today, 7, now))[:3]
        if not found:
            return f"Today is {now:%A %d %B %Y}. No free slots in the next week."
        parts = [f"{d:%A %d %B} (date {d.isoformat()}): " + ", ".join(spoken(x).split(' at ')[1] for x in s[:4])
                 for d, s in found]
        return f"Today is {now:%A %d %B %Y}. Next free slots. " + "; ".join(parts) + "."

    # book_appointment ----------------------------------------------------------------------------
    def book_appointment(self, args: Dict[str, Any], call: Dict[str, Any]) -> str:
        now = self.scheduler.now()
        name = _clean(args.get("name"), 80)
        phone = _clean(args.get("phone") or (call.get("customer") or {}).get("number"), 40)
        reason = _clean(args.get("reason") or "Appointment", 120)
        day = resolve_day(args.get("date"), now.date())
        at = parse_time(str(args.get("time") or ""))
        if not name:
            raise ToolError("I need the caller's name before booking.")
        if not phone:
            raise ToolError("I need a contact phone number before booking.")
        if day is None or at is None:
            raise ToolError("I need a date and a time for the booking, as YYYY-MM-DD and HH:MM.")
        start = datetime.combine(day, at, self.scheduler.tz)
        if not self.scheduler.is_free(start, now):
            raise ToolError(f"{spoken(start)} is not available. Check availability again and offer another time.")
        booking = Booking(start=start, end=start + self.scheduler.slot, name=name, phone=phone, reason=reason,
                          call_id=call.get("id"))
        booking.event_id = self.calendar.create_event(booking)
        self._add_outcome(call.get("id"), f"Booked {spoken(start)} for {name} ({reason})")
        return (f"Booked. {name}, {reason}, {spoken(start)}. Reference {booking.event_id[:6].upper()}. "
                f"Confirm this back to the caller.")

    # send_summary --------------------------------------------------------------------------------
    def send_summary(self, args: Dict[str, Any], call: Dict[str, Any]) -> str:
        caller = _clean(args.get("caller_name") or "Unknown caller", 80)
        phone = _clean(args.get("phone") or (call.get("customer") or {}).get("number") or "not given", 40)
        summary = _clean(args.get("summary"), 1500)
        action = _clean(args.get("follow_up") or "None", 400)
        body = (f"Call summary from the {self.business_name} voice receptionist\n\n"
                f"Caller: {caller}\nPhone: {phone}\nCall id: {call.get('id') or 'n/a'}\n\n"
                f"What happened:\n{summary}\n\nFollow-up needed: {action}\n")
        self.notifier.send(f"Call summary: {caller}", body)
        if call.get("id"):
            self.log.mark(call["id"], summary=summary, summary_emailed=1)
        return "Summary sent to the team."

    # handover ------------------------------------------------------------------------------------
    def handover(self, args: Dict[str, Any], call: Dict[str, Any]) -> str:
        caller = _clean(args.get("caller_name") or "Unknown caller", 80)
        phone = _clean(args.get("callback_number") or (call.get("customer") or {}).get("number") or "not given", 40)
        reason = _clean(args.get("reason") or "Caller asked for a person", 400)
        urgent = bool(args.get("urgent"))
        body = (f"A caller asked to speak to a person.\n\nCaller: {caller}\nCall back on: {phone}\n"
                f"Urgent: {'YES' if urgent else 'no'}\nReason: {reason}\nCall id: {call.get('id') or 'n/a'}\n")
        self.notifier.send(f"{'URGENT ' if urgent else ''}Handover: call back {caller}", body)
        self._add_outcome(call.get("id"), f"Handed over: {reason}", handover=1)
        when = "within 15 minutes" if urgent else "within the hour, during opening hours"
        return (f"The team has been alerted and will call {caller} back on {phone} {when}. "
                f"Tell the caller exactly that.")
