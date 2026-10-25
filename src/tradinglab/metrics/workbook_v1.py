"""Provisional formulas observed in the partner's operational workbook."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

FORMULA_VERSION = "partner-workbook-v1"
DEFAULT_REFERENCE_CAPITAL = Decimal("100000")
DEFAULT_RISK_AMOUNT = Decimal("200")
ROLLING_WINDOW = 20
COMMERCIAL_DEAL_TYPES = frozenset((0, 1))
CLOSING_ENTRY_TYPES = frozenset((1, 2, 3))


class DealForMetrics(Protocol):
    """Minimum validated MT5 deal shape needed by the workbook adapter."""

    ticket: str
    time_msc: int
    deal_type: int
    entry: int
    profit: float
    commission: float
    swap: float
    fee: float


@dataclass(frozen=True, slots=True)
class ClosedResult:
    """One commercial exit row, matching the workbook's current row granularity."""

    ticket: str
    time_msc: int
    net_profit: Decimal


@dataclass(frozen=True, slots=True)
class WorkbookMetricSelection:
    """Metrics plus explicit evidence of what the provisional selector ignored."""

    metrics: WorkbookMetrics
    closed_results: tuple[ClosedResult, ...]
    source_deal_count: int
    ignored_opening_deals: int
    ignored_non_trade_deals: int


@dataclass(frozen=True, slots=True)
class WorkbookMetrics:
    """One deterministic calculation, preserving the workbook's current semantics."""

    formula_version: str
    reference_capital: Decimal
    risk_amount: Decimal
    trade_count: int
    net_profit: Decimal
    profit_factor: Decimal | None
    winning_percentage: Decimal | None
    average_trade: Decimal | None
    maximum_drawdown: Decimal
    maximum_drawdown_percentage: Decimal
    current_drawdown: Decimal
    current_drawdown_percentage: Decimal
    return_drawdown_ratio: Decimal | None
    expectancy_r: Decimal | None
    standard_deviation: Decimal | None
    cumulative_profit: tuple[Decimal, ...]
    drawdown_curve: tuple[Decimal, ...]
    profit_per_trade: tuple[Decimal, ...]
    rolling_average_20: tuple[Decimal, ...]


def calculate_closed_deal_metrics(
    deals: Iterable[DealForMetrics],
    *,
    reference_capital: Decimal = DEFAULT_REFERENCE_CAPITAL,
    risk_amount: Decimal = DEFAULT_RISK_AMOUNT,
) -> WorkbookMetricSelection:
    """Select commercial exits and apply the workbook-v1 formulas.

    MT5 pending orders are not deals and therefore cannot enter this selector.
    Opening deals are retained in durable history but excluded from performance
    calculations. Partial exits remain separate results, matching the current
    workbook row granularity rather than claiming reconstructed round trips.
    """
    observed = tuple(deals)
    closed: list[ClosedResult] = []
    ignored_opening = 0
    ignored_non_trade = 0
    for deal in observed:
        if deal.deal_type not in COMMERCIAL_DEAL_TYPES:
            ignored_non_trade += 1
            continue
        if deal.entry not in CLOSING_ENTRY_TYPES:
            ignored_opening += 1
            continue
        net_profit = sum(
            (
                Decimal(str(deal.profit)),
                Decimal(str(deal.commission)),
                Decimal(str(deal.swap)),
                Decimal(str(deal.fee)),
            ),
            Decimal(0),
        )
        closed.append(ClosedResult(deal.ticket, deal.time_msc, _finite(net_profit)))
    closed.sort(key=lambda result: (result.time_msc, int(result.ticket)))
    metrics = calculate_workbook_metrics(
        tuple(result.net_profit for result in closed),
        reference_capital=reference_capital,
        risk_amount=risk_amount,
    )
    return WorkbookMetricSelection(
        metrics=metrics,
        closed_results=tuple(closed),
        source_deal_count=len(observed),
        ignored_opening_deals=ignored_opening,
        ignored_non_trade_deals=ignored_non_trade,
    )


def calculate_workbook_metrics(
    results: Sequence[Decimal],
    *,
    reference_capital: Decimal = DEFAULT_REFERENCE_CAPITAL,
    risk_amount: Decimal = DEFAULT_RISK_AMOUNT,
) -> WorkbookMetrics:
    """Calculate the mutable workbook reference as an explicit v1 formula.

    ``results`` must already contain only the ordered, net closed-position values
    selected for the metric. Selecting MT5 entities is deliberately a separate
    concern because partial closes and incomplete history need explicit treatment.
    """
    _positive_finite(reference_capital, "capital de referencia")
    _positive_finite(risk_amount, "riesgo de referencia")
    values = tuple(_finite(value) for value in results)
    count = len(values)

    cumulative: list[Decimal] = []
    drawdowns: list[Decimal] = []
    rolling: list[Decimal] = []
    running = Decimal(0)
    peak = reference_capital
    for index, value in enumerate(values):
        running += value
        cumulative.append(running)
        equity = reference_capital + running
        peak = max(peak, equity)
        drawdowns.append(peak - equity)
        window = values[max(0, index - ROLLING_WINDOW + 1) : index + 1]
        rolling.append(sum(window, Decimal(0)) / len(window))

    net_profit = cumulative[-1] if cumulative else Decimal(0)
    maximum_drawdown = max(drawdowns, default=Decimal(0))
    current_peak = max((reference_capital + value for value in cumulative), default=peak)
    current_peak = max(reference_capital, current_peak)
    current_equity = reference_capital + net_profit
    current_drawdown = current_peak - current_equity
    average = net_profit / count if count else None
    positive = sum((value for value in values if value > 0), Decimal(0))
    negative = sum((value for value in values if value < 0), Decimal(0))

    return WorkbookMetrics(
        formula_version=FORMULA_VERSION,
        reference_capital=reference_capital,
        risk_amount=risk_amount,
        trade_count=count,
        net_profit=net_profit,
        profit_factor=positive / abs(negative) if negative else None,
        winning_percentage=(Decimal(sum(value > 0 for value in values)) / count if count else None),
        average_trade=average,
        maximum_drawdown=maximum_drawdown,
        maximum_drawdown_percentage=maximum_drawdown / reference_capital,
        current_drawdown=current_drawdown,
        current_drawdown_percentage=current_drawdown / current_peak,
        return_drawdown_ratio=(net_profit / maximum_drawdown if maximum_drawdown else None),
        expectancy_r=average / risk_amount if average is not None else None,
        standard_deviation=_sample_standard_deviation(values, average),
        cumulative_profit=tuple(cumulative),
        drawdown_curve=tuple(drawdowns),
        profit_per_trade=values,
        rolling_average_20=tuple(rolling),
    )


def _sample_standard_deviation(
    values: tuple[Decimal, ...], average: Decimal | None
) -> Decimal | None:
    if len(values) < 2 or average is None:
        return None
    variance = sum(((value - average) ** 2 for value in values), Decimal(0)) / (len(values) - 1)
    return variance.sqrt()


def _finite(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("Los resultados deben ser Decimal finitos")
    return value


def _positive_finite(value: Decimal, label: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError(f"El {label} debe ser Decimal, finito y positivo")
