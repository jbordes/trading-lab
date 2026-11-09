from __future__ import annotations

import io
import unittest
import urllib.request
from decimal import Decimal
from unittest.mock import Mock, patch

from tradinglab.dashboard.snapshot import DashboardReadError
from tradinglab.dashboard.telemetry_v2 import (
    LoopbackV2HistoryClient,
    TelemetryPositionCycle,
    TelemetryPositionCyclePage,
    V2HistoryProvider,
)
from tradinglab.metrics.position_cycles import CycleLifecycle, PositionCycle


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def cycle(event: int, position: str) -> TelemetryPositionCycle:
    return TelemetryPositionCycle(
        1,
        "2026-11-05T00:00:00Z",
        PositionCycle(
            "account",
            position,
            "11122",
            ("11122",),
            0,
            event,
            CycleLifecycle.CLOSED,
            Decimal(0),
            Decimal(10),
            (position,),
            (),
        ),
    )


def page(*items: TelemetryPositionCycle, cursor: str | None = None) -> TelemetryPositionCyclePage:
    return TelemetryPositionCyclePage("account", "activity", None, items, cursor)


class CycleMetricsBudgetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.client = Mock(spec=LoopbackV2HistoryClient)
        self.client.deal_history.return_value.coverage = {"status": "complete"}
        self.provider = V2HistoryProvider(self.client, metrics_budget_seconds=1, clock=self.clock)

    def calculate(self) -> dict[str, object]:
        return self.provider.cycle_performance_metrics(from_msc=0, to_msc=100).as_dict()

    def test_valid_numeric_progress_preserves_metrics_and_passes_remaining_budget(self) -> None:
        def coverage(**_: object) -> Mock:
            self.clock.now += 0.2
            return Mock(coverage={"status": "complete"})

        pages = iter((page(cycle(1, "2"), cycle(1, "10"), cursor="1:10"), page(cycle(2, "1"))))

        def fetch(**_: object) -> TelemetryPositionCyclePage:
            self.clock.now += 0.3
            return next(pages)

        self.client.deal_history.side_effect = coverage
        self.client.position_cycles.side_effect = fetch
        result = self.calculate()
        self.assertEqual(result["trade_count"], 3)
        self.assertEqual(result["net_profit"], 30)
        self.assertEqual(result["by_ea"][0]["trade_count"], 3)
        calls = self.client.position_cycles.call_args_list
        self.assertAlmostEqual(calls[0].kwargs["timeout_seconds"], 0.8)
        self.assertAlmostEqual(calls[1].kwargs["timeout_seconds"], 0.5)

    def test_empty_final_page_is_valid(self) -> None:
        self.client.position_cycles.return_value = page()
        self.assertEqual(self.calculate()["trade_count"], 0)

    def test_alternating_pages_stop_before_a_second_lap(self) -> None:
        self.client.position_cycles.side_effect = (
            page(cycle(1, "1"), cursor="1:1"),
            page(cycle(2, "2"), cursor="2:2"),
            page(cycle(1, "1"), cursor="1:1"),
        )
        with self.assertRaisesRegex(DashboardReadError, "retrocedió"):
            self.calculate()
        self.assertEqual(self.client.position_cycles.call_count, 3)

    def test_repeated_cycle_is_rejected_even_on_final_page(self) -> None:
        self.client.position_cycles.side_effect = (
            page(cycle(1, "1"), cursor="1:1"),
            page(cycle(1, "1")),
        )
        with self.assertRaisesRegex(DashboardReadError, "repitió"):
            self.calculate()

    def test_inconsistent_cursor_and_empty_continuation_are_rejected(self) -> None:
        for invalid in (page(cycle(1, "1"), cursor="2:2"), page(cursor="1:1")):
            with self.subTest(page=invalid):
                self.client.position_cycles.return_value = invalid
                with self.assertRaisesRegex(DashboardReadError, "paginación"):
                    self.calculate()

    def test_coverage_uses_the_same_budget_and_prevents_further_reads(self) -> None:
        def coverage(**_: object) -> Mock:
            self.clock.now = 1
            return Mock(coverage={"status": "complete"})

        self.client.deal_history.side_effect = coverage
        with self.assertRaisesRegex(DashboardReadError, "agotó"):
            self.calculate()
        self.client.position_cycles.assert_not_called()
        self.assertEqual(self.client.deal_history.call_args.kwargs["timeout_seconds"], 1)

    def test_slow_final_page_never_returns_partial_metrics(self) -> None:
        def fetch(**_: object) -> TelemetryPositionCyclePage:
            self.clock.now = 1.1
            return page(cycle(1, "1"))

        self.client.position_cycles.side_effect = fetch
        with self.assertRaisesRegex(DashboardReadError, "agotó"):
            self.calculate()
        self.assertEqual(self.client.position_cycles.call_count, 1)

    def test_invalid_budgets_are_rejected(self) -> None:
        for value in (True, 0, -1, float("nan"), float("inf"), 31):
            with self.subTest(value=value), self.assertRaises(ValueError):
                V2HistoryProvider(self.client, metrics_budget_seconds=value)

    def test_budget_is_checked_while_accumulating_cycles(self) -> None:
        self.client.position_cycles.return_value = page(cycle(1, "1"), cycle(2, "2"))
        clock = Mock(side_effect=(0, 0, 0, 0, 0, 0.5, 1))
        provider = V2HistoryProvider(self.client, metrics_budget_seconds=1, clock=clock)
        with self.assertRaisesRegex(DashboardReadError, "agotó"):
            provider.cycle_performance_metrics(from_msc=0, to_msc=100)

    def test_budget_includes_final_result_preparation(self) -> None:
        self.client.position_cycles.return_value = page(cycle(1, "1"))

        def prepare(_: object) -> dict[str, object]:
            self.clock.now = 1
            return {}

        with patch("tradinglab.dashboard.telemetry_v2._streaming_metric_values", prepare):
            with self.assertRaisesRegex(DashboardReadError, "agotó"):
                self.calculate()


class HistoryReadBudgetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = LoopbackV2HistoryClient(
            read_authorization="synthetic-read-credential-safe-length",
            activity_source_id="activity",
        )
        self.client._opener = Mock()
        self.request = urllib.request.Request("http://127.0.0.1:8777/api/trading/activity")

    def test_io_timeout_is_capped_by_remaining_budget_and_body_limit(self) -> None:
        response = io.BytesIO(b"payload")
        self.client._opener.open.return_value = response
        self.assertEqual(self.client._history_body(self.request, 0.25), b"payload")
        self.client._opener.open.assert_called_once_with(self.request, timeout=0.25)
        self.assertTrue(response.closed)
        self.client._opener.open.return_value = io.BytesIO(b"12345")
        with patch("tradinglab.dashboard.telemetry_v2.MAX_BODY_BYTES", 3):
            self.assertEqual(self.client._history_body(self.request, None), b"1234")
        self.assertEqual(self.client._opener.open.call_args.kwargs["timeout"], 2)

    def test_continuous_small_chunks_do_not_reset_total_read_budget(self) -> None:
        clock = Clock()

        class SlowBody(io.BytesIO):
            def read1(self, size: int = -1) -> bytes:
                clock.now += 0.6
                return super().read1(1)

        response = SlowBody(b"payload")
        self.client._opener.open.return_value = response
        with patch("tradinglab.dashboard.telemetry_v2.monotonic", clock):
            with self.assertRaisesRegex(DashboardReadError, "agotó"):
                self.client._history_body(self.request, 1)
        self.assertTrue(response.closed)

    def test_invalid_read_budget_never_opens_a_connection(self) -> None:
        for value in (True, 0, -1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.client._history_body(self.request, value)
        self.client._opener.open.assert_not_called()

    def test_time_spent_opening_response_counts_towards_read_budget(self) -> None:
        clock = Clock()
        response = io.BytesIO(b"payload")

        def open_response(*_: object, **__: object) -> io.BytesIO:
            clock.now = 1
            return response

        self.client._opener.open.side_effect = open_response
        with patch("tradinglab.dashboard.telemetry_v2.monotonic", clock):
            with self.assertRaisesRegex(DashboardReadError, "agotó"):
                self.client._history_body(self.request, 1)
        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
