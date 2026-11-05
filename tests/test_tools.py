CALL = {"id": "call-1", "type": "webCall", "customer": {"number": "+44 7700 900123"}}


def test_check_availability_for_a_named_day(receptionist):
    out = receptionist.run("check_availability", {"date": "tomorrow"}, CALL)
    assert "Tuesday 04 November" in out and "(date 2025-11-04)" in out and "9am" in out
    assert "Today is Monday 03 November 2025" in out
    # the whole day is listed, split so the caller can ask for "afternoon"
    assert "Morning: 9am, 9:30am" in out and "Afternoon: 12pm" in out and "4:30pm." in out


def test_check_availability_without_date_lists_next_days(receptionist):
    out = receptionist.run("check_availability", {}, CALL)
    assert "Next free slots" in out and "2025-11-03" in out


def test_check_availability_bad_and_past_dates(receptionist):
    assert "couldn't work out" in receptionist.run("check_availability", {"date": "the blue moon"}, CALL)
    assert "has passed" in receptionist.run("check_availability", {"date": "2025-10-01"}, CALL)


def test_check_availability_closed_day_suggests_next(receptionist):
    out = receptionist.run("check_availability", {"date": "sunday"}, CALL)
    assert "Nothing free on Sunday" in out and "Monday 10 November" in out


def test_book_appointment_writes_calendar_and_log(receptionist, calendar):
    out = receptionist.run("book_appointment", {"name": "Sam Lee", "phone": "07700 900123",
                                                "reason": "New patient check-up", "date": "2025-11-04",
                                                "time": "10:30"}, CALL)
    assert out.startswith("Booked. Sam Lee, New patient check-up, Tuesday 4 November at 10:30am")
    appts = calendar.appointments()
    assert len(appts) == 1 and appts[0]["name"] == "Sam Lee" and appts[0]["call_id"] == "call-1"
    call = receptionist.log.calls()[0]
    assert call["outcome"].startswith("Booked Tuesday 4 November at 10:30am")
    assert [e["tool"] for e in call["tool_events"]] == ["book_appointment"]


def test_double_booking_is_refused(receptionist, calendar):
    args = {"name": "A", "phone": "1", "reason": "x", "date": "2025-11-04", "time": "11:00"}
    receptionist.run("book_appointment", args, CALL)
    out = receptionist.run("book_appointment", dict(args, name="B"), CALL)
    assert "not available" in out and len(calendar.appointments()) == 1


def test_booking_outside_hours_or_missing_fields(receptionist, calendar):
    assert "not available" in receptionist.run("book_appointment", {"name": "A", "phone": "1", "reason": "x",
                                                                     "date": "2025-11-04", "time": "19:00"}, CALL)
    assert "name" in receptionist.run("book_appointment", {"phone": "1", "date": "2025-11-04", "time": "10:00"}, CALL)
    assert "date and a time" in receptionist.run("book_appointment", {"name": "A", "phone": "1"}, CALL)
    assert calendar.appointments() == []


def test_booking_falls_back_to_caller_id(receptionist, calendar):
    receptionist.run("book_appointment", {"name": "A", "reason": "x", "date": "2025-11-04", "time": "09:00"}, CALL)
    assert calendar.appointments()[0]["phone"] == "+44 7700 900123"


def test_send_summary_emails_team(receptionist, notifier):
    out = receptionist.run("send_summary", {"caller_name": "Sam Lee", "summary": "Booked a check-up.",
                                            "follow_up": "None"}, CALL)
    assert out == "Summary sent to the team."
    subject, body = notifier.sent[0]
    assert subject == "Call summary: Sam Lee" and "Booked a check-up." in body and "+44 7700 900123" in body
    assert receptionist.log.calls()[0]["summary"] == "Booked a check-up."


def test_handover_alerts_team_and_flags_call(receptionist, notifier):
    out = receptionist.run("handover", {"caller_name": "Jo", "callback_number": "07700 900555",
                                        "reason": "Toothache since last night", "urgent": True}, CALL)
    assert "within 15 minutes" in out and "07700 900555" in out
    subject, body = notifier.sent[0]
    assert subject.startswith("URGENT Handover") and "Toothache" in body
    assert receptionist.log.calls()[0]["handover"] == 1


def test_caller_text_is_sanitised(receptionist, notifier):
    receptionist.run("handover", {"caller_name": "Eve\r\nBcc: x@example.com", "reason": "r"}, CALL)
    subject, _ = notifier.sent[0]
    assert "\n" not in subject and "\r" not in subject


def test_calendar_failure_gives_spoken_fallback(receptionist):
    def boom(*a, **k):
        raise ConnectionError("down")
    receptionist.scheduler.calendar.busy = boom
    out = receptionist.run("check_availability", {"date": "tomorrow"}, CALL)
    assert "couldn't reach the booking system" in out
    assert receptionist.log.calls()[0]["tool_events"][0]["result"].startswith("ERROR ConnectionError")


def test_unknown_tool(receptionist):
    assert receptionist.run("delete_everything", {}, CALL) == "Unknown tool delete_everything."
