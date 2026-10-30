#!/usr/bin/env python3
"""Portable validation entry point for TradingLab 2.0."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path
from urllib.parse import unquote

from session import (
    configured_stable_branch,
    madrid_now,
    session_date_from_name,
    validate_sessions,
)

HARNESS_VERSION = "0.2"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


REQUIRED_PATHS = (
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    ".python-version",
    ".codex/config.toml",
    ".codex/agents/docs-recorder.toml",
    ".codex/agents/git-operator.toml",
    "AGENTS.md",
    "README.md",
    "docs/architecture/development-harness-0.2.md",
    "docs/adr/0001-portable-development-harness.md",
    "docs/adr/README.md",
    "docs/development/environment.md",
    "docs/development/coding-standards.md",
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
    ".cfg",
    ".css",
    ".csv",
    ".editorconfig",
    ".gitignore",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".mq5",
    ".mqh",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
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
# Secuencias típicas de doble encoding UTF-8: "Ã" o "Â" seguidos de un
# carácter no ASCII (caso de 2 bytes) o la secuencia de 3 bytes que produce
# guiones largos y puntos suspensivos rotos. Escritas con escapes unicode
# para que este mismo archivo no se auto-detecte como mojibake.
MOJIBAKE = re.compile("[\\u00c3\\u00c2][^\\u0000-\\u007f]|\\u00e2\\u20ac")
ADR_NAME = re.compile(r"^\d{4}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
ADR_STATES = {"proposed", "accepted", "superseded", "rejected"}
ADR_SECTIONS = ("Contexto", "Alternativas consideradas", "Decisión", "Consecuencias")
MQL5_FORBIDDEN_TOKENS = (
    "#import",
    "ctrade",
    "orderdelete(",
    "ordersend(",
    "positionclose(",
    "positioncloseby(",
    "positionmodify(",
)


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
    )


def versioned_files(root: Path) -> tuple[list[Path], list[str]]:
    result = run_git(root, "ls-files", "-z")
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        return [], [f"No se pudo consultar Git: {message}"]
    paths = [Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]
    return paths, []


def check_required(root: Path) -> list[str]:
    return [
        f"Falta la ruta requerida: {path}" for path in REQUIRED_PATHS if not (root / path).exists()
    ]


def check_repository_boundaries(root: Path, files: list[Path]) -> list[str]:
    errors: list[str] = []
    for relative in files:
        path = root / relative
        root_part = relative.parts[0].lower() if relative.parts else ""
        if root_part in {"_storage", "storage"}:
            errors.append(f"Storage operativo versionado: {relative.as_posix()}")
        if (
            relative.name.lower() in FORBIDDEN_NAMES
            or relative.suffix.lower() in FORBIDDEN_SUFFIXES
        ):
            errors.append(f"Archivo prohibido en Git: {relative.as_posix()}")
        if path.is_file() and path.stat().st_size > MAX_TRACKED_SIZE:
            errors.append(f"Archivo versionado mayor a 10 MiB: {relative.as_posix()}")
    return errors


def is_text_file(path: Path) -> bool:
    return (
        path.name
        in {".editorconfig", ".env.example", ".gitattributes", ".gitignore", ".python-version"}
        or path.suffix.lower() in TEXT_SUFFIXES
    )


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
        if MOJIBAKE.search(text):
            errors.append(f"Posible mojibake (doble encoding UTF-8): {relative.as_posix()}")
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"Posible {label} en {relative.as_posix()}")
    return errors


def check_mql5_read_only(root: Path, files: list[Path]) -> list[str]:
    errors: list[str] = []
    for relative in files:
        if relative.suffix.lower() != ".mq5":
            continue
        path = root / relative
        if not path.is_file():
            continue
        normalized = "".join(path.read_text(encoding="utf-8").casefold().split())
        for token in MQL5_FORBIDDEN_TOKENS:
            if token in normalized:
                errors.append(
                    f"Operación no permitida en colector MQL5 {relative.as_posix()}: {token}"
                )
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


def check_agent_configs(root: Path) -> list[str]:
    errors: list[str] = []
    config_path = root / ".codex" / "config.toml"
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f"Configuración Codex inválida: {exc}"]
    agents_config = config.get("agents")
    if not isinstance(agents_config, dict) or agents_config.get("enabled") is not True:
        errors.append("La configuración debe habilitar agentes explícitamente")
    threads = agents_config.get("max_concurrent_threads_per_session") if agents_config else None
    if not isinstance(threads, int) or isinstance(threads, bool) or not 1 <= threads <= 4:
        errors.append("El máximo de subagentes concurrentes debe estar entre 1 y 4")

    expected_names = {"git_operator", "docs_recorder"}
    observed_names: set[str] = set()
    for path in sorted((root / ".codex" / "agents").glob("*.toml")):
        try:
            agent = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            errors.append(f"Agente Codex inválido {path.name}: {exc}")
            continue
        name = agent.get("name")
        for field in ("name", "description", "developer_instructions"):
            if not isinstance(agent.get(field), str) or not agent[field].strip():
                errors.append(f"Agente {path.name} sin {field} válido")
        if isinstance(name, str):
            if name in observed_names:
                errors.append(f"Nombre de agente duplicado: {name}")
            observed_names.add(name)
        if name in expected_names:
            if agent.get("model") != "gpt-6-luna":
                errors.append(f"El agente económico {name} debe usar gpt-6-luna")
            if agent.get("model_reasoning_effort") not in {"low", "medium"}:
                errors.append(f"El agente económico {name} debe usar esfuerzo low o medium")
            features = agent.get("features")
            disabled = ("apps", "plugins", "memories", "request_permissions_tool")
            if not isinstance(features, dict) or any(
                features.get(key) is not False for key in disabled
            ):
                errors.append(f"El agente económico {name} debe limitar capacidades no necesarias")
            skills = agent.get("skills")
            bundled = skills.get("bundled") if isinstance(skills, dict) else None
            if (
                not isinstance(skills, dict)
                or skills.get("include_instructions") is not False
                or not isinstance(bundled, dict)
                or bundled.get("enabled") is not False
            ):
                errors.append(f"El agente económico {name} debe omitir skills automáticas")
    missing = expected_names - observed_names
    if missing:
        errors.append("Faltan agentes económicos requeridos: " + ", ".join(sorted(missing)))
    return errors


def changed_files(root: Path) -> tuple[set[Path], list[str]]:
    pull_request_base = os.environ.get("GITHUB_BASE_REF")
    base_ref = os.environ.get("TRADINGLAB_BASE_SHA")
    if base_ref and set(base_ref) == {"0"}:
        base_ref = None
    if not base_ref:
        if pull_request_base:
            base_ref = f"origin/{pull_request_base}"
        else:
            try:
                stable_branch = configured_stable_branch(root)
            except (OSError, tomllib.TOMLDecodeError, ValueError) as error:
                return set(), [str(error)]
            branch_result = run_git(root, "branch", "--show-current")
            branch = branch_result.stdout.decode("utf-8", errors="replace").strip()
            if branch not in {"", stable_branch}:
                stable_ref = f"origin/{stable_branch}"
                merge_base = run_git(root, "merge-base", "HEAD", stable_ref)
                if merge_base.returncode != 0:
                    return set(), [f"No se pudo calcular el ancestro común con {stable_ref}"]
                base_ref = merge_base.stdout.decode("utf-8", errors="replace").strip()
    if not base_ref:
        return set(), []
    verify = run_git(root, "rev-parse", "--verify", base_ref)
    if verify.returncode != 0:
        return set(), [f"No se pudo resolver la base de la rama: {base_ref}"]
    comparison = base_ref
    if pull_request_base:
        head_ref = os.environ.get("TRADINGLAB_HEAD_SHA") or "HEAD"
        verify_head = run_git(root, "rev-parse", "--verify", head_ref)
        if verify_head.returncode != 0:
            return set(), [f"No se pudo resolver la cabeza del pull request: {head_ref}"]
        comparison = f"{base_ref}...{head_ref}"
    result = run_git(root, "diff", "--name-only", "-z", comparison, "--")
    if result.returncode != 0:
        return set(), ["No se pudo calcular el diff para validar la política de bitácora"]
    paths = {Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item}
    if pull_request_base:
        working_tree = run_git(root, "diff", "--name-only", "-z", "HEAD", "--")
        if working_tree.returncode != 0:
            return set(), ["No se pudo validar el árbol de trabajo"]
        paths.update(
            Path(item.decode("utf-8")) for item in working_tree.stdout.split(b"\0") if item
        )
    return paths, []


def local_changed_files(root: Path) -> tuple[set[Path], list[str]]:
    paths: set[Path] = set()
    for args in (
        ("diff", "--name-only", "-z", "HEAD", "--"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        result = run_git(root, *args)
        if result.returncode != 0:
            return set(), ["No se pudo validar el alcance local del cambio"]
        paths.update(Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item)
    return paths, []


def check_documentation_change_scope(root: Path) -> list[str]:
    branch_paths, errors = changed_files(root)
    if errors:
        return errors
    local_paths, errors = local_changed_files(root)
    if errors:
        return errors
    paths = branch_paths | local_paths
    allowed_files = {Path("AGENTS.md"), Path("README.md")}
    unauthorized = {
        path
        for path in paths
        if path not in allowed_files and (not path.parts or path.parts[0] != "docs")
    }
    if unauthorized:
        names = ", ".join(sorted(path.as_posix() for path in unauthorized))
        return [f"El modo docs solo admite documentación: {names}"]
    return []


def check_session_change_policy(root: Path, current_date: date | None = None) -> list[str]:
    paths, errors = changed_files(root)
    if errors or not paths:
        return errors
    dated_sessions = {
        path
        for path in paths
        if len(path.parts) == 3
        and path.parts[:2] == ("docs", "sessions")
        and session_date_from_name(path.name) is not None
    }
    if not dated_sessions:
        return []

    branch_result = run_git(root, "branch", "--show-current")
    branch = branch_result.stdout.decode("utf-8", errors="replace").strip()
    is_pull_request = bool(os.environ.get("GITHUB_BASE_REF"))
    try:
        stable_branch = configured_stable_branch(root)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as error:
        return [str(error)]
    if is_pull_request or branch != stable_branch:
        names = ", ".join(sorted(path.as_posix() for path in dated_sessions))
        return [f"Las ramas de cambio no pueden modificar bitácoras diarias: {names}"]

    today = current_date or madrid_now().date()
    unauthorized = {path for path in dated_sessions if session_date_from_name(path.name) != today}
    unauthorized.update(paths - dated_sessions)
    if unauthorized:
        names = ", ".join(sorted(path.as_posix() for path in unauthorized))
        errors.append(
            f"Un cambio directo de bitácora en {stable_branch} solo puede contener archivos "
            "fechados hoy: " + names
        )
    return errors


def run_unit_tests(root: Path) -> list[str]:
    errors: list[str] = []
    for suite in ("tests/harness", "tests/unit"):
        if not (root / suite).is_dir():
            continue
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                suite,
                "-p",
                "test_*.py",
            ],
            cwd=root,
            check=False,
        )
        if result.returncode != 0:
            errors.append(f"Fallaron los tests en {suite}")
    return errors


def run_code_quality(root: Path) -> list[str]:
    commands = (
        ([sys.executable, "-m", "ruff", "format", "--check", "."], "formato de Ruff"),
        ([sys.executable, "-m", "ruff", "check", "."], "lint de Ruff"),
    )
    errors: list[str] = []
    for command, label in commands:
        result = subprocess.run(command, cwd=root, check=False)
        if result.returncode != 0:
            errors.append(f"Falló {label}")
    return errors


def validate(root: Path, mode: str) -> list[str]:
    files, errors = versioned_files(root)
    errors.extend(check_required(root))
    errors.extend(check_repository_boundaries(root, files))
    errors.extend(check_text_safety(root, files))
    errors.extend(check_mql5_read_only(root, files))
    errors.extend(check_markdown_links(root, files))
    errors.extend(check_adrs(root))
    errors.extend(check_agent_configs(root))
    errors.extend(validate_sessions(root))
    if mode == "docs":
        errors.extend(check_documentation_change_scope(root))
        errors.extend(check_session_change_policy(root))
    else:
        errors.extend(run_code_quality(root))
    if mode == "full":
        errors.extend(check_session_change_policy(root))
        errors.extend(run_unit_tests(root))
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("docs", "fast", "full"), nargs="?", default="fast")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    print(f"TradingLab Harness {HARNESS_VERSION} | modo={args.mode}")
    errors = validate(root, args.mode)
    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        print(f"Resultado: {len(errors)} error(es)")
        return 1
    if args.mode == "docs":
        print("[OK] Documentación, límites, textos, secretos y enlaces")
    else:
        print("[OK] Estructura, límites, textos, secretos, enlaces, formato y lint")
    if args.mode == "full":
        print("[OK] Tests automatizados")
    print("Resultado: validación correcta")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
