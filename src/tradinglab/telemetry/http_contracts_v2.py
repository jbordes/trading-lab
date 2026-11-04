"""Shared pure query parsing and wire presentation for telemetry v2 HTTP adapters."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from tradinglab.telemetry.sqlite_store_v2 import V2PositionCycleItem


def parse_activity_query(query: str) -> dict[str, Any]:
    values = parse_qs(
        query,
        keep_blank_values=True,
        strict_parsing=True,
        max_num_fields=6,
    )
    required = {"entity", "from_msc", "to_msc"}
    allowed = required | {"magic_number", "limit", "cursor"}
    if not required <= set(values) or not set(values) <= allowed:
        raise ValueError("Parámetros de actividad inválidos")
    if any(len(items) != 1 for items in values.values()):
        raise ValueError("Parámetros de actividad repetidos")
    entity = values["entity"][0]
    if entity not in {"deal", "order"}:
        raise ValueError("Entidad de actividad inválida")

    def integer(name: str, default: str | None = None) -> int:
        value = values.get(name, [default])[0]
        if value is None or not value.isascii() or not value.isdecimal():
            raise ValueError("Entero de actividad inválido")
        parsed = int(value)
        if str(parsed) != value:
            raise ValueError("Entero de actividad inválido")
        return parsed

    return {
        "entity_type": entity,
        "from_msc": integer("from_msc"),
        "to_msc": integer("to_msc"),
        "magic_number": values.get("magic_number", [None])[0],
        "limit": integer("limit", "50"),
        "cursor": values.get("cursor", [None])[0],
    }


def parse_position_cycles_query(query: str) -> dict[str, Any]:
    values = parse_qs(
        query,
        keep_blank_values=True,
        strict_parsing=True,
        max_num_fields=9,
    )
    if not set(values) <= {
        "owner_magic",
        "owner_magics",
        "from_msc",
        "to_msc",
        "closed_only",
        "order",
        "include_details",
        "limit",
        "cursor",
    }:
        raise ValueError("Parámetros de ciclos inválidos")
    if any(len(items) != 1 for items in values.values()):
        raise ValueError("Parámetros de ciclos repetidos")
    limit = values.get("limit", ["50"])[0]
    if not limit.isascii() or not limit.isdecimal() or str(int(limit)) != limit:
        raise ValueError("Límite de ciclos inválido")
    owner_magic = values.get("owner_magic", [None])[0]
    owner_magics_text = values.get("owner_magics", [None])[0]
    if owner_magic is not None and owner_magics_text is not None:
        raise ValueError("Filtros Magic incompatibles")
    owner_magics = () if owner_magics_text is None else tuple(owner_magics_text.split(","))
    if (
        len(owner_magics) > 12
        or len(set(owner_magics)) != len(owner_magics)
        or any(not item for item in owner_magics)
    ):
        raise ValueError("Selección Magic inválida")
    from_text = values.get("from_msc", [None])[0]
    to_text = values.get("to_msc", [None])[0]
    if (from_text is None) != (to_text is None):
        raise ValueError("El período de ciclos debe estar completo")
    if from_text is not None and to_text is not None:
        if any(
            not value.isascii() or not value.isdecimal() or str(int(value)) != value
            for value in (from_text, to_text)
        ):
            raise ValueError("Período de ciclos inválido")
        from_msc = int(from_text)
        to_msc = int(to_text)
        if not 0 <= from_msc < to_msc < 2**63:
            raise ValueError("Período de ciclos inválido")
    else:
        from_msc = None
        to_msc = None
    closed_text = values.get("closed_only", ["false"])[0]
    if closed_text not in {"true", "false"}:
        raise ValueError("closed_only inválido")
    order = values.get("order", ["desc"])[0]
    if order not in {"asc", "desc"}:
        raise ValueError("Orden de ciclos inválido")
    details_text = values.get("include_details", ["true"])[0]
    if details_text not in {"true", "false"}:
        raise ValueError("include_details inválido")
    return {
        "owner_magic": owner_magic,
        "owner_magics": owner_magics,
        "from_msc": from_msc,
        "to_msc": to_msc,
        "closed_only": closed_text == "true",
        "ascending": order == "asc",
        "include_details": details_text == "true",
        "limit": int(limit),
        "cursor": values.get("cursor", [None])[0],
    }


def position_cycle_item(item: V2PositionCycleItem) -> dict[str, object]:
    cycle = item.cycle
    return {
        "message_id": item.message_id,
        "source_id": item.source_id,
        "captured_at": item.captured_at,
        "details": item.details,
        "cycle": {
            "account_id": cycle.account_id,
            "position_id": cycle.position_id,
            "owner_magic": cycle.owner_magic,
            "observed_magics": cycle.observed_magics,
            "started_at_msc": cycle.started_at_msc,
            "last_event_at_msc": cycle.last_event_at_msc,
            "lifecycle": cycle.lifecycle.value,
            "remaining_signed_volume": str(cycle.remaining_signed_volume),
            "observed_net_result": str(cycle.observed_net_result),
            "deal_tickets": cycle.deal_tickets,
            "exclusions": tuple(reason.value for reason in cycle.exclusions),
            "eligible_for_autonomous_metrics": (cycle.eligible_for_autonomous_metrics),
        },
    }
