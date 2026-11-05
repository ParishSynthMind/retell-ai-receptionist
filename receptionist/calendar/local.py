from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from .base import Booking, Interval


class LocalCalendar:
    """A working calendar in a single SQLite file, with .ics export so any calendar app can subscribe."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS appointments (
                id TEXT PRIMARY KEY, start_utc TEXT NOT NULL, end_utc TEXT NOT NULL,
                name TEXT NOT NULL, phone TEXT NOT NULL, reason TEXT NOT NULL,
                call_id TEXT, created_utc TEXT NOT NULL)"""
        )
        self._db.commit()

    @staticmethod
    def _utc(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).isoformat()

    def busy(self, start: datetime, end: datetime) -> List[Interval]:
        with self._lock:
            rows = self._db.execute(
                "SELECT start_utc, end_utc FROM appointments WHERE start_utc < ? AND end_utc > ? ORDER BY start_utc",
                (self._utc(end), self._utc(start)),
            ).fetchall()
        return [(datetime.fromisoformat(s), datetime.fromisoformat(e)) for s, e in rows]

    def create_event(self, booking: Booking) -> str:
        event_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._db.execute(
                "INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?)",
                (event_id, self._utc(booking.start), self._utc(booking.end), booking.name, booking.phone,
                 booking.reason, booking.call_id, self._utc(datetime.now(timezone.utc))),
            )
            self._db.commit()
        return event_id

    def appointments(self) -> List[dict]:
        with self._lock:
            cur = self._db.execute("SELECT * FROM appointments ORDER BY start_utc")
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def export_ics(self, calendar_name: str = "Appointments") -> str:
        def stamp(iso: str) -> str:
            return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        def esc(text: str) -> str:
            return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//retell-ai-receptionist//EN",
                 "X-WR-CALNAME:" + esc(calendar_name)]
        for a in self.appointments():
            lines += [
                "BEGIN:VEVENT",
                f"UID:{a['id']}@retell-ai-receptionist",
                "DTSTAMP:" + stamp(a["created_utc"]),
                "DTSTART:" + stamp(a["start_utc"]),
                "DTEND:" + stamp(a["end_utc"]),
                "SUMMARY:" + esc(f"{a['name']}: {a['reason']}"),
                "DESCRIPTION:" + esc(f"Phone: {a['phone']}\nBooked by the voice receptionist"),
                "END:VEVENT",
            ]
        lines.append("END:VCALENDAR")
        return "\r\n".join(lines) + "\r\n"
