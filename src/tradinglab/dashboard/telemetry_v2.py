"""Validated dashboard adapter for durable telemetry v2 activity."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from tradinglab.dashboard.snapshot import DashboardReadError
from tradinglab.dashboard.telemetry import (
    TelemetryDeal,
    TelemetryDealPage,
    TelemetryPerformance,
    _RejectRedirects,
    _telemetry_deal,
)
from tradinglab.metrics import calculate_closed_deal_metrics
from tradinglab.metrics.position_cycles import CycleExclusion, CycleLifecycle, PositionCycle
from tradinglab.metrics.workbook_v1 import calculate_workbook_metrics
from tradinglab.telemetry.contract import (
    IDENTIFIER,
    MAX_BODY_BYTES,
    MAX_INT64,
    MAX_UINT64,
    UTC_TIMESTAMP,
)

TELEMETRY_READ_TOKEN_ENV = "TRADINGLAB_TELEMETRY_READ_TOKEN"
_RESPONSE_FIELDS = {
    "account_id",
    "entity_type",
    "from_msc",
    "to_msc",
    "magic_number",
    "items",
    "next_cursor",
    "coverage",
}
_ITEM_FIELDS = {
    "message_id",
    "ticket",
    "values",
    "observed_at",
    "received_at",
    "source_id",
    "session_id",
    "sequence",
    "conflict_at",
}
_CYCLE_RESPONSE_FIELDS = {"account_id", "owner_magic", "items", "next_cursor"}
_CYCLE_ITEM_FIELDS = {"message_id", "source_id", "captured_at", "cycle", "details"}
_CYCLE_FIELDS = {
    "account_id",
    "position_id",
    "owner_magic",
    "observed_magics",
    "started_at_msc",
    "last_event_at_msc",
    "lifecycle",
    "remaining_signed_volume",
    "observed_net_result",
    "deal_tickets",
    "exclusions",
    "eligible_for_autonomous_metrics",
}


@dataclass(frozen=True, slots=True)
class V2Coverage:
    complete_ranges: tuple[tuple[str, str], ...]
    incomplete_batches: int

    def as_dict(self) -> dict[str, object]:
        return {
            "complete_ranges": [
                {"from_msc": start, "to_msc": end} for start, end in self.complete_ranges
            ],
            "incomplete_batches": self.incomplete_batches,
        }


@dataclass(frozen=True, slots=True)
class TelemetryPositionCycle:
    message_id: int
    captured_at: str
    cycle: PositionCycle
    details: dict[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "message_id": self.message_id,
            "captured_at": self.captured_at,
            "details": self.details,
            "cycle": {
                "account_id": self.cycle.account_id,
                "position_id": self.cycle.position_id,
                "owner_magic": self.cycle.owner_magic,
                "observed_magics": self.cycle.observed_magics,
                "started_at_msc": self.cycle.started_at_msc,
                "last_event_at_msc": self.cycle.last_event_at_msc,
                "lifecycle": self.cycle.lifecycle.value,
                "remaining_signed_volume": str(self.cycle.remaining_signed_volume),
                "observed_net_result": str(self.cycle.observed_net_result),
                "deal_tickets": self.cycle.deal_tickets,
                "exclusions": tuple(reason.value for reason in self.cycle.exclusions),
                "eligible_for_autonomous_metrics": (self.cycle.eligible_for_autonomous_metrics),
            },
        }


@dataclass(frozen=True, slots=True)
class TelemetryPositionCyclePage:
    account_id: str
    source_id: str
    owner_magic: str | None
    cycles: tuple[TelemetryPositionCycle, ...]
    next_cursor: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "source_id": self.source_id,
            "owner_magic": self.owner_magic,
            "cycles": [cycle.as_dict() for cycle in self.cycles],
            "next_cursor": self.next_cursor,
        }


@dataclass(frozen=True, slots=True)
class TelemetryCyclePerformance:
    """Metrics calculated only from complete, attributable position cycles."""

    account_id: str
    source_id: str
    from_msc: int
    to_msc: int
    owner_magic: str | None
    cycles: tuple[TelemetryPositionCycle, ...]
    coverage: dict[str, object]

    def as_dict(self, *, selected_magics: tuple[str, ...] = ()) -> dict[str, object]:
        available_magics = sorted(
            {item.cycle.owner_magic for item in self.cycles if item.cycle.owner_magic is not None}
        )
        ordered = tuple(
            sorted(
                (
                    item
                    for item in self.cycles
                    if item.cycle.eligible_for_autonomous_metrics
                    and item.cycle.lifecycle is CycleLifecycle.CLOSED
                    and (not selected_magics or item.cycle.owner_magic in selected_magics)
                ),
                key=lambda item: item.cycle.last_event_at_msc,
            )
        )
        metrics = calculate_workbook_metrics(
            tuple(item.cycle.observed_net_result for item in ordered)
        )
        return {
            "account_id": self.account_id,
            "source_id": self.source_id,
            "from_msc": self.from_msc,
            "to_msc": self.to_msc,
            "magic_number": self.owner_magic,
            "formula_version": "position-cycle-v1",
            "coverage": self.coverage,
            "reference_capital": float(metrics.reference_capital),
            "risk_amount": float(metrics.risk_amount),
            "trade_count": metrics.trade_count,
            "net_profit": float(metrics.net_profit),
            "profit_factor": _optional_decimal(metrics.profit_factor),
            "winning_percentage": _optional_decimal(metrics.winning_percentage),
            "average_trade": _optional_decimal(metrics.average_trade),
            "maximum_drawdown": float(metrics.maximum_drawdown),
            "maximum_drawdown_percentage": float(metrics.maximum_drawdown_percentage),
            "current_drawdown": float(metrics.current_drawdown),
            "current_drawdown_percentage": float(metrics.current_drawdown_percentage),
            "return_drawdown_ratio": _optional_decimal(metrics.return_drawdown_ratio),
            "expectancy_r": _optional_decimal(metrics.expectancy_r),
            "standard_deviation": _optional_decimal(metrics.standard_deviation),
            "by_ea": _compare_eas(ordered),
            "available_magics": available_magics,
            "selected_magics": list(selected_magics),
            "series": [
                {
                    "ticket": item.cycle.position_id,
                    "time_msc": item.cycle.last_event_at_msc,
                    "net_profit": float(item.cycle.observed_net_result),
                    "cumulative_profit": float(metrics.cumulative_profit[index]),
                    "drawdown": float(metrics.drawdown_curve[index]),
                    "rolling_average_20": float(metrics.rolling_average_20[index]),
                }
                for index, item in enumerate(ordered)
            ],
        }


def _compare_eas(cycles: tuple[TelemetryPositionCycle, ...]) -> list[dict[str, object]]:
    """Reuse the approved formulas independently for each account and owner Magic."""
    groups: dict[tuple[str, str], list[TelemetryPositionCycle]] = {}
    for item in cycles:
        magic = item.cycle.owner_magic
        if magic is not None:
            groups.setdefault((item.cycle.account_id, magic), []).append(item)
    result: list[dict[str, object]] = []
    for (account, magic), items in sorted(groups.items()):
        metrics = calculate_workbook_metrics(
            tuple(item.cycle.observed_net_result for item in items)
        )
        result.append(
            {
                "account_id": account,
                "magic_number": magic,
                "trade_count": metrics.trade_count,
                "net_profit": float(metrics.net_profit),
                "profit_factor": _optional_decimal(metrics.profit_factor),
                "winning_percentage": _optional_decimal(metrics.winning_percentage),
                "maximum_drawdown": float(metrics.maximum_drawdown),
                "maximum_drawdown_percentage": float(metrics.maximum_drawdown_percentage),
                "current_drawdown": float(metrics.current_drawdown),
                "current_drawdown_percentage": float(metrics.current_drawdown_percentage),
                "return_drawdown_ratio": _optional_decimal(metrics.return_drawdown_ratio),
                "expectancy_r": _optional_decimal(metrics.expectancy_r),
                "standard_deviation": _optional_decimal(metrics.standard_deviation),
                "average_trade": _optional_decimal(metrics.average_trade),
                "series": [
                    {
                        "time_msc": item.cycle.last_event_at_msc,
                        "cumulative_profit": float(metrics.cumulative_profit[index]),
                        "net_profit": float(item.cycle.observed_net_result),
                        "drawdown": float(metrics.drawdown_curve[index]),
                        "rolling_average_20": float(metrics.rolling_average_20[index]),
                    }
                    for index, item in enumerate(items)
                ],
            }
        )
    return result


def _optional_decimal(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


@dataclass(frozen=True, slots=True)
class TelemetryHistoricalOrder:
    account_id: str
    source_id: str
    message_id: int
    captured_at: str
    ticket: str
    magic_number: str
    symbol: str
    order_type: int
    state: int
    volume_initial: float
    volume_current: float
    price_open: float
    stop_loss: float
    take_profit: float
    setup_time_msc: int
    done_time_msc: int
    position_id: str
    position_by_id: str
    comment: str

    def as_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class TelemetryHistoricalOrderPage:
    account_id: str
    source_id: str
    from_msc: int
    to_msc: int
    magic_number: str | None
    orders: tuple[TelemetryHistoricalOrder, ...]
    next_cursor: str | None
    coverage: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "source_id": self.source_id,
            "from_msc": self.from_msc,
            "to_msc": self.to_msc,
            "magic_number": self.magic_number,
            "orders": [order.as_dict() for order in self.orders],
            "next_cursor": self.next_cursor,
            "coverage": self.coverage,
        }


class LoopbackV2HistoryClient:
    """Read recovered deals through the authenticated loopback v2 API."""

    def __init__(
        self,
        *,
        read_authorization: str,
        activity_source_id: str,
        port: int = 8777,
        timeout_seconds: float = 2.0,
    ) -> None:
        if (
            not 24 <= len(read_authorization) <= 256
            or not read_authorization.isascii()
            or any(not 33 <= ord(character) <= 126 for character in read_authorization)
        ):
            raise ValueError("La credencial de lectura v2 no cumple el formato requerido")
        if not IDENTIFIER.fullmatch(activity_source_id):
            raise ValueError("activity_source_id inválido")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("Puerto v2 fuera de rango")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0.05 <= timeout_seconds <= 30
        ):
            raise ValueError("Timeout v2 fuera de rango")
        self._activity_url = f"http://127.0.0.1:{port}/v2/activity"
        self._cycles_url = f"http://127.0.0.1:{port}/v2/position-cycles"
        self._cycle_magics_url = f"http://127.0.0.1:{port}/v2/position-cycle-magics"
        self._authorization = f"Bearer {read_authorization}"
        self._source_id = activity_source_id
        self._timeout = float(timeout_seconds)
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _RejectRedirects(),
        )

    def deal_history(
        self,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> TelemetryDealPage:
        parameters: dict[str, str | int] = {
            "entity": "deal",
            "from_msc": from_msc,
            "to_msc": to_msc,
            "limit": limit,
        }
        if magic_number is not None:
            parameters["magic_number"] = magic_number
        if cursor is not None:
            parameters["cursor"] = cursor
        request = urllib.request.Request(
            f"{self._activity_url}?{urllib.parse.urlencode(parameters)}",
            headers={"Authorization": self._authorization, "Accept": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body = response.read(MAX_BODY_BYTES + 1)
        except urllib.error.HTTPError as exc:
            exc.close()
            if 300 <= exc.code < 400:
                raise DashboardReadError("El receptor v2 intentó una redirección") from exc
            if exc.code == 401:
                raise DashboardReadError("El receptor v2 rechazó la lectura") from exc
            if exc.code == 400:
                raise ValueError("Consulta histórica v2 inválida") from exc
            raise DashboardReadError(f"El receptor v2 respondió HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DashboardReadError("No se pudo leer el historial v2 local") from exc
        if len(body) > MAX_BODY_BYTES:
            raise DashboardReadError("La respuesta histórica v2 supera el límite")
        try:
            payload = json.loads(body)
            return self._deal_page(
                payload,
                from_msc=from_msc,
                to_msc=to_msc,
                magic_number=magic_number,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DashboardReadError("El receptor devolvió actividad v2 inválida") from exc

    def order_history(
        self,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> TelemetryHistoricalOrderPage:
        parameters: dict[str, str | int] = {
            "entity": "order",
            "from_msc": from_msc,
            "to_msc": to_msc,
            "limit": limit,
        }
        if magic_number is not None:
            parameters["magic_number"] = magic_number
        if cursor is not None:
            parameters["cursor"] = cursor
        request = urllib.request.Request(
            f"{self._activity_url}?{urllib.parse.urlencode(parameters)}",
            headers={"Authorization": self._authorization, "Accept": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body = response.read(MAX_BODY_BYTES + 1)
        except urllib.error.HTTPError as exc:
            exc.close()
            if 300 <= exc.code < 400:
                raise DashboardReadError("El receptor v2 intentó una redirección") from exc
            if exc.code == 401:
                raise DashboardReadError("El receptor v2 rechazó la lectura") from exc
            if exc.code == 400:
                raise ValueError("Consulta de órdenes v2 inválida") from exc
            raise DashboardReadError(f"El receptor v2 respondió HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DashboardReadError("No se pudieron leer las órdenes v2 locales") from exc
        if len(body) > MAX_BODY_BYTES:
            raise DashboardReadError("La respuesta de órdenes v2 supera el límite")
        try:
            return self._order_page(
                json.loads(body),
                from_msc=from_msc,
                to_msc=to_msc,
                magic_number=magic_number,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DashboardReadError("El receptor devolvió órdenes v2 inválidas") from exc

    def position_cycles(
        self,
        *,
        owner_magic: str | None = None,
        owner_magics: tuple[str, ...] = (),
        from_msc: int | None = None,
        to_msc: int | None = None,
        closed_only: bool = False,
        limit: int = 50,
        cursor: str | None = None,
    ) -> TelemetryPositionCyclePage:
        parameters: dict[str, str | int] = {"limit": limit}
        if owner_magic is not None:
            parameters["owner_magic"] = owner_magic
        if owner_magics:
            parameters["owner_magics"] = ",".join(owner_magics)
        if (from_msc is None) != (to_msc is None):
            raise ValueError("El período de ciclos debe estar completo")
        if from_msc is not None and to_msc is not None:
            parameters["from_msc"] = from_msc
            parameters["to_msc"] = to_msc
        if closed_only:
            parameters["closed_only"] = "true"
        if cursor is not None:
            parameters["cursor"] = cursor
        request = urllib.request.Request(
            f"{self._cycles_url}?{urllib.parse.urlencode(parameters)}",
            headers={"Authorization": self._authorization, "Accept": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body = response.read(MAX_BODY_BYTES + 1)
        except urllib.error.HTTPError as exc:
            exc.close()
            if 300 <= exc.code < 400:
                raise DashboardReadError("El receptor v2 intentó una redirección") from exc
            if exc.code == 401:
                raise DashboardReadError("El receptor v2 rechazó la lectura") from exc
            if exc.code == 400:
                raise ValueError("Consulta de ciclos v2 inválida") from exc
            raise DashboardReadError(f"El receptor v2 respondió HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DashboardReadError("No se pudieron leer los ciclos v2 locales") from exc
        if len(body) > MAX_BODY_BYTES:
            raise DashboardReadError("La respuesta de ciclos v2 supera el límite")
        try:
            return self._position_cycle_page(
                json.loads(body),
                owner_magic=owner_magic,
                owner_magics=owner_magics,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DashboardReadError("El receptor devolvió ciclos v2 inválidos") from exc

    def position_cycle_magics(self) -> tuple[str, ...]:
        request = urllib.request.Request(
            self._cycle_magics_url,
            headers={"Authorization": self._authorization, "Accept": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body = response.read(MAX_BODY_BYTES + 1)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            raise DashboardReadError("No se pudo descubrir los Magic Numbers") from exc
        if len(body) > MAX_BODY_BYTES:
            raise DashboardReadError("La lista de Magic Numbers supera el límite")
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict) or set(payload) != {"magics"}:
                raise ValueError("Respuesta inválida")
            magics = payload["magics"]
            if (
                not isinstance(magics, list)
                or len(magics) > 100
                or any(not isinstance(item, str) for item in magics)
            ):
                raise ValueError("Magic Numbers inválidos")
            validated = tuple(self._magic_text(item, allow_none=False) for item in magics)
            if len(set(validated)) != len(validated):
                raise ValueError("Magic Numbers duplicados")
            return validated
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise DashboardReadError("El receptor devolvió Magic Numbers inválidos") from exc

    def _deal_page(
        self,
        payload: object,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None,
    ) -> TelemetryDealPage:
        if not isinstance(payload, dict) or set(payload) != _RESPONSE_FIELDS:
            raise ValueError("Respuesta v2 inválida")
        account_id = payload["account_id"]
        if not isinstance(account_id, str) or not IDENTIFIER.fullmatch(account_id):
            raise ValueError("Cuenta v2 inválida")
        if (
            payload["entity_type"] != "deal"
            or payload["from_msc"] != from_msc
            or payload["to_msc"] != to_msc
            or payload["magic_number"] != magic_number
        ):
            raise ValueError("Filtros v2 inesperados")
        items = payload["items"]
        if not isinstance(items, list) or len(items) > 100:
            raise ValueError("Cantidad v2 inválida")
        deals = tuple(self._deal(item, account_id) for item in items)
        for previous, current in zip(deals, deals[1:], strict=False):
            if (previous.time_msc, int(previous.ticket)) <= (current.time_msc, int(current.ticket)):
                raise ValueError("Orden v2 inválido")
        coverage = self._coverage(payload["coverage"], from_msc, to_msc)
        next_cursor = payload["next_cursor"]
        if next_cursor is not None:
            event_msc, ticket = self._cursor(next_cursor)
            if not deals or (event_msc, ticket) != (deals[-1].time_msc, deals[-1].ticket):
                raise ValueError("Cursor v2 inconsistente")
        return TelemetryDealPage(
            account_id=account_id,
            source_id=self._source_id,
            from_msc=from_msc,
            to_msc=to_msc,
            magic_number=magic_number,
            deals=deals,
            next_cursor=next_cursor,
            coverage=coverage.as_dict(),
        )

    def _deal(self, item: object, account_id: str) -> TelemetryDeal:
        if not isinstance(item, dict) or set(item) != _ITEM_FIELDS:
            raise ValueError("Observación v2 inválida")
        if item["source_id"] != self._source_id:
            raise ValueError("Fuente v2 inesperada")
        if (
            not isinstance(item["session_id"], str)
            or not IDENTIFIER.fullmatch(item["session_id"])
            or isinstance(item["sequence"], bool)
            or not isinstance(item["sequence"], int)
            or not 1 <= item["sequence"] <= MAX_INT64
            or not isinstance(item["received_at"], str)
            or not UTC_TIMESTAMP.fullmatch(item["received_at"])
            or (
                item["conflict_at"] is not None
                and (
                    not isinstance(item["conflict_at"], str)
                    or not UTC_TIMESTAMP.fullmatch(item["conflict_at"])
                )
            )
        ):
            raise ValueError("Procedencia v2 inválida")
        values = item["values"]
        if not isinstance(values, dict) or values.get("ticket") != item["ticket"]:
            raise ValueError("Deal v2 inconsistente")
        time_msc = values.get("time_msc")
        if (
            not isinstance(time_msc, str)
            or not time_msc.isascii()
            or not time_msc.isdecimal()
            or str(int(time_msc)) != time_msc
        ):
            raise ValueError("Hora de deal v2 inválida")
        row = (
            {
                "account_id": account_id,
                "source_id": item["source_id"],
                "message_id": item["message_id"],
                "captured_at": item["observed_at"],
            }
            | values
            | {"time_msc": int(time_msc)}
        )
        return _telemetry_deal(row, account_id=account_id)

    def _order_page(
        self,
        payload: object,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None,
    ) -> TelemetryHistoricalOrderPage:
        if not isinstance(payload, dict) or set(payload) != _RESPONSE_FIELDS:
            raise ValueError("Respuesta de órdenes v2 inválida")
        account_id = payload["account_id"]
        if not isinstance(account_id, str) or not IDENTIFIER.fullmatch(account_id):
            raise ValueError("Cuenta de órdenes v2 inválida")
        if (
            payload["entity_type"] != "order"
            or payload["from_msc"] != from_msc
            or payload["to_msc"] != to_msc
            or payload["magic_number"] != magic_number
        ):
            raise ValueError("Filtros de órdenes v2 inesperados")
        items = payload["items"]
        if not isinstance(items, list) or len(items) > 100:
            raise ValueError("Cantidad de órdenes v2 inválida")
        orders = tuple(self._historical_order(item, account_id) for item in items)
        for previous, current in zip(orders, orders[1:], strict=False):
            left = (previous.done_time_msc, int(previous.ticket))
            right = (current.done_time_msc, int(current.ticket))
            if left <= right:
                raise ValueError("Orden de órdenes v2 inválido")
        coverage = self._coverage(payload["coverage"], from_msc, to_msc)
        next_cursor = payload["next_cursor"]
        if next_cursor is not None:
            event_msc, ticket = self._cursor(next_cursor)
            if not orders or (event_msc, ticket) != (
                orders[-1].done_time_msc,
                orders[-1].ticket,
            ):
                raise ValueError("Cursor de órdenes v2 inconsistente")
        return TelemetryHistoricalOrderPage(
            account_id=account_id,
            source_id=self._source_id,
            from_msc=from_msc,
            to_msc=to_msc,
            magic_number=magic_number,
            orders=orders,
            next_cursor=next_cursor,
            coverage=coverage.as_dict(),
        )

    def _historical_order(self, item: object, account_id: str) -> TelemetryHistoricalOrder:
        if not isinstance(item, dict) or set(item) != _ITEM_FIELDS:
            raise ValueError("Observación de orden v2 inválida")
        if (
            item["source_id"] != self._source_id
            or isinstance(item["message_id"], bool)
            or not isinstance(item["message_id"], int)
            or item["message_id"] < 1
            or not isinstance(item["observed_at"], str)
            or not UTC_TIMESTAMP.fullmatch(item["observed_at"])
            or not isinstance(item["received_at"], str)
            or not UTC_TIMESTAMP.fullmatch(item["received_at"])
            or not isinstance(item["session_id"], str)
            or not IDENTIFIER.fullmatch(item["session_id"])
            or isinstance(item["sequence"], bool)
            or not isinstance(item["sequence"], int)
            or not 1 <= item["sequence"] <= MAX_INT64
            or (
                item["conflict_at"] is not None
                and (
                    not isinstance(item["conflict_at"], str)
                    or not UTC_TIMESTAMP.fullmatch(item["conflict_at"])
                )
            )
        ):
            raise ValueError("Procedencia de orden v2 inválida")
        values = item["values"]
        if not isinstance(values, dict) or set(values) != {
            "ticket",
            "magic_number",
            "symbol",
            "order_type",
            "state",
            "volume_initial",
            "volume_current",
            "price_open",
            "stop_loss",
            "take_profit",
            "setup_time_msc",
            "done_time_msc",
            "position_id",
            "position_by_id",
            "comment",
        }:
            raise ValueError("Campos de orden v2 inválidos")
        ticket = self._unsigned_text(values["ticket"], allow_zero=False)
        if ticket != item["ticket"]:
            raise ValueError("Ticket de orden v2 inconsistente")
        magic = self._magic_text(values["magic_number"], allow_none=False)
        assert magic is not None
        symbol = self._bounded_text(values["symbol"], 128, allow_empty=False)
        comment = self._bounded_text(values["comment"], 256, allow_empty=True)
        order_type = self._bounded_integer(values["order_type"], 0, 8)
        state = self._bounded_integer(values["state"], 0, 9)
        volume_initial = self._finite_number(values["volume_initial"])
        volume_current = self._finite_number(values["volume_current"])
        if not 0 <= volume_current <= volume_initial:
            raise ValueError("Volúmenes de orden v2 inconsistentes")
        setup = int(self._unsigned_text(values["setup_time_msc"], allow_zero=True))
        done = int(self._unsigned_text(values["done_time_msc"], allow_zero=True))
        if setup > done:
            raise ValueError("Tiempos de orden v2 inconsistentes")
        return TelemetryHistoricalOrder(
            account_id=account_id,
            source_id=self._source_id,
            message_id=item["message_id"],
            captured_at=item["observed_at"],
            ticket=ticket,
            magic_number=magic,
            symbol=symbol,
            order_type=order_type,
            state=state,
            volume_initial=volume_initial,
            volume_current=volume_current,
            price_open=self._finite_number(values["price_open"]),
            stop_loss=self._finite_number(values["stop_loss"]),
            take_profit=self._finite_number(values["take_profit"]),
            setup_time_msc=setup,
            done_time_msc=done,
            position_id=self._unsigned_text(values["position_id"], allow_zero=True),
            position_by_id=self._unsigned_text(values["position_by_id"], allow_zero=True),
            comment=comment,
        )

    def _position_cycle_page(
        self,
        payload: object,
        *,
        owner_magic: str | None,
        owner_magics: tuple[str, ...] = (),
    ) -> TelemetryPositionCyclePage:
        if not isinstance(payload, dict) or set(payload) != _CYCLE_RESPONSE_FIELDS:
            raise ValueError("Respuesta de ciclos v2 inválida")
        account_id = payload["account_id"]
        if not isinstance(account_id, str) or not IDENTIFIER.fullmatch(account_id):
            raise ValueError("Cuenta de ciclos v2 inválida")
        if payload["owner_magic"] != owner_magic:
            raise ValueError("Filtro de ciclos v2 inesperado")
        items = payload["items"]
        if not isinstance(items, list) or len(items) > 500:
            raise ValueError("Cantidad de ciclos v2 inválida")
        cycles = tuple(self._position_cycle(item, account_id) for item in items)
        for previous, current in zip(cycles, cycles[1:], strict=False):
            left = (previous.cycle.last_event_at_msc, int(previous.cycle.position_id))
            right = (current.cycle.last_event_at_msc, int(current.cycle.position_id))
            if left <= right:
                raise ValueError("Orden de ciclos v2 inválido")
        if owner_magic is not None and any(
            item.cycle.owner_magic != owner_magic for item in cycles
        ):
            raise ValueError("Magic propietario de ciclos v2 inesperado")
        if owner_magics and any(item.cycle.owner_magic not in owner_magics for item in cycles):
            raise ValueError("Magic propietario de ciclos v2 inesperado")
        next_cursor = payload["next_cursor"]
        if next_cursor is not None:
            event_msc, position_id = self._cursor(next_cursor)
            if not cycles or (event_msc, position_id) != (
                cycles[-1].cycle.last_event_at_msc,
                cycles[-1].cycle.position_id,
            ):
                raise ValueError("Cursor de ciclos v2 inconsistente")
        return TelemetryPositionCyclePage(
            account_id,
            self._source_id,
            owner_magic,
            cycles,
            next_cursor,
        )

    def _position_cycle(self, item: object, account_id: str) -> TelemetryPositionCycle:
        if not isinstance(item, dict) or set(item) != _CYCLE_ITEM_FIELDS:
            raise ValueError("Observación de ciclo v2 inválida")
        if (
            isinstance(item["message_id"], bool)
            or not isinstance(item["message_id"], int)
            or item["message_id"] < 1
            or item["source_id"] != self._source_id
            or not isinstance(item["captured_at"], str)
            or not UTC_TIMESTAMP.fullmatch(item["captured_at"])
        ):
            raise ValueError("Procedencia de ciclo v2 inválida")
        value = item["cycle"]
        if not isinstance(value, dict) or set(value) != _CYCLE_FIELDS:
            raise ValueError("Ciclo v2 inválido")
        position_id = self._unsigned_text(value["position_id"], allow_zero=False)
        owner_magic = self._magic_text(value["owner_magic"], allow_none=True)
        observed = value["observed_magics"]
        if not isinstance(observed, list):
            raise ValueError("Magic observados v2 inválidos")
        observed_magics = tuple(self._magic_text(magic, allow_none=False) for magic in observed)
        if (
            len(set(observed_magics)) != len(observed_magics)
            or tuple(sorted(observed_magics, key=int)) != observed_magics
        ):
            raise ValueError("Magic observados v2 inválidos")
        if owner_magic is not None and owner_magic not in observed_magics:
            raise ValueError("Magic propietario v2 inconsistente")
        started = value["started_at_msc"]
        last = value["last_event_at_msc"]
        if (
            isinstance(started, bool)
            or not isinstance(started, int)
            or isinstance(last, bool)
            or not isinstance(last, int)
            or not 0 <= started <= last <= MAX_INT64
        ):
            raise ValueError("Tiempos de ciclo v2 inválidos")
        remaining = self._decimal_text(value["remaining_signed_volume"])
        result = self._decimal_text(value["observed_net_result"])
        tickets = value["deal_tickets"]
        if not isinstance(tickets, list):
            raise ValueError("Tickets de ciclo v2 inválidos")
        deal_tickets = tuple(self._unsigned_text(ticket, allow_zero=False) for ticket in tickets)
        if not deal_tickets or len(set(deal_tickets)) != len(deal_tickets):
            raise ValueError("Tickets de ciclo v2 inválidos")
        raw_exclusions = value["exclusions"]
        if not isinstance(raw_exclusions, list):
            raise ValueError("Exclusiones de ciclo v2 inválidas")
        exclusions = tuple(CycleExclusion(reason) for reason in raw_exclusions)
        if len(set(exclusions)) != len(exclusions):
            raise ValueError("Exclusiones de ciclo v2 duplicadas")
        eligible = value["eligible_for_autonomous_metrics"]
        if not isinstance(eligible, bool) or eligible != (not exclusions):
            raise ValueError("Elegibilidad de ciclo v2 inconsistente")
        if value["account_id"] != account_id:
            raise ValueError("Cuenta de ciclo v2 inconsistente")
        cycle = PositionCycle(
            account_id=account_id,
            position_id=position_id,
            owner_magic=owner_magic,
            observed_magics=observed_magics,
            started_at_msc=started,
            last_event_at_msc=last,
            lifecycle=CycleLifecycle(value["lifecycle"]),
            remaining_signed_volume=remaining,
            observed_net_result=result,
            deal_tickets=deal_tickets,
            exclusions=exclusions,
        )
        if eligible and (
            cycle.lifecycle is not CycleLifecycle.CLOSED
            or cycle.remaining_signed_volume != 0
            or cycle.owner_magic is None
            or set(cycle.observed_magics) != {cycle.owner_magic}
        ):
            raise ValueError("Ciclo elegible v2 inconsistente")
        details = self._trade_details(item["details"])
        return TelemetryPositionCycle(item["message_id"], item["captured_at"], cycle, details)

    def _trade_details(self, value: object) -> dict[str, object]:
        numeric = {
            "volume",
            "open_price",
            "close_price",
            "gross_profit",
            "swap",
            "commission",
            "fee",
            "take_profit",
            "stop_loss",
            "pips",
            "duration_hours",
        }
        if not isinstance(value, dict) or set(value) != numeric | {
            "side",
            "symbol",
            "opening_tickets",
            "levels_basis",
        }:
            raise ValueError("Detalle de operación inválido")
        if value["side"] not in (None, "long", "short") or value["levels_basis"] not in (
            "exit_order",
            "initial_order",
            "unknown",
        ):
            raise ValueError("Dirección o procedencia de niveles inválida")
        if value["symbol"] is not None:
            self._bounded_text(value["symbol"], 128, allow_empty=False)
        tickets = value["opening_tickets"]
        if not isinstance(tickets, list) or len(tickets) > 500:
            raise ValueError("Tickets de apertura inválidos")
        for ticket in tickets:
            self._unsigned_text(ticket, allow_zero=False)
        for name in numeric:
            if value[name] is not None:
                self._finite_number(value[name])
        return value

    @staticmethod
    def _unsigned_text(value: object, *, allow_zero: bool) -> str:
        if (
            not isinstance(value, str)
            or not value.isascii()
            or not value.isdecimal()
            or str(int(value)) != value
            or int(value) > MAX_UINT64
            or (not allow_zero and int(value) == 0)
        ):
            raise ValueError("Identificador v2 inválido")
        return value

    @staticmethod
    def _magic_text(value: object, *, allow_none: bool) -> str | None:
        if value is None and allow_none:
            return None
        if not isinstance(value, str) or not value.isascii():
            raise ValueError("Magic v2 inválido")
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError("Magic v2 inválido") from exc
        if not -(2**63) <= parsed <= MAX_INT64 or str(parsed) != value:
            raise ValueError("Magic v2 inválido")
        return value

    @staticmethod
    def _decimal_text(value: object) -> Decimal:
        if not isinstance(value, str):
            raise ValueError("Decimal v2 inválido")
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("Decimal v2 inválido") from exc
        if not result.is_finite() or str(result) != value:
            raise ValueError("Decimal v2 inválido")
        return result

    @staticmethod
    def _bounded_integer(value: object, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError("Entero de orden v2 inválido")
        return value

    @staticmethod
    def _finite_number(value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Número de orden v2 inválido")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Número de orden v2 inválido")
        return result

    @staticmethod
    def _bounded_text(value: object, maximum: int, *, allow_empty: bool) -> str:
        if (
            not isinstance(value, str)
            or len(value) > maximum
            or (not allow_empty and not value)
            or any(not character.isprintable() for character in value)
        ):
            raise ValueError("Texto de orden v2 inválido")
        return value

    @staticmethod
    def _coverage(payload: object, from_msc: int, to_msc: int) -> V2Coverage:
        if not isinstance(payload, dict) or set(payload) != {
            "complete_ranges",
            "incomplete_batches",
        }:
            raise ValueError("Cobertura v2 inválida")
        incomplete = payload["incomplete_batches"]
        if isinstance(incomplete, bool) or not isinstance(incomplete, int) or incomplete < 0:
            raise ValueError("Cobertura v2 inválida")
        raw_ranges = payload["complete_ranges"]
        if not isinstance(raw_ranges, list):
            raise ValueError("Cobertura v2 inválida")
        ranges: list[tuple[str, str]] = []
        previous_end = -1
        for item in raw_ranges:
            if not isinstance(item, dict) or set(item) != {"from_msc", "to_msc"}:
                raise ValueError("Cobertura v2 inválida")
            start, end = item["from_msc"], item["to_msc"]
            if (
                not isinstance(start, str)
                or not isinstance(end, str)
                or not start.isascii()
                or not end.isascii()
                or not start.isdecimal()
                or not end.isdecimal()
            ):
                raise ValueError("Cobertura v2 inválida")
            start_value, end_value = int(start), int(end)
            if (
                str(start_value) != start
                or str(end_value) != end
                or not from_msc <= start_value <= end_value <= to_msc
                or start_value <= previous_end
            ):
                raise ValueError("Cobertura v2 inválida")
            previous_end = end_value
            ranges.append((start, end))
        return V2Coverage(tuple(ranges), incomplete)

    @staticmethod
    def _cursor(value: object) -> tuple[int, str]:
        if not isinstance(value, str) or value.count(":") != 1:
            raise ValueError("Cursor v2 inválido")
        event, ticket = value.split(":")
        if not event.isdecimal() or not ticket.isdecimal():
            raise ValueError("Cursor v2 inválido")
        if (
            str(int(event)) != event
            or str(int(ticket)) != ticket
            or int(event) > MAX_INT64
            or int(ticket) > MAX_UINT64
        ):
            raise ValueError("Cursor v2 inválido")
        return int(event), ticket


class V2HistoryProvider:
    """Expose v2 recovered deals and existing metric formulas to the dashboard."""

    def __init__(self, client: LoopbackV2HistoryClient) -> None:
        self._client = client

    def deal_history(
        self,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> TelemetryDealPage:
        return self._client.deal_history(
            from_msc=from_msc,
            to_msc=to_msc,
            magic_number=magic_number,
            limit=limit,
            cursor=cursor,
        )

    def position_cycles(
        self,
        *,
        owner_magic: str | None = None,
        owner_magics: tuple[str, ...] = (),
        from_msc: int | None = None,
        to_msc: int | None = None,
        closed_only: bool = False,
        limit: int = 50,
        cursor: str | None = None,
    ) -> TelemetryPositionCyclePage:
        return self._client.position_cycles(
            owner_magic=owner_magic,
            owner_magics=owner_magics,
            from_msc=from_msc,
            to_msc=to_msc,
            closed_only=closed_only,
            limit=limit,
            cursor=cursor,
        )

    def position_cycle_magics(self) -> tuple[str, ...]:
        return self._client.position_cycle_magics()

    def cycle_performance_metrics(
        self,
        *,
        from_msc: int,
        to_msc: int,
        owner_magic: str | None = None,
        owner_magics: tuple[str, ...] = (),
    ) -> TelemetryCyclePerformance:
        evidence = self._client.deal_history(
            from_msc=from_msc,
            to_msc=to_msc,
            magic_number=owner_magic,
            limit=1,
        )
        if evidence.coverage is None:
            raise DashboardReadError("El receptor no informó cobertura de deals")
        cycles: list[TelemetryPositionCycle] = []
        cursor: str | None = None
        account_id: str | None = None
        source_id: str | None = None
        inspected = 0
        while True:
            page = self.position_cycles(
                owner_magic=owner_magic,
                owner_magics=owner_magics,
                from_msc=from_msc,
                to_msc=to_msc,
                closed_only=True,
                limit=100,
                cursor=cursor,
            )
            account_id = page.account_id
            source_id = page.source_id
            inspected += len(page.cycles)
            cycles.extend(
                item for item in page.cycles if item.cycle.eligible_for_autonomous_metrics
            )
            cursor = page.next_cursor
            if cursor is None:
                break
            if inspected >= 500:
                raise DashboardReadError("El período supera el límite seguro de 500 operaciones")
        if account_id is None or source_id is None:
            raise DashboardReadError("El receptor no informó la cuenta")
        return TelemetryCyclePerformance(
            account_id,
            source_id,
            from_msc,
            to_msc,
            owner_magic,
            tuple(cycles),
            evidence.coverage,
        )

    def order_history(
        self,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> TelemetryHistoricalOrderPage:
        return self._client.order_history(
            from_msc=from_msc,
            to_msc=to_msc,
            magic_number=magic_number,
            limit=limit,
            cursor=cursor,
        )

    def performance_metrics(
        self,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None = None,
    ) -> TelemetryPerformance:
        deals: list[TelemetryDeal] = []
        cursor: str | None = None
        account_id: str | None = None
        while True:
            remaining = 500 - len(deals)
            if remaining <= 0:
                raise DashboardReadError("El período supera el límite seguro de 500 deals")
            page = self._client.deal_history(
                from_msc=from_msc,
                to_msc=to_msc,
                magic_number=magic_number,
                limit=min(100, remaining),
                cursor=cursor,
            )
            if account_id is not None and page.account_id != account_id:
                raise DashboardReadError("La cuenta cambió durante el cálculo")
            account_id = page.account_id
            deals.extend(page.deals)
            cursor = page.next_cursor
            if cursor is None:
                break
        if account_id is None:
            raise DashboardReadError("El receptor no informó la cuenta")
        return TelemetryPerformance(
            account_id=account_id,
            source_id=page.source_id,
            from_msc=from_msc,
            to_msc=to_msc,
            magic_number=magic_number,
            selection=calculate_closed_deal_metrics(deals),
        )
