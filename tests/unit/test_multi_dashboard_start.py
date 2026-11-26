"""Account-specific poller startup coordination."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock, patch

from tradinglab.multi_dashboard import AccountViews


class DashboardStartupTest(unittest.TestCase):
    def test_slow_first_account_allows_other_account_and_shares_poller(self):
        views = AccountViews(
            "http://127.0.0.1:8782",
            {
                "CENTRAL_ACCOUNT_READ": "snapshot-" + "x" * 32,
                "CENTRAL_TRADING_READ": "history-" + "x" * 32,
            },
        )
        views.catalog = {key: {"broker_offset": 0} for key in ("alpha", "beta")}
        entered, release = Event(), Event()

        def slow_poll():
            entered.set()
            if not release.wait(5):
                raise TimeoutError("poller de prueba")

        first, second = Mock(), Mock()
        first.start.side_effect = slow_poll
        with patch("tradinglab.multi_dashboard.LiveDashboardService", side_effect=[first, second]):
            with ThreadPoolExecutor(max_workers=3) as workers:
                a = workers.submit(views.view, "alpha")
                try:
                    self.assertTrue(entered.wait(2))
                    repeated = workers.submit(views.view, "alpha")
                    b = workers.submit(views.view, "beta")
                    self.assertIs(b.result(timeout=2)[0], second)
                finally:
                    release.set()
                self.assertIs(a.result(), repeated.result())
        views.close()
        first.start.assert_called_once()
        first.stop.assert_called_once()
        second.stop.assert_called_once()
