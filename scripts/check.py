#!/usr/bin/env python3
"""Portable validation entry point for TradingLab 2.0."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

from session import SESSION_NAME, validate_sessions


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


REQUIRED_PATHS = (
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    ".python-version",
    "AGENTS.md",
    "README.md",
    "docs/architecture/development-harness-0.1.md",
    "docs/adr/0001-portable-development-harness.md",
    "docs/adr/README.md",
    "docs/development/environment.md",
    "docs/sessions/README.md",
    "docs/sessions/_template.md",
    ".env.example",
    "pyproject.toml",
    "scripts/check.py",
    "uv.lock",
)

FORBIDDEN_NAMES = {".env", "credentials.json", "settings.local.json"}
FORBIDDEN_SUFFIXES = {".bak", ".db", ".ex4", ".ex5", ".key", ".pem", ".sqlite", ".sqlite3"}
TEXT_SUFFIXES = {
    ".cfg", ".css", ".csv", ".editorconfig", ".gitignore", ".html", ".ini",
    ".js", ".json", ".md", ".mq5", ".mqh", ".ps1", ".py", ".sh",
    ".toml", ".ts", ".txt", ".xml", ".yaml", ".yml",
}
MAX_TRACKED_SIZE = 10 * 1024 * 1024

SECRET_PATTERNS = (
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "assigned secret",
        re.compile(
            r"(?im)^\s*(?:[{,]\s*)?[\"']?(?:[A-Za-z0-9]+[_-])*"
            r"(?:api[_-]?key|password|secret|token)[\"']?\s*[:=]\s*"
            r"[\"']?(?!<|your[_-]|change[_-]?me|example|placeholder)[A-Za-z0-9_./+=-]{12,}"
        ),
    ),
)

MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
CONFLICT_MARKERS = re.compile(r"^(?:<{7}|={7}|>{7})(?:\s|$)", re.MULTILINE)
ADR_NAME = re.compile(r"^\d{4}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
ADR_STATES = {"proposed", "accepted", "superseded", "rejected"}
ADR_SECTIONS = ("Contexto", "Alternativas consideradas", "Decisión", "Consecuencias")


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def versioned_files(root: Path) -> tuple[list[Path], list[str]]:
    result = run_git(root, "ls-files", "-z")
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        return [], [f"No se pudo consultar Git: {message}"]
    paths = [Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]
    return paths, []


def check_required(root: Path) -> list[str]:
    return [f"Falta la ruta requerida: {path}" for path in REQUIRED_PATHS if not (root / path).exists()]


def check_repository_boundaries(root: Path, files: list[Path]) -> list[str]:
    errors: list[str] = []
    for relative in files:
        path = root / relative
        root_part = relative.parts[0].lower() if relative.parts else ""
        if root_part in {"_storage", "storage"}:
            errors.append(f"Storage operativo versionado: {relative.as_posix()}")
        if relative.name.lower() in FORBIDDEN_NAMES or relative.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"Archivo prohibido en Git: {relative.as_posix()}")
        if path.is_file() and path.stat().st_size > MAX_TRACKED_SIZE:
            errors.append(f"Archivo versionado mayor a 10 MiB: {relative.as_posix()}")
    return errors


def is_text_file(path: Path) -> bool:
    return path.name in {
        ".editorconfig", ".env.example", ".gitattributes", ".gitignore", ".python-version"
    } or path.suffix.lower() in TEXT_SUFFIXES


def check_text_safety(root: Path, files: list[Path]) -> list[str]:
    errors: list[str] = []
    for relative in files:
        path = root / relative
        if not path.is_file() or not is_text_file(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"Texto no codificado como UTF-8: {relative.as_posix()}")
            continue
        if CONFLICT_MARKERS.search(text):
            errors.append(f"Marcadores de conflicto Git: {relative.as_posix()}")
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"Posible {label} en {relative.as_posix()}")
    return errors


def check_markdown_links(root: Path, files: list[Path]) -> list[str]:
    errors: list[str] = []
    for relative in files:
        if relative.suffix.lower() != ".md":
            continue
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            target_path = unquote(target.split("#", 1)[0])
            if target_path and not (path.parent / target_path).resolve().exists():
                errors.append(f"Enlace Markdown roto en {relative.as_posix()}: {target}")
    return errors


def check_adrs(root: Path) -> list[str]:
    errors: list[str] = []
    directory = root / "docs" / "adr"
    for path in sorted(directory.glob("*.md")):
        if path.name in {"README.md", "_template.md"}:
            continue
        if not ADR_NAME.fullmatch(path.name):
            errors.append(f"Nombre de ADR inválido: {path.name}")
            continue
        text = path.read_text(encoding="utf-8")
        status_match = re.search(r"(?m)^\*\*Estado:\*\*\s*(\w+)\s*$", text)
        if not status_match or status_match.group(1) not in ADR_STATES:
            errors.append(f"ADR {path.name} sin Estado admitido")
        if not re.search(r"(?m)^\*\*Fecha:\*\*\s*\d{4}-\d{2}-\d{2}\s*$", text):
            errors.append(f"ADR {path.name} sin Fecha ISO")
        for section in ADR_SECTIONS:
            if not re.search(rf"(?m)^## {re.escape(section)}\s*$", text):
                errors.append(f"ADR {path.name} sin sección {section}")
    return errors


def changed_files(root: Path) -> tuple[set[Path], list[str]]:
    base_branch = os.environ.get("GITHUB_BASE_REF")
    if not base_branch:
        branch_result = run_git(root, "branch", "--show-current")
        branch = branch_result.stdout.decode("utf-8", errors="replace").strip()
        if branch in {"", "main", "master"}:
            return set(), []
        base_branch = "main"
    base_ref = f"origin/{base_branch}"
    verify = run_git(root, "rev-parse", "--verify", base_ref)
    if verify.returncode != 0:
        return set(), [f"No se pudo resolver la base de la rama: {base_ref}"]
    paths: set[Path] = set()
    for args in (("diff", "--name-only", "-z", f"{base_ref}...HEAD"), ("diff", "--name-only", "-z", "--cached")):
        result = run_git(root, *args)
        if result.returncode != 0:
            return set(), ["No se pudo calcular el diff para validar la bitácora"]
        paths.update(Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item)
    return paths, []


def check_change_traceability(root: Path) -> list[str]:
    paths, errors = changed_files(root)
    if errors or not paths:
        return errors
    session_changed = any(
        len(path.parts) == 3
        and path.parts[:2] == ("docs", "sessions")
        and SESSION_NAME.fullmatch(path.name)
        and (root / path).is_file()
        for path in paths
    )
    if not session_changed:
        errors.append("La rama debe crear o actualizar una bitácora en docs/sessions/YYYY-MM-DD-<tema>.md")
    return errors


def run_unit_tests(root: Path) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/harness", "-p", "test_*.py", "-v"],
        cwd=root,
        check=False,
    )
    return [] if result.returncode == 0 else ["Fallaron los tests del harness"]


def validate(root: Path, mode: str) -> list[str]:
    files, errors = versioned_files(root)
    errors.extend(check_required(root))
    errors.extend(check_repository_boundaries(root, files))
    errors.extend(check_text_safety(root, files))
    errors.extend(check_markdown_links(root, files))
    errors.extend(check_adrs(root))
    errors.extend(validate_sessions(root, require_closed=mode == "full"))
    if mode == "full":
        errors.extend(check_change_traceability(root))
        errors.extend(run_unit_tests(root))
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fast", "full"), nargs="?", default="fast")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    print(f"TradingLab Harness 0.1 | modo={args.mode}")
    errors = validate(root, args.mode)
    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        print(f"Resultado: {len(errors)} error(es)")
        return 1
    print("[OK] Estructura, límites del repositorio, textos, secretos y enlaces")
    if args.mode == "full":
        print("[OK] Tests del harness")
    print("Resultado: validación correcta")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
