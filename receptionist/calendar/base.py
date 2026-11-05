from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Protocol, Tuple

Interval = Tuple[datetime, datetime]


@dataclass
class Booking:
    start: datetime  # timezone-aware
    end: datetime
    name: str
    phone: str
    reason: str
    call_id: Optional[str] = None
    event_id: Optional[str] = None


class CalendarAdapter(Protocol):
    """Everything the receptionist needs from a calendar. Two methods, so a new backend is small."""

    def busy(self, start: datetime, end: datetime) -> List[Interval]:
        """Busy intervals that overlap [start, end), as timezone-aware datetimes."""

    def create_event(self, booking: Booking) -> str:
        """Write the booking to the calendar and return the backend's event id."""
