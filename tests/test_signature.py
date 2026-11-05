"""X-Retell-Signature, checked against Retell's documented scheme:
v=<unix ms>,d=<hex HMAC-SHA256(key=API key, msg=raw body + timestamp)>, 5 minute window."""
import hashlib
import hmac

from receptionist.signature import TOLERANCE_MS, sign, verify

KEY = "key_test_5f1c"
BODY = '{"event":"call_started","call":{"call_id":"Jabr9TXYYJHfvl6Syypi88rdAHYHmcq6"}}'
TS = 1762333200000


def test_matches_an_independent_computation_of_the_documented_scheme():
    digest = hmac.new(KEY.encode(), (BODY + str(TS)).encode(), hashlib.sha256).hexdigest()
    assert sign(BODY, KEY, TS) == f"v={TS},d={digest}"
    assert verify(BODY, KEY, f"v={TS},d={digest}", now_ms=TS)


def test_any_change_to_the_body_or_key_fails():
    sig = sign(BODY, KEY, TS)
    assert not verify(BODY.replace("started", "ended"), KEY, sig, now_ms=TS)
    assert not verify(BODY, "another-key", sig, now_ms=TS)
    assert not verify(BODY + " ", KEY, sig, now_ms=TS)  # re-serialised JSON would fail too


def test_old_or_future_timestamps_are_refused():
    sig = sign(BODY, KEY, TS)
    assert verify(BODY, KEY, sig, now_ms=TS + TOLERANCE_MS)
    assert not verify(BODY, KEY, sig, now_ms=TS + TOLERANCE_MS + 1)
    assert not verify(BODY, KEY, sig, now_ms=TS - TOLERANCE_MS - 1)


def test_missing_or_malformed_headers_are_refused():
    for bad in (None, "", "garbage", f"v={TS}", f"d=abc,v={TS}", f"v=abc,d={'0' * 64}"):
        assert not verify(BODY, KEY, bad, now_ms=TS)
    assert not verify(BODY, "", sign(BODY, KEY, TS), now_ms=TS)


def test_timestamp_from_the_header_is_part_of_the_mac():
    sig = sign(BODY, KEY, TS)
    digest = sig.split(",d=")[1]
    assert not verify(BODY, KEY, f"v={TS + 1},d={digest}", now_ms=TS)
