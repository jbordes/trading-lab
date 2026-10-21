"""In-memory authentication for the local dashboard boundary."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections.abc import Callable
from hmac import compare_digest
from http.cookies import CookieError, SimpleCookie

DASHBOARD_TOKEN_ENV = "TRADINGLAB_DASHBOARD_TOKEN"
SESSION_COOKIE = "tradinglab_session"
MIN_TOKEN_LENGTH = 24
MAX_TOKEN_LENGTH = 256
DEFAULT_SESSION_SECONDS = 12 * 60 * 60
MAX_SESSIONS = 32


def validate_dashboard_token(token: str) -> None:
    """Reject weak or unsafe operator credentials before opening the server."""
    if not MIN_TOKEN_LENGTH <= len(token) <= MAX_TOKEN_LENGTH:
        raise ValueError(
            f"El token del dashboard debe tener entre {MIN_TOKEN_LENGTH} y "
            f"{MAX_TOKEN_LENGTH} caracteres"
        )
    if not token.isascii() or any(not 33 <= ord(char) <= 126 for char in token):
        raise ValueError("El token del dashboard debe ser ASCII y no contener espacios")


class DashboardAuth:
    """Validate one operator token and manage bounded, ephemeral browser sessions."""

    def __init__(
        self,
        token: str,
        *,
        session_seconds: int = DEFAULT_SESSION_SECONDS,
        clock: Callable[[], float] = time.time,
        token_factory: Callable[[int], str] = secrets.token_urlsafe,
    ) -> None:
        validate_dashboard_token(token)
        if not 60 <= session_seconds <= DEFAULT_SESSION_SECONDS:
            raise ValueError("La sesión debe durar entre 60 segundos y 12 horas")
        self._token = token
        self._session_seconds = session_seconds
        self._clock = clock
        self._token_factory = token_factory
        self._sessions: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def session_seconds(self) -> int:
        return self._session_seconds

    def login(self, candidate: str) -> str | None:
        """Return a new opaque session only when the operator token matches."""
        if not MIN_TOKEN_LENGTH <= len(candidate) <= MAX_TOKEN_LENGTH or not candidate.isascii():
            return None
        if not compare_digest(candidate, self._token):
            return None
        session = self._token_factory(32)
        digest = self._digest(session)
        now = self._clock()
        with self._lock:
            self._prune(now)
            if len(self._sessions) >= MAX_SESSIONS:
                oldest = min(self._sessions, key=self._sessions.__getitem__)
                del self._sessions[oldest]
            self._sessions[digest] = now + self._session_seconds
        return session

    def authorized_session(self, cookie_header: str | None) -> str | None:
        """Return the presented session when it exists and has not expired."""
        session = self._session_from_cookie(cookie_header)
        if session is None:
            return None
        now = self._clock()
        digest = self._digest(session)
        with self._lock:
            self._prune(now)
            expires_at = self._sessions.get(digest)
            if expires_at is None or expires_at <= now:
                return None
        return session

    def logout(self, session: str | None) -> None:
        """Revoke one browser session without affecting telemetry credentials."""
        if session is None:
            return
        with self._lock:
            self._sessions.pop(self._digest(session), None)

    def _prune(self, now: float) -> None:
        expired = [digest for digest, expires_at in self._sessions.items() if expires_at <= now]
        for digest in expired:
            del self._sessions[digest]

    @staticmethod
    def _digest(session: str) -> str:
        return hashlib.sha256(session.encode("ascii")).hexdigest()

    @staticmethod
    def _session_from_cookie(cookie_header: str | None) -> str | None:
        if not cookie_header or len(cookie_header) > 4096:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except CookieError:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        if morsel is None:
            return None
        value = morsel.value
        if not value.isascii() or not 32 <= len(value) <= 128:
            return None
        return value
