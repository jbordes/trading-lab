#!/usr/bin/env python3
"""Prepare locked dependencies and install; explicit --apply permits provisioning."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--allow-real-account", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--resume", action="store_true", help="Validar instalacion existente sin recrear datos"
    )
    parser.add_argument(
        "--start", action="store_true", help="Iniciar al terminar; requiere --apply"
    )
    args = parser.parse_args(argv)
    if args.start and not args.apply:
        parser.error("--start requiere --apply")
    uv = shutil.which("uv")
    if uv is None:
        print("Instale uv y añádalo a PATH antes de usar el bootstrap.", file=sys.stderr)
        return 1
    command = [
        uv,
        "run",
        "--no-sync",
        "python",
        str(ROOT / "scripts/install_tradinglab.py"),
        "--config",
        str(args.config.resolve()),
        "--data-dir",
        str(args.data_dir),
    ]
    if args.allow_real_account:
        command.append("--allow-real-account")
    if not args.apply:
        print(
            "Vista previa: uv sync --locked --no-dev; instalación nueva. No se descargó ni escribió nada."
        )
        print("Destino:", args.data_dir)
        return 0
    command.append("--apply")
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    try:
        subprocess.run(
            [uv, "sync", "--locked", "--no-dev"], cwd=ROOT, env=env, check=True, timeout=600
        )
        if args.resume:
            resume_command = [
                uv,
                "run",
                "--no-sync",
                "python",
                str(ROOT / "scripts/run_tradinglab.py"),
                "--data-dir",
                str(args.data_dir),
                "--dry-run",
                "--expected-config",
                str(args.config.resolve()),
            ]
            subprocess.run(resume_command, cwd=ROOT, env=env, check=True, timeout=120)
        else:
            subprocess.run(command, cwd=ROOT, env=env, check=True, timeout=120)
        if args.start:
            return subprocess.call(
                [
                    uv,
                    "run",
                    "--no-sync",
                    "python",
                    str(ROOT / "scripts/run_tradinglab.py"),
                    "--data-dir",
                    str(args.data_dir),
                ],
                cwd=ROOT,
                env=env,
            )
    except KeyboardInterrupt:
        return 130
    except OSError, subprocess.SubprocessError:
        print(
            "Bootstrap incompleto; revise dependencias y configuración. No se sobrescribe el destino.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
