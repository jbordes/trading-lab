"""Validated dashboard adapter for durable telemetry v2 activity."""

from __future__ import annotations

import json
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
_CYCLE_ITEM_FIELDS = {"message_id", "source_id", "captured_at", "cycle"}
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

    def as_dict(self) -> dict[str, object]:
        return {
            "message_id": self.message_id,
            "captured_at": self.captured_at,
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

    def position_cycles(
        self,
        *,
        owner_magic: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> TelemetryPositionCyclePage:
        parameters: dict[str, str | int] = {"limit": limit}
        if owner_magic is not None:
            parameters["owner_magic"] = owner_magic
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
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DashboardReadError("El receptor devolvió ciclos v2 inválidos") from exc

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

    def _position_cycle_page(
        self,
        payload: object,
        *,
        owner_magic: str | None,
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
        return TelemetryPositionCycle(item["message_id"], item["captured_at"], cycle)

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
        limit: int = 50,
        cursor: str | None = None,
    ) -> TelemetryPositionCyclePage:
        return self._client.position_cycles(
            owner_magic=owner_magic,
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
