from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from receptionist.calendar.local import LocalCalendar
from receptionist.calllog import CallLog
from receptionist.config import DEFAULT_HOURS
from receptionist.scheduling import Scheduler
from receptionist.tools import Receptionist

TZ = "Europe/London"
# Monday 3 November 2025, 08:00 local: the whole working day is still ahead.
FIXED_NOW = datetime(2025, 11, 3, 8, 0, tzinfo=ZoneInfo(TZ))


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, subject, body):
        self.sent.append((subject, body))


@pytest.fixture
def notifier():
    return FakeNotifier()


@pytest.fixture
def calendar(tmp_path: Path):
    return LocalCalendar(tmp_path / "cal.sqlite3")


@pytest.fixture
def receptionist(tmp_path, calendar, notifier):
    sched = Scheduler(calendar, TZ, DEFAULT_HOURS, 30, 60)
    sched.now = lambda: FIXED_NOW
    return Receptionist(sched, calendar, notifier, CallLog(tmp_path / "calls.sqlite3"), "Test Clinic")
