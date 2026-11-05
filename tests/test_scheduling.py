from datetime import date, datetime, time, timedelta

from receptionist.calendar.base import Booking
from receptionist.config import DEFAULT_HOURS
from receptionist.scheduling import Scheduler, parse_time, resolve_day, spoken

from .conftest import FIXED_NOW, TZ

MON = date(2025, 11, 3)


def test_resolve_day_variants():
    assert resolve_day("2025-11-07", MON) == date(2025, 11, 7)
    assert resolve_day("today", MON) == MON
    assert resolve_day("tomorrow", MON) == date(2025, 11, 4)
    assert resolve_day("Friday", MON) == date(2025, 11, 7)
    assert resolve_day("monday", MON) == MON
    assert resolve_day("next monday", MON) == date(2025, 11, 10)
    assert resolve_day("whenever", MON) is None
    assert resolve_day(None, MON) is None


def test_parse_time_variants():
    assert parse_time("14:30") == time(14, 30)
    assert parse_time("2:30pm") == time(14, 30)
    assert parse_time("2 pm") == time(14, 0)
    assert parse_time("12am") == time(0, 0)
    assert parse_time("10.15") == time(10, 15)
    assert parse_time("25:00") is None
    assert parse_time("soon") is None


def test_spoken_format():
    assert spoken(datetime(2025, 11, 7, 14, 30)) == "Friday 7 November at 2:30pm"
    assert spoken(datetime(2025, 11, 7, 9, 0)) == "Friday 7 November at 9am"


def make(calendar):
    return Scheduler(calendar, TZ, DEFAULT_HOURS, 30, 60)


def test_weekday_has_16_slots_and_respects_notice(calendar):
    s = make(calendar)
    slots = s.free_slots(MON, now=FIXED_NOW)
    assert len(slots) == 16 and slots[0].time() == time(9, 0) and slots[-1].time() == time(16, 30)
    later = s.free_slots(MON, now=FIXED_NOW.replace(hour=12, minute=10))
    assert later[0].time() == time(13, 30)  # 60 minutes' notice


def test_saturday_short_and_sunday_closed(calendar):
    s = make(calendar)
    assert len(s.free_slots(date(2025, 11, 8), now=FIXED_NOW)) == 8
    assert s.free_slots(date(2025, 11, 9), now=FIXED_NOW) == []


def test_busy_slots_removed(calendar):
    s = make(calendar)
    start = datetime.combine(MON, time(10, 0), s.tz)
    calendar.create_event(Booking(start, start + timedelta(minutes=60), "A", "1", "x"))
    times = [x.time() for x in s.free_slots(MON, now=FIXED_NOW)]
    assert time(10, 0) not in times and time(10, 30) not in times and time(11, 0) in times
    assert not s.is_free(start, now=FIXED_NOW)
    assert s.is_free(start + timedelta(hours=1), now=FIXED_NOW)
