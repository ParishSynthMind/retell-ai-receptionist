import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from receptionist.calendar.base import Booking
from receptionist.calendar.google import GoogleCalendar

START = datetime(2025, 11, 4, 9, 0, tzinfo=timezone.utc)


def test_local_calendar_roundtrip_and_ics(calendar):
    eid = calendar.create_event(Booking(START, START + timedelta(minutes=30), "Sam Lee", "+44 7700 900000",
                                        "Check-up, new patient"))
    assert calendar.busy(START - timedelta(hours=1), START + timedelta(hours=1)) == [
        (START, START + timedelta(minutes=30))]
    assert calendar.busy(START + timedelta(minutes=30), START + timedelta(hours=1)) == []
    ics = calendar.export_ics("Clinic")
    assert "BEGIN:VEVENT" in ics and f"UID:{eid}@" in ics
    assert "DTSTART:20251104T090000Z" in ics
    assert "SUMMARY:Sam Lee: Check-up\\, new patient" in ics
    assert ics.endswith("END:VCALENDAR\r\n")


def mock_google(handler):
    return GoogleCalendar("team@example.com", lambda: "test-token",
                          client=httpx.Client(transport=httpx.MockTransport(handler)), timezone="Europe/London")


def test_google_busy_parses_freebusy():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        assert request.url.path == "/calendar/v3/freeBusy"
        return httpx.Response(200, json={"calendars": {"team@example.com": {"busy": [
            {"start": "2025-11-04T09:00:00Z", "end": "2025-11-04T09:30:00Z"}]}}})

    busy = mock_google(handler).busy(START, START + timedelta(hours=8))
    assert busy == [(START, START + timedelta(minutes=30))]
    assert seen["auth"] == "Bearer test-token"
    assert seen["body"]["items"] == [{"id": "team@example.com"}]


def test_google_busy_raises_on_calendar_error():
    def handler(request):
        return httpx.Response(200, json={"calendars": {"team@example.com": {"errors": [{"reason": "notFound"}]}}})

    with pytest.raises(RuntimeError):
        mock_google(handler).busy(START, START + timedelta(hours=1))


def test_google_create_event_posts_event():
    def handler(request):
        assert request.url.raw_path.decode() == "/calendar/v3/calendars/team%40example.com/events"
        body = json.loads(request.content)
        assert body["summary"] == "Sam Lee: Hygienist"
        assert body["start"]["timeZone"] == "Europe/London"
        return httpx.Response(200, json={"id": "evt123"})

    eid = mock_google(handler).create_event(
        Booking(START, START + timedelta(minutes=30), "Sam Lee", "+44 7700 900000", "Hygienist"))
    assert eid == "evt123"


def test_google_http_error_propagates():
    with pytest.raises(httpx.HTTPStatusError):
        mock_google(lambda r: httpx.Response(403, json={})).busy(START, START + timedelta(hours=1))
