#!/usr/bin/env python3
"""Read-only change summary. Recommendations never execute checks."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "--no-optional-locks", *args],
        cwd=root,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if result.returncode:
        raise ValueError("No se pudo consultar Git; revisar repositorio y referencia base.")
    return result.stdout.decode("utf-8", errors="replace")


def category(path: str) -> str:
    parts = PurePosixPath(path).parts
    if path in {"README.md", "AGENTS.md"} or (
        parts[0] == "docs" and PurePosixPath(path).suffix == ".md"
    ):
        return "documentación"
    if path in {"scripts/check.py", "scripts/session.py", "scripts/change.py"} or path.startswith(
        ("tests/harness/", ".codex/", ".github/")
    ):
        return "harness"
    if path.startswith(("src/", "tests/unit/", "tests/integration/")):
        return "producto"
    return "sin clasificar"


def recommend(paths: list[str]) -> dict[str, object]:
    groups = sorted({category(path) for path in paths})
    if not paths:
        return {
            "tipo": "sin cambios",
            "motivo": "No hay archivos modificados en el alcance consultado.",
            "recomendación": "No ejecutar validaciones por esta consulta.",
        }
    if groups == ["documentación"]:
        advice = "Al preparar el commit: check.py docs; sin tests de producto."
    elif "sin clasificar" in groups:
        advice = (
            "Revisar las rutas no clasificadas antes de elegir pruebas. "
            "Si persiste la incertidumbre, usar check.py full al cerrar el cambio."
        )
    else:
        advice = (
            "Durante el trabajo: check.py fast y tests dirigidos al comportamiento cambiado. "
            "Antes del PR: check.py full, salvo resultado vigente para el mismo cambio."
        )
        if "harness" in groups:
            advice += " Revisar impacto en portabilidad; tests dirigidos en tests/harness."
    return {
        "tipo": groups[0] if len(groups) == 1 else "mixto",
        "grupos": groups,
        "motivo": "Clasificación conservadora por rutas; no analiza dependencias ni contenido.",
        "recomendación": advice,
    }


def inspect(root: Path, base: str | None = None) -> dict[str, object]:
    branch = git(root, "branch", "--show-current").strip()
    if base is None:
        base = "HEAD" if branch in {"main", "master", ""} else "origin/main"
        reference = git(root, "merge-base", "HEAD", base).strip()
    else:
        reference = git(
            root, "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}"
        ).strip()
    paths: set[str] = set()
    for args in (
        ("diff", "--name-only", "--no-renames", "-z", reference, "--"),
        ("diff", "--cached", "--name-only", "--no-renames", "-z", "HEAD", "--"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        paths.update(path for path in git(root, *args).split("\0") if path)
    ordered = sorted(paths)
    return {
        "rama": branch or "HEAD separado",
        "base": reference,
        "cantidad_archivos": len(ordered),
        "archivos": ordered,
        **recommend(ordered),
        "nota": (
            "Solo recomendación: no ejecuta pruebas, agentes, red ni escrituras. "
            "No conoce validaciones previas: no repetir resultados vigentes sin motivo. "
            "Ante un fallo, diagnosticar antes de reintentar."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inspect"])
    parser.add_argument("--base", help="Comparar con este commit; HEAD limita a cambios locales.")
    args = parser.parse_args()
    try:
        report = inspect(Path(__file__).resolve().parents[1], args.base)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f"No se pudo inspeccionar el cambio: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
