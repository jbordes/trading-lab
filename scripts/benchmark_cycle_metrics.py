#!/usr/bin/env python3
"""Opt-in synthetic benchmark for v2 cycle-metric aggregation and pagination."""

from __future__ import annotations

import argparse
import statistics
import sys
import tracemalloc
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradinglab.dashboard.telemetry_v2 import (  # noqa: E402
    TelemetryPositionCycle,
    TelemetryPositionCyclePage,
    V2HistoryProvider,
)
from tradinglab.metrics.position_cycles import CycleLifecycle, PositionCycle  # noqa: E402
from tradinglab.metrics.workbook_v1 import StreamingWorkbookMetrics  # noqa: E402

_PAGE_SIZE = 100
_FROM_MSC = 1_700_000_000_000
_TO_MSC = _FROM_MSC + 10_000_000_000


@dataclass(frozen=True, slots=True)
class _CoverageEvidence:
    coverage: dict[str, object]


class _SyntheticHistoryClient:
    """Serve prebuilt cycles through the same page contract as the API client."""

    def __init__(self, cycles: tuple[TelemetryPositionCycle, ...]) -> None:
        self._cycles = cycles
        self.page_requests = 0

    def deal_history(self, **_: object) -> _CoverageEvidence:
        return _CoverageEvidence({"complete_ranges": [], "incomplete_batches": 0})

    def position_cycles(
        self, *, cursor: str | None = None, **_: object
    ) -> TelemetryPositionCyclePage:
        start = int(cursor.split(":")[1]) if cursor is not None else 0
        end = min(start + _PAGE_SIZE, len(self._cycles))
        self.page_requests += 1
        return TelemetryPositionCyclePage(
            "synthetic-account",
            "synthetic-source",
            None,
            self._cycles[start:end],
            (
                f"{self._cycles[end - 1].cycle.last_event_at_msc}:{end}"
                if end < len(self._cycles)
                else None
            ),
        )


def _cycles(count: int, magic_count: int) -> tuple[TelemetryPositionCycle, ...]:
    result: list[TelemetryPositionCycle] = []
    for index in range(count):
        position_id = str(index + 1)
        magic = str(index % magic_count + 1)
        cycle = PositionCycle(
            account_id="synthetic-account",
            position_id=position_id,
            owner_magic=magic,
            observed_magics=(magic,),
            started_at_msc=_FROM_MSC + index,
            last_event_at_msc=_FROM_MSC + index,
            lifecycle=CycleLifecycle.CLOSED,
            remaining_signed_volume=Decimal(0),
            observed_net_result=Decimal((index % 21) - 10) / Decimal(10),
            deal_tickets=(position_id,),
            exclusions=(),
        )
        result.append(TelemetryPositionCycle(index + 1, "synthetic", cycle))
    return tuple(result)


def _aggregate_only(cycles: tuple[TelemetryPositionCycle, ...]) -> int:
    """Time the metric accumulation without client pagination or response guards."""
    combined = StreamingWorkbookMetrics()
    by_magic: dict[str, StreamingWorkbookMetrics] = {}
    for item in cycles:
        cycle = item.cycle
        combined.add(
            cycle.observed_net_result,
            ticket=cycle.position_id,
            time_msc=cycle.last_event_at_msc,
        )
        if cycle.owner_magic is None:
            continue
        metrics = by_magic.get(cycle.owner_magic)
        if metrics is None:
            metrics = StreamingWorkbookMetrics()
            by_magic[cycle.owner_magic] = metrics
        metrics.add(
            cycle.observed_net_result,
            ticket=cycle.position_id,
            time_msc=cycle.last_event_at_msc,
        )
    combined_snapshot = combined.snapshot()
    for metrics in by_magic.values():
        metrics.snapshot()
    return combined_snapshot.trade_count


def _measure(count: int, magic_count: int, repeats: int) -> dict[str, object]:
    cycles = _cycles(count, magic_count)
    _aggregate_only(cycles)
    warm_client = _SyntheticHistoryClient(cycles)
    V2HistoryProvider(warm_client).cycle_performance_metrics(from_msc=_FROM_MSC, to_msc=_TO_MSC)
    aggregation_samples: list[float] = []
    provider_samples: list[float] = []
    page_count = 0

    for _ in range(repeats):
        started = perf_counter()
        aggregate_count = _aggregate_only(cycles)
        aggregation_samples.append(perf_counter() - started)
        if aggregate_count != count:
            raise RuntimeError("El benchmark de acumulación produjo un conteo inesperado")

        client = _SyntheticHistoryClient(cycles)
        provider = V2HistoryProvider(client)  # type: ignore[arg-type]
        started = perf_counter()
        result = provider.cycle_performance_metrics(from_msc=_FROM_MSC, to_msc=_TO_MSC).as_dict()
        provider_samples.append(perf_counter() - started)
        page_count = client.page_requests
        if result["trade_count"] != count:
            raise RuntimeError("El benchmark paginado produjo un conteo inesperado")
        if page_count != (count + _PAGE_SIZE - 1) // _PAGE_SIZE:
            raise RuntimeError("El benchmark paginado produjo una cantidad de páginas inesperada")

    client = _SyntheticHistoryClient(cycles)
    provider = V2HistoryProvider(client)  # type: ignore[arg-type]
    tracemalloc.start()
    provider.cycle_performance_metrics(from_msc=_FROM_MSC, to_msc=_TO_MSC)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "cycles": count,
        "magics": magic_count,
        "pages": page_count,
        "aggregation_median_ms": statistics.median(aggregation_samples) * 1000,
        "aggregation_min_ms": min(aggregation_samples) * 1000,
        "aggregation_max_ms": max(aggregation_samples) * 1000,
        "provider_median_ms": statistics.median(provider_samples) * 1000,
        "provider_min_ms": min(provider_samples) * 1000,
        "provider_max_ms": max(provider_samples) * 1000,
        "provider_peak_kib": peak_bytes / 1024,
    }


def _bounded_positive_int(value: str, maximum: int, label: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= maximum:
        raise argparse.ArgumentTypeError(f"{label}: debe estar entre 1 y {maximum}")
    return parsed


def _cycle_count(value: str) -> int:
    return _bounded_positive_int(value, 100_000, "cantidad de ciclos")


def _magic_count(value: str) -> int:
    return _bounded_positive_int(value, 100, "cantidad de EAs")


def _repeat_count(value: str) -> int:
    return _bounded_positive_int(value, 20, "repeticiones")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", nargs="+", type=_cycle_count, default=[1_000, 10_000, 30_000])
    parser.add_argument("--magics", nargs="+", type=_magic_count, default=[1, 5, 20])
    parser.add_argument("--repeats", type=_repeat_count, default=5)
    args = parser.parse_args(argv)

    print(f"Python {sys.version.split()[0]} | repeats={args.repeats} | synthetic data only")
    print(
        "cycles  EAs  pages  aggregate median [min-max] ms  "
        "paged provider median [min-max] ms  peak KiB"
    )
    for count in args.counts:
        for magic_count in args.magics:
            result = _measure(count, magic_count, args.repeats)
            print(
                f"{result['cycles']:>6}  {result['magics']:>3}  {result['pages']:>5}  "
                f"{result['aggregation_median_ms']:>7.2f} [{result['aggregation_min_ms']:.2f}-"
                f"{result['aggregation_max_ms']:.2f}]  "
                f"{result['provider_median_ms']:>8.2f} [{result['provider_min_ms']:.2f}-"
                f"{result['provider_max_ms']:.2f}]  "
                f"{result['provider_peak_kib']:>8.1f}"
            )
    print("Peak memory uses tracemalloc and is Python allocation data, not process RSS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
