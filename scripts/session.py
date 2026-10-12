#!/usr/bin/env python3
"""Create, validate and guard TradingLab daily logs."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


LAB_TIMEZONE = ZoneInfo("Europe/Madrid")
SCHEMA_EFFECTIVE_DATE = date(2026, 10, 12)
DAILY_SESSION_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?\.md$")
REQUIRED_DAILY_METADATA = ("Fecha", "Estado", "Zona horaria", "Schema de sesión")
REQUIRED_DAILY_SECTIONS = (
    "Actividades",
    "Hechos y evidencias",
    "Interpretaciones",
    "Decisiones",
    "Validaciones",
    "Preguntas abiertas",
    "Próximo paso",
    "Referencias",
)
PLACEHOLDER = re.compile(r"\[(?:completar|actividad|HH:MM|referencia)[^\]]*\]", re.IGNORECASE)


def madrid_now() -> datetime:
    return datetime.now(LAB_TIMEZONE)


def session_date_from_name(name: str) -> date | None:
    match = DAILY_SESSION_NAME.fullmatch(name)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def metadata_value(text: str, key: str) -> str | None:
    match = re.search(rf"(?m)^\*\*{re.escape(key)}:\*\*\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else None


def render_daily_log(moment: datetime, first_activity: str) -> str:
    day = moment.date().isoformat()
    time = moment.strftime("%H:%M")
    return f"""# Bitácora diaria de TradingLab — {day}

**Fecha:** {day}

**Estado:** Abierta

**Zona horaria:** Europe/Madrid

**Schema de sesión:** daily-v1

## Actividades

### {time} — Inicio de jornada

- {first_activity}

## Hechos y evidencias

- [completar]

## Interpretaciones

- [completar o indicar “No aplica”]

## Decisiones

- [completar o indicar “Ninguna”]

## Validaciones

- [completar o indicar “No aplica”]

## Preguntas abiertas

- [completar o indicar “Ninguna”]

## Próximo paso

- [completar]

## Referencias

- Git: [completar o indicar “No aplica”]
- Estrategias, datos, experimentos, runs o artefactos: [completar o indicar “No aplica”]
"""


def validate_session(path: Path, require_closed: bool = False) -> list[str]:
    errors: list[str] = []
    file_date = session_date_from_name(path.name)
    if file_date is None:
        return [f"Nombre de bitácora inválido: {path.name}"]
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        return [f"Bitácora inválida {path.name}: {error}"]

    if not text.startswith("# "):
        errors.append(f"La bitácora {path.name} no comienza con un título H1")
    if not metadata_value(text, "Fecha"):
        errors.append(f"La bitácora {path.name} no declara Fecha")

    if file_date >= SCHEMA_EFFECTIVE_DATE:
        for key in REQUIRED_DAILY_METADATA:
            if not metadata_value(text, key):
                errors.append(f"La bitácora {path.name} no declara {key}")
        if metadata_value(text, "Schema de sesión") != "daily-v1":
            errors.append(f"La bitácora {path.name} no usa daily-v1")
        declared_date = metadata_value(text, "Fecha")
        try:
            if date.fromisoformat(declared_date or "") != file_date:
                errors.append(f"La Fecha de {path.name} no coincide con su nombre")
        except ValueError:
            errors.append(f"La bitácora {path.name} no declara la Fecha en formato ISO")
        if metadata_value(text, "Zona horaria") != "Europe/Madrid":
            errors.append(f"La bitácora {path.name} debe usar Europe/Madrid")
        for section in REQUIRED_DAILY_SECTIONS:
            if not re.search(rf"(?m)^## {re.escape(section)}\s*$", text):
                errors.append(f"La bitácora {path.name} no contiene la sección {section}")
        status = metadata_value(text, "Estado")
        if status not in {"Abierta", "Cerrada"}:
            errors.append(f"La bitácora {path.name} tiene un Estado no admitido: {status}")
        if require_closed and status != "Cerrada":
            errors.append(f"La bitácora {path.name} debe estar Cerrada")
        if require_closed and PLACEHOLDER.search(text):
            errors.append(f"La bitácora {path.name} conserva marcadores sin completar")
    elif not (
        metadata_value(text, "Objetivo")
        or re.search(r"(?m)^## Objetivo\s*$", text)
        or re.search(r"(?m)^## Actividades\s*$", text)
    ):
        errors.append(f"La bitácora histórica {path.name} no declara su objetivo o actividades")
    return errors


def validate_sessions(root: Path, require_closed: bool = False, paths: list[Path] | None = None) -> list[str]:
    directory = root / "docs" / "sessions"
    candidates = paths or sorted(directory.glob("*.md"))
    errors: list[str] = []
    for path in candidates:
        if path.name in {"README.md", "_template.md"}:
            continue
        errors.extend(validate_session(path, require_closed=require_closed))
    return errors


def create_today(
    root: Path,
    first_activity: str,
    topic: str | None = None,
    moment: datetime | None = None,
) -> tuple[Path, bool]:
    current = moment or madrid_now()
    if topic and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", topic):
        raise ValueError("El tema debe usar kebab-case ASCII")
    suffix = f"-{topic}" if topic else ""
    target = root / "docs" / "sessions" / f"{current.date().isoformat()}{suffix}.md"
    if target.exists():
        return target, False
    target.write_text(render_daily_log(current, first_activity), encoding="utf-8", newline="\n")
    return target, True


def git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Falló Git")
    return result.stdout


def guard_direct_main_publish(root: Path, current_date: date | None = None) -> list[str]:
    today = current_date or madrid_now().date()
    errors: list[str] = []
    try:
        branch = git_output(root, "branch", "--show-current").strip()
        status = git_output(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
        changed = {Path(item[3:]) for item in status.split("\0") if item}
    except RuntimeError as error:
        return [str(error)]
    if branch != "main":
        errors.append("La publicación directa de la bitácora solo puede ejecutarse desde main")
    if not changed:
        errors.append("No hay cambios de bitácora para publicar")
    authorized: list[Path] = []
    unexpected: list[Path] = []
    for relative in changed:
        is_session_path = len(relative.parts) == 3 and relative.parts[:2] == ("docs", "sessions")
        if is_session_path and session_date_from_name(relative.name) == today and (root / relative).is_file():
            authorized.append(relative)
        else:
            unexpected.append(relative)
    if unexpected:
        errors.append(
            "El push directo contiene rutas no autorizadas: "
            + ", ".join(sorted(path.as_posix() for path in unexpected))
        )
    for relative in authorized:
        errors.extend(validate_session(root / relative))
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    today_parser = subparsers.add_parser("today", help="crear o localizar la bitácora de hoy")
    today_parser.add_argument("--activity", required=True, help="primera actividad de la jornada")
    today_parser.add_argument(
        "--topic",
        help="división excepcional de la jornada en kebab-case; normalmente se omite",
    )
    check_parser = subparsers.add_parser("check", help="validar bitácoras")
    check_parser.add_argument("paths", nargs="*", type=Path)
    check_parser.add_argument("--closed", action="store_true")
    subparsers.add_parser("guard-publish", help="verificar la excepción de push directo a main")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.command == "today":
        try:
            target, created = create_today(root, args.activity, topic=args.topic)
        except ValueError as error:
            print(f"[ERROR] {error}")
            return 1
        action = "creada" if created else "existente"
        print(f"[OK] Bitácora {action}: {target.relative_to(root).as_posix()}")
        return 0
    if args.command == "guard-publish":
        errors = guard_direct_main_publish(root)
    else:
        paths = [path if path.is_absolute() else root / path for path in args.paths] or None
        errors = validate_sessions(root, require_closed=args.closed, paths=paths)
    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        return 1
    print("[OK] Política de bitácora válida")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
