from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from tradinglab.dashboard.auth import (  # noqa: E402
    SESSION_COOKIE,
    DashboardAuth,
    validate_dashboard_token,
)

TOKEN = "example-dashboard-token-not-for-production"


class DashboardAuthTest(unittest.TestCase):
    def test_token_validation_rejects_weak_or_unsafe_values(self) -> None:
        for token in ("short", "x" * 257, "token with spaces that is long", "é" * 24):
            with self.subTest(token=token[:10]), self.assertRaises(ValueError):
                validate_dashboard_token(token)

    def test_login_cookie_expiration_and_logout(self) -> None:
        now = [1000.0]
        auth = DashboardAuth(
            TOKEN,
            session_seconds=60,
            clock=lambda: now[0],
            token_factory=lambda _: "s" * 43,
        )

        self.assertIsNone(auth.login("wrong-token-value-with-safe-length"))
        self.assertIsNone(auth.login("é" * 24))
        session = auth.login(TOKEN)
        self.assertEqual(session, "s" * 43)
        cookie = f"other=value; {SESSION_COOKIE}={session}"
        self.assertEqual(auth.authorized_session(cookie), session)

        now[0] += 61
        self.assertIsNone(auth.authorized_session(cookie))

        now[0] = 2000.0
        session = auth.login(TOKEN)
        auth.logout(session)
        self.assertIsNone(auth.authorized_session(f"{SESSION_COOKIE}={session}"))

    def test_malformed_or_ambiguous_cookie_is_not_authorized(self) -> None:
        auth = DashboardAuth(TOKEN)
        for cookie in (None, "", f"{SESSION_COOKIE}=tiny", "broken-cookie"):
            with self.subTest(cookie=cookie):
                self.assertIsNone(auth.authorized_session(cookie))


if __name__ == "__main__":
    unittest.main()
