"""Remember-me cookie helpers: JWT subject parsing, session restore, cookie set/clear."""

import base64
import json
import time

from ui.cookies import (
    COOKIE_NAME,
    apply_auth_cookie,
    parse_jwt_claims,
    parse_jwt_subject,
    remove_auth_cookie,
    token_fingerprint,
)
from ui.session import REJECTED_TOKEN_KEY, restore_auth_from_cookies


def _token(subject="alice", extra=None):
    payload = {"sub": subject, **(extra or {})}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


class FakeCookies(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = 0

    def save(self):
        self.saved += 1


def test_parse_jwt_subject_valid_garbage_and_missing():
    assert parse_jwt_subject(_token("alice")) == "alice"
    assert parse_jwt_subject(_token("alice", {"tv": 1})) == "alice"
    assert parse_jwt_subject("not-a-jwt") is None
    assert parse_jwt_subject("") is None
    assert parse_jwt_subject("a.!!!.c") is None
    assert parse_jwt_subject(_token("")) is None
    assert parse_jwt_subject(_token("alice", {"sub": None})) is None


def test_restore_auth_from_cookies_populates_state():
    state = {"jwt_token": None}
    assert restore_auth_from_cookies(state, FakeCookies({COOKIE_NAME: _token("alice")})) is True
    assert state["jwt_token"] == _token("alice")
    assert state["authenticated_user"] == "alice"


def test_restore_skips_when_already_authenticated():
    state = {"jwt_token": "existing", "authenticated_user": "bob"}
    assert restore_auth_from_cookies(state, FakeCookies({COOKIE_NAME: _token("alice")})) is False
    assert state["authenticated_user"] == "bob"


def test_restore_ignores_missing_garbage_and_broken_sources():
    assert restore_auth_from_cookies({}, FakeCookies()) is False
    assert restore_auth_from_cookies({}, FakeCookies({COOKIE_NAME: "garbage"})) is False
    assert restore_auth_from_cookies({"jwt_token": None}, None) is False
    assert restore_auth_from_cookies({}, FakeCookies({COOKIE_NAME: _token("alice")})) is True


def test_apply_and_remove_auth_cookie():
    cookies = FakeCookies()
    apply_auth_cookie(cookies, _token("alice"))
    assert cookies[COOKIE_NAME] == _token("alice")
    assert cookies.saved == 1

    remove_auth_cookie(cookies)
    assert COOKIE_NAME not in cookies
    assert cookies.saved == 2

    # Removing when absent is a no-op (no pointless component write).
    remove_auth_cookie(cookies)
    assert cookies.saved == 2


def test_cookie_helpers_tolerate_none_and_empty_values():
    apply_auth_cookie(None, _token("alice"))
    remove_auth_cookie(None)
    empty = FakeCookies()
    apply_auth_cookie(empty, "")
    assert COOKIE_NAME not in empty
    assert empty.saved == 0


def test_parse_jwt_claims_reads_subject_and_expiry():
    subject, expires = parse_jwt_claims(_token("alice", {"exp": 123}))
    assert subject == "alice"
    assert expires == 123
    assert parse_jwt_claims(_token("alice")) == ("alice", None)
    assert parse_jwt_claims("not-a-jwt") == (None, None)
    assert parse_jwt_claims("") == (None, None)


def test_token_fingerprint_is_stable_short_and_distinct():
    assert token_fingerprint("abc") == token_fingerprint("abc")
    assert token_fingerprint("abc") != token_fingerprint("abd")
    assert len(token_fingerprint("abc")) == 16


def test_restore_skips_expired_tokens():
    expired = _token("alice", {"exp": int(time.time()) - 60})
    state = {"jwt_token": None}
    assert restore_auth_from_cookies(state, FakeCookies({COOKIE_NAME: expired})) is False
    assert state.get("jwt_token") is None


def test_restore_allows_future_expiry_and_missing_expiry():
    fresh = _token("alice", {"exp": int(time.time()) + 3600})
    assert restore_auth_from_cookies({"jwt_token": None}, FakeCookies({COOKIE_NAME: fresh})) is True
    assert restore_auth_from_cookies({"jwt_token": None}, FakeCookies({COOKIE_NAME: _token("alice")})) is True


def test_restore_skips_session_rejected_fingerprint():
    token = _token("alice")
    state = {"jwt_token": None, REJECTED_TOKEN_KEY: token_fingerprint(token)}
    assert restore_auth_from_cookies(state, FakeCookies({COOKIE_NAME: token})) is False
    assert state.get("jwt_token") is None


def test_rejected_fingerprint_does_not_block_other_tokens():
    state = {"jwt_token": None, REJECTED_TOKEN_KEY: token_fingerprint("some-other-token")}
    assert restore_auth_from_cookies(state, FakeCookies({COOKIE_NAME: _token("alice")})) is True
