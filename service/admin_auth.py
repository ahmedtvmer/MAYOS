"""Separate owner credentials, TOTP checks, lockouts, and browser sessions."""

import base64
import hashlib
import hmac
import os
import re
import secrets
import struct
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

import bcrypt

from service.auth import verify_password

SESSION_IDLE_SECONDS = 30 * 60
SESSION_ABSOLUTE_SECONDS = 8 * 60 * 60
LOGIN_CSRF_SECONDS = 10 * 60
IP_LOCKOUT_FAILURES = 5
IDENTITY_LOCKOUT_FAILURES = 20
LOCKOUT_WINDOW_SECONDS = 15 * 60
LOCKOUT_SECONDS = 15 * 60
TOTP_PERIOD_SECONDS = 30
TOTP_DIGITS = 6
MAX_TOKEN_LENGTH = 128
_ADMIN_SECRETS = ("ADMIN_USERNAME", "ADMIN_PASSWORD_HASH", "ADMIN_TOTP_SECRET")
_USERNAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_BCRYPT_HASH = re.compile(r"^\$2[aby]\$(?:0[4-9]|1[0-6])\$[./A-Za-z0-9]{53}$")
_BASE32_SECRET = re.compile(r"^[A-Z2-7]+={0,6}$", re.IGNORECASE)


@dataclass(frozen=True)
class AdminConfig:
    username: str | None
    password_hash: str | None
    totp_secret: bytes | None

    @property
    def enabled(self) -> bool:
        return bool(self.username and self.password_hash and self.totp_secret)

    @classmethod
    def from_environment(cls) -> "AdminConfig":
        raw = [os.getenv(name, "") for name in _ADMIN_SECRETS]
        if not all(raw) or not _valid_username(raw[0]) or not _valid_password_hash(raw[1]):
            return cls(None, None, None)
        try:
            secret = decode_totp_secret(raw[2])
        except ValueError:
            return cls(None, None, None)
        return cls(raw[0], raw[1], secret)


@dataclass(frozen=True)
class AdminSessionTokens:
    session_token: str
    csrf_token: str


@dataclass(frozen=True)
class AdminLoginAttempt:
    username: str
    password: str
    code: str
    client_ip: str


class AdminLoginResult(str, Enum):
    SUCCESS = "success"
    REJECTED = "rejected"
    LOCKED_OUT = "locked_out"
    LOCKOUT_STARTED = "lockout_started"


@dataclass
class AdminSession:
    csrf_token: str
    created_at: float
    last_activity: float


@dataclass
class _FailureState:
    failures: int
    window_started: float
    locked_until: float = 0.0


def partial_secret_configuration() -> bool:
    """True when some, but not all, owner secrets are present."""
    present = sum(bool(os.getenv(name, "").strip()) for name in _ADMIN_SECRETS)
    return 0 < present < len(_ADMIN_SECRETS)


def decode_totp_secret(value: str) -> bytes:
    """Decodes an unpadded or padded Base32 TOTP secret of at least 128 bits."""
    clean = value.strip()
    if not clean or not _BASE32_SECRET.fullmatch(clean):
        raise ValueError("TOTP secret must be Base32.")
    unpadded = clean.rstrip("=")
    secret = base64.b32decode(unpadded.upper() + "=" * (-len(unpadded) % 8))
    if len(secret) < 16:
        raise ValueError("TOTP secret must contain at least 128 bits.")
    return secret


def verify_totp_code(
    secret: bytes,
    code: str,
    timestamp: float,
    last_accepted_step: int | None = None,
) -> int | None:
    """Returns the matching fresh 30-second step, accepting one adjacent step."""
    if len(code) != TOTP_DIGITS or not code.isascii() or not code.isdigit():
        return None
    current_step = int(timestamp // TOTP_PERIOD_SECONDS)
    matches = [
        step
        for step in range(max(0, current_step - 1), current_step + 2)
        if _code_for_step(secret, step) == code and (last_accepted_step is None or step > last_accepted_step)
    ]
    return max(matches) if matches else None


class AdminSecurity:
    """Process-local auth state for one API replica."""

    def __init__(self, config: AdminConfig | None = None, clock: Callable[[], float] = time.time):
        self.config = config or AdminConfig.from_environment()
        self.clock = clock
        self._lock = threading.RLock()
        self._sessions: dict[str, AdminSession] = {}
        self._failures: dict[str, _FailureState] = {}
        self._login_csrf: dict[str, float] = {}
        self._last_accepted_totp_step: int | None = None
        self._login_alert_failed = False
        self._next_alert_sequence = 0
        self._latest_alert_sequence = 0

    @property
    def login_alert_failed(self) -> bool:
        with self._lock:
            return self._login_alert_failed

    def next_login_alert_sequence(self) -> int:
        with self._lock:
            self._next_alert_sequence += 1
            return self._next_alert_sequence

    def record_login_alert(self, sequence: int, failed: bool) -> None:
        with self._lock:
            if sequence >= self._latest_alert_sequence:
                self._latest_alert_sequence = sequence
                self._login_alert_failed = failed

    def issue_login_csrf(self) -> str:
        token = secrets.token_urlsafe(32)
        now = self.clock()
        digest = _token_digest(token)
        with self._lock:
            self._login_csrf = {key: expiry for key, expiry in self._login_csrf.items() if expiry > now}
            self._login_csrf[digest] = now + LOGIN_CSRF_SECONDS
        return token

    def consume_login_csrf(self, form_token: str, cookie_token: str) -> bool:
        if len(form_token) > MAX_TOKEN_LENGTH or len(cookie_token) > MAX_TOKEN_LENGTH:
            return False
        if not form_token or not cookie_token or not hmac.compare_digest(form_token, cookie_token):
            return False
        now = self.clock()
        with self._lock:
            expires_at = self._login_csrf.pop(_token_digest(cookie_token), None)
        return expires_at is not None and expires_at > now

    def verify_login(self, attempt: AdminLoginAttempt) -> AdminLoginResult:
        """Checks credentials outside the state lock, then atomically records the outcome."""
        if not self.config.enabled:
            return AdminLoginResult.REJECTED
        now = self.clock()
        ip_key = f"ip:{attempt.client_ip[:MAX_TOKEN_LENGTH]}"
        with self._lock:
            if self._is_locked(ip_key, now) or self._is_locked("identity", now):
                return AdminLoginResult.LOCKED_OUT
        matching_step = self._matching_totp_step(attempt, now)
        now = self.clock()
        with self._lock:
            if self._is_locked(ip_key, now) or self._is_locked("identity", now):
                return AdminLoginResult.LOCKED_OUT
            if matching_step is not None and (
                self._last_accepted_totp_step is None or matching_step > self._last_accepted_totp_step
            ):
                self._last_accepted_totp_step = matching_step
                self._failures.pop(ip_key, None)
                self._failures.pop("identity", None)
                return AdminLoginResult.SUCCESS
            ip_lock_started = self._record_failure(ip_key, now)
            identity_lock_started = self._record_failure("identity", now)
            if ip_lock_started or identity_lock_started:
                return AdminLoginResult.LOCKOUT_STARTED
            return AdminLoginResult.REJECTED

    def create_session(self) -> AdminSessionTokens:
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        now = self.clock()
        with self._lock:
            self._remove_expired_sessions(now)
            self._sessions[_token_digest(session_token)] = AdminSession(csrf_token, now, now)
        return AdminSessionTokens(session_token, csrf_token)

    def has_valid_session(self, session_token: str | None) -> bool:
        if not session_token or len(session_token) > MAX_TOKEN_LENGTH:
            return False
        with self._lock:
            return self._active_session(session_token, self.clock()) is not None

    def get_session(self, session_token: str | None) -> AdminSession | None:
        if not session_token or len(session_token) > MAX_TOKEN_LENGTH:
            return None
        with self._lock:
            now = self.clock()
            session = self._active_session(session_token, now)
            if session is not None:
                session.last_activity = now
            return session

    def validate_session_csrf(self, session_token: str | None, submitted_token: str) -> bool:
        if (
            not session_token
            or len(session_token) > MAX_TOKEN_LENGTH
            or not submitted_token
            or len(submitted_token) > MAX_TOKEN_LENGTH
        ):
            return False
        now = self.clock()
        with self._lock:
            session = self._active_session(session_token, now)
            if session is None or not hmac.compare_digest(session.csrf_token, submitted_token):
                return False
            session.last_activity = now
            return True

    def logout(self, session_token: str | None) -> None:
        if session_token:
            with self._lock:
                self._sessions.pop(_token_digest(session_token), None)

    def _matching_totp_step(self, attempt: AdminLoginAttempt, now: float) -> int | None:
        configured_username = self.config.username or ""
        configured_hash = self.config.password_hash or ""
        identity_matches = len(attempt.username) <= 64 and hmac.compare_digest(attempt.username, configured_username)
        password_matches = self._password_matches(attempt.password, configured_hash)
        step = verify_totp_code(self.config.totp_secret or b"", attempt.code, now)
        return step if identity_matches and password_matches else None

    @staticmethod
    def _password_matches(password: str, password_hash: str) -> bool:
        if len(password) > 72 or len(password.encode("utf-8")) > 72:
            verify_password("", password_hash)
            return False
        return verify_password(password, password_hash)

    def _active_session(self, session_token: str, now: float) -> AdminSession | None:
        digest = _token_digest(session_token)
        session = self._sessions.get(digest)
        if session is None:
            return None
        idle_expired = now - session.last_activity >= SESSION_IDLE_SECONDS
        absolute_expired = now - session.created_at >= SESSION_ABSOLUTE_SECONDS
        if idle_expired or absolute_expired:
            self._sessions.pop(digest, None)
            return None
        return session

    def _remove_expired_sessions(self, now: float) -> None:
        expired = [
            digest
            for digest, session in self._sessions.items()
            if now - session.last_activity >= SESSION_IDLE_SECONDS
            or now - session.created_at >= SESSION_ABSOLUTE_SECONDS
        ]
        for digest in expired:
            self._sessions.pop(digest, None)

    def _is_locked(self, key: str, now: float) -> bool:
        state = self._failures.get(key)
        if state is None:
            return False
        if state.locked_until > now:
            return True
        if state.locked_until and now >= state.locked_until:
            self._failures.pop(key, None)
            return False
        if now - state.window_started >= LOCKOUT_WINDOW_SECONDS:
            self._failures.pop(key, None)
            return False
        return False

    def _record_failure(self, key: str, now: float) -> bool:
        state = self._failures.get(key)
        if state is None or now - state.window_started >= LOCKOUT_WINDOW_SECONDS:
            state = _FailureState(0, now)
            self._failures[key] = state
        state.failures += 1
        threshold = IP_LOCKOUT_FAILURES if key.startswith("ip:") else IDENTITY_LOCKOUT_FAILURES
        if state.failures == threshold:
            state.locked_until = now + LOCKOUT_SECONDS
            return True
        return False


def _valid_username(value: str) -> bool:
    return bool(_USERNAME.fullmatch(value))


def _valid_password_hash(value: str) -> bool:
    if not _BCRYPT_HASH.fullmatch(value):
        return False
    try:
        bcrypt.checkpw(b"admin-config-validation", value.encode("ascii"))
    except (UnicodeEncodeError, ValueError):
        return False
    return True


def _code_for_step(secret: bytes, step: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{number % (10**TOTP_DIGITS):0{TOTP_DIGITS}d}"


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
