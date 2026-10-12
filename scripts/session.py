#!/usr/bin/env python3
"""Create and validate TradingLab session logs."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


SCHEMA_EFFECTIVE_DATE = date(2026, 10, 12)
SESSION_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")
REQUIRED_V1_METADATA = ("Fecha", "Estado", "Objetivo", "Schema de sesión")
REQUIRED_V1_SECTIONS = (
    "Hechos y evidencias",
    "Interpretaciones",
    "Trabajo realizado",
    "Decisiones",
    "Validación",
    "Preguntas abiertas",
    "Próximo paso",
    "Referencias",
)
PLACEHOLDER = re.compile(
    r"\[(?:completar|AAAA-MM-DD|objetivo concreto|título|comandos)[^\]]*\]",
    re.IGNORECASE,
)


def metadata_value(text: str, key: str) -> str | None:
    match = re.search(rf"(?m)^\*\*{re.escape(key)}:\*\*\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else None


def render_session(session_date: date, slug: str, objective: str) -> str:
    title = " ".join(part.capitalize() for part in slug.split("-"))
    return f"""# Bitácora — {title}

**Fecha:** {session_date.isoformat()}

**Estado:** En curso

**Objetivo:** {objective}

**Schema de sesión:** session-v1

## Hechos y evidencias

- [completar]

## Interpretaciones

- [completar o indicar “No aplica”]

## Trabajo realizado

- [completar]

## Decisiones

- [completar o enlazar el ADR]

## Validación

- [comandos, comprobaciones y resultado]

## Preguntas abiertas

- [completar o indicar “Ninguna”]

## Próximo paso

- [completar]

## Referencias

- Rama: [completar]
- Commits: [completar]
- PR: [completar]
- ADR: [completar o indicar “No aplica”]
- Proyectos, experimentos o runs: [completar o indicar “No aplica”]
"""


def validate_session(path: Path, require_closed: bool = False) -> list[str]:
    errors: list[str] = []
    match = SESSION_NAME.fullmatch(path.name)
    if not match:
        return [f"Nombre de sesión inválido: {path.name}"]
    try:
        file_date = date.fromisoformat(match.group(1))
        text = path.read_text(encoding="utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        return [f"Sesión inválida {path.name}: {error}"]

    if not text.startswith("# "):
        errors.append(f"La sesión {path.name} no comienza con un título H1")
    if not metadata_value(text, "Fecha"):
        errors.append(f"La sesión {path.name} no declara Fecha")
    if not (metadata_value(text, "Objetivo") or re.search(r"(?m)^## Objetivo\s*$", text)):
        errors.append(f"La sesión {path.name} no declara Objetivo")

    if file_date >= SCHEMA_EFFECTIVE_DATE:
        for key in REQUIRED_V1_METADATA:
            if not metadata_value(text, key):
                errors.append(f"La sesión {path.name} no declara {key}")
        if metadata_value(text, "Schema de sesión") != "session-v1":
            errors.append(f"La sesión {path.name} no usa session-v1")
        declared_date = metadata_value(text, "Fecha")
        try:
            if date.fromisoformat(declared_date or "") != file_date:
                errors.append(f"La Fecha de {path.name} no coincide con su nombre")
        except ValueError:
            errors.append(f"La sesión {path.name} no declara la Fecha en formato ISO")
        for section in REQUIRED_V1_SECTIONS:
            if not re.search(rf"(?m)^## {re.escape(section)}\s*$", text):
                errors.append(f"La sesión {path.name} no contiene la sección {section}")
        status = metadata_value(text, "Estado")
        if status not in {"En curso", "Cerrada"}:
            errors.append(f"La sesión {path.name} tiene un Estado no admitido: {status}")
        if require_closed and status != "Cerrada":
            errors.append(f"La sesión {path.name} debe estar Cerrada antes del PR")
        if require_closed and PLACEHOLDER.search(text):
            errors.append(f"La sesión {path.name} conserva marcadores sin completar")
    return errors


def validate_sessions(root: Path, require_closed: bool = False) -> list[str]:
    directory = root / "docs" / "sessions"
    errors: list[str] = []
    for path in sorted(directory.glob("*.md")):
        if path.name in {"README.md", "_template.md"}:
            continue
        errors.extend(validate_session(path, require_closed=require_closed))
    return errors


def create_session(root: Path, slug: str, objective: str, session_date: date) -> Path:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError("El tema debe usar kebab-case ASCII")
    target = root / "docs" / "sessions" / f"{session_date.isoformat()}-{slug}.md"
    if target.exists():
        raise FileExistsError(f"La sesión ya existe: {target}")
    target.write_text(render_session(session_date, slug, objective), encoding="utf-8", newline="\n")
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    new_parser = subparsers.add_parser("new", help="crear una sesión session-v1")
    new_parser.add_argument("slug")
    new_parser.add_argument("--objective", required=True)
    new_parser.add_argument("--date", default=date.today().isoformat())
    check_parser = subparsers.add_parser("check", help="validar las sesiones")
    check_parser.add_argument("--closed", action="store_true", help="exigir cierre y ausencia de placeholders")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.command == "new":
        try:
            target = create_session(root, args.slug, args.objective, date.fromisoformat(args.date))
        except (ValueError, FileExistsError) as error:
            print(f"[ERROR] {error}")
            return 1
        print(f"[OK] Sesión creada: {target.relative_to(root).as_posix()}")
        return 0
    errors = validate_sessions(root, require_closed=args.closed)
    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        return 1
    print("[OK] Bitácoras de sesión válidas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
