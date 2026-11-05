"""Turning opening hours and busy times into bookable slots, and spoken dates into real dates."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .calendar.base import CalendarAdapter

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def resolve_day(text: Optional[str], today: date) -> Optional[date]:
    """Accepts YYYY-MM-DD, 'today', 'tomorrow' or a weekday name (next occurrence, today counts)."""
    if not text:
        return None
    t = text.strip().lower()
    m = re.search(r"\d{4}-\d{2}-\d{2}", t)
    if m:
        return date.fromisoformat(m.group(0))
    if "today" in t:
        return today
    if "tomorrow" in t:
        return today + timedelta(days=1)
    for i, name in enumerate(WEEKDAYS):
        if name in t:
            ahead = (i - today.weekday()) % 7
            if "next" in t and ahead == 0:
                ahead = 7
            return today + timedelta(days=ahead)
    return None


def parse_time(text: str) -> Optional[time]:
    """'14:30', '2:30pm', '2 pm', '10am' -> time."""
    t = text.strip().lower().replace(".", ":").replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", t)
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def spoken(dt: datetime) -> str:
    """Friday 7 November at 2:30pm (what a receptionist would say)."""
    hour = dt.strftime("%I").lstrip("0")
    minutes = "" if dt.minute == 0 else dt.strftime(":%M")
    return f"{dt.strftime('%A')} {dt.day} {dt.strftime('%B')} at {hour}{minutes}{dt.strftime('%p').lower()}"


class Scheduler:
    def __init__(self, calendar: CalendarAdapter, tz: str, hours: Dict[int, List[Tuple[str, str]]],
                 slot_minutes: int = 30, min_notice_minutes: int = 60):
        self.calendar = calendar
        self.tz = ZoneInfo(tz)
        self.hours = hours
        self.slot = timedelta(minutes=slot_minutes)
        self.notice = timedelta(minutes=min_notice_minutes)

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def _opening_slots(self, day: date) -> List[datetime]:
        out = []
        for open_s, close_s in self.hours.get(day.weekday(), []):
            start = datetime.combine(day, time.fromisoformat(open_s), self.tz)
            close = datetime.combine(day, time.fromisoformat(close_s), self.tz)
            while start + self.slot <= close:
                out.append(start)
                start += self.slot
        return out

    def free_slots(self, day: date, now: Optional[datetime] = None) -> List[datetime]:
        now = now or self.now()
        candidates = [s for s in self._opening_slots(day) if s >= now + self.notice]
        if not candidates:
            return []
        busy = self.calendar.busy(candidates[0], candidates[-1] + self.slot)
        return [s for s in candidates if not any(b0 < s + self.slot and b1 > s for b0, b1 in busy)]

    def next_days_with_slots(self, start_day: date, days: int = 7, now: Optional[datetime] = None):
        for offset in range(days):
            d = start_day + timedelta(days=offset)
            slots = self.free_slots(d, now)
            if slots:
                yield d, slots

    def is_free(self, start: datetime, now: Optional[datetime] = None) -> bool:
        return start in self.free_slots(start.date(), now)
