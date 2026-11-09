from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tradinglab.telemetry.daily_account_history import (  # noqa: E402
    AccountObservation,
    consolidate_broker_day,
)

DAY = date(2026, 11, 5)


def observation(hour: int, *, balance: str = "100", equity: str = "103") -> AccountObservation:
    return AccountObservation(
        "test-account",
        datetime(2026, 11, 5, hour, tzinfo=UTC),
        datetime(2026, 11, 5, hour) + timedelta(hours=2),
        Decimal(balance),
        Decimal(equity),
        Decimal(equity) - Decimal(balance),
    )


class DailyAccountHistoryTest(unittest.TestCase):
    def consolidate(self, samples, **overrides):
        arguments = {
            "account_id": "test-account",
            "broker_day": DAY,
            "current_broker_day": date(2026, 11, 6),
        }
        arguments.update(overrides)
        return consolidate_broker_day(iter(samples), **arguments)

    def test_close_is_latest_capture_not_highest_balance_or_arrival_order(self) -> None:
        first = observation(8, balance="120", equity="130")
        last = observation(21, balance="90", equity="85")
        middle = observation(12, balance="110", equity="70")
        result = self.consolidate([last, first, middle])
        self.assertEqual(result.close, last)
        self.assertEqual(result.first_captured_at_utc, first.captured_at_utc)
        self.assertEqual((result.min_balance, result.max_balance), (Decimal(90), Decimal(120)))
        self.assertEqual((result.min_equity, result.max_equity), (Decimal(70), Decimal(130)))
        self.assertEqual(result, self.consolidate([middle, first, last, last]))

    def test_day_uses_broker_date_not_utc_and_keeps_actual_capture_time(self) -> None:
        # UTC Nov 5 at 23:00 already belongs to broker Nov 6.
        result = self.consolidate([observation(21), observation(23)])
        self.assertEqual(result.close.broker_time.hour, 23)
        self.assertEqual(result.close.captured_at_utc.hour, 21)
        self.assertIsNone(self.consolidate([observation(23)]))

    def test_no_captures_means_missing_day_not_carried_forward_or_zero(self) -> None:
        self.assertIsNone(self.consolidate([]))
        result = self.consolidate([observation(8)])
        self.assertEqual(result.close.broker_time.hour, 10)
        self.assertNotIn("realized_pnl", result.__dataclass_fields__)

    def test_current_future_and_wrong_account_are_rejected(self) -> None:
        for current in (DAY, date(2026, 11, 4)):
            with self.assertRaises(ValueError):
                self.consolidate([], current_broker_day=current)
        with self.assertRaises(ValueError):
            self.consolidate([replace(observation(8), account_id="another-account")])

    def test_ambiguous_close_fails_instead_of_choosing_arbitrarily(self) -> None:
        sample = observation(21)
        conflict = replace(sample, balance=Decimal(999))
        for rows in ([sample, conflict], [conflict, sample]):
            with self.assertRaises(ValueError):
                self.consolidate(rows)

    def test_invalid_money_and_clock_are_rejected(self) -> None:
        for value in (Decimal("NaN"), Decimal("Infinity"), 3.1, "100"):
            with self.assertRaises(ValueError):
                replace(observation(8), balance=value)
        with self.assertRaises(ValueError):
            replace(observation(8), captured_at_utc=datetime(2026, 11, 5, 8))
        with self.assertRaises(ValueError):
            replace(observation(8), broker_time=datetime(2026, 11, 5, 10, tzinfo=UTC))

    def test_late_arrival_updates_close_and_is_replay_safe(self) -> None:
        early = observation(8)
        late = observation(21, balance="99.99", equity="100.01")
        self.assertEqual(self.consolidate([early]).close, early)
        expected = self.consolidate([early, late])
        self.assertEqual(expected.close, late)
        self.assertEqual(expected, self.consolidate([late, early, late]))

    def test_only_conflict_at_latest_capture_blocks_closing(self) -> None:
        early = observation(8)
        conflict = replace(early, balance=Decimal(999))
        late = observation(21)
        self.assertEqual(
            self.consolidate([early, conflict, late]),
            self.consolidate([late, conflict, early]),
        )


if __name__ == "__main__":
    unittest.main()
