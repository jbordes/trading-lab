"""Build the distributable Windows SetUp from product files and matching MT5 binaries."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "_storage/setup"
EXPERTS = ("TradingLabTelemetry", "TradingLabActivity", "TradingLabAttachCollectors")


def package() -> Path:
    content = {}
    for name in (
        "TradingLab SetUp.cmd",
        "scripts/tradinglab_setup_windows.ps1",
        "scripts/tradinglab_setup.py",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        "docs/development/tradinglab-setup.md",
    ):
        content[name] = (ROOT / name).read_bytes()
    assets = set(
        subprocess.check_output(
            ["git", "ls-files", "-z", "--", "src/tradinglab/dashboard/static"], cwd=ROOT
        )
        .decode()
        .split("\0")
    )
    for path in sorted((ROOT / "src/tradinglab").rglob("*")):
        if path.is_file() and (path.suffix == ".py" or path.relative_to(ROOT).as_posix() in assets):
            if path.is_symlink() or path.name.startswith(".") or "__pycache__" in path.parts:
                raise ValueError("Archivo inesperado en los fuentes del paquete")
            content[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    source = ROOT / "apps/mt5-telemetry-collector"
    for path in [*(source.glob("*.mqh")), *(source / (name + ".mq5") for name in EXPERTS)]:
        if path.read_text(encoding="utf-8-sig") != (BUILD / "compiled" / path.name).read_text(
            encoding="utf-8-sig"
        ):
            raise ValueError("Recompile MT5 antes de empaquetar " + path.name)
        content[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for name in EXPERTS:
        binary = (BUILD / "compiled" / (name + ".ex5")).read_bytes()
        if not binary:
            raise ValueError("EX5 vacío")
        content["collectors/" + name + ".ex5"] = binary
    content["LEEME.md"] = content["docs/development/tradinglab-setup.md"]
    manifest = {
        "layout": "tradinglab-setup-v2",
        "files": {p: hashlib.sha256(data).hexdigest() for p, data in sorted(content.items())},
    }
    content["MANIFEST.json"] = json.dumps(manifest, indent=2).encode()
    release = hashlib.sha256(content["MANIFEST.json"]).hexdigest()[:12]
    output = BUILD / f"TradingLab-SetUp-{release}.zip"
    with tempfile.NamedTemporaryFile(dir=BUILD, delete=False) as temporary:
        staged = Path(temporary.name)
    try:
        with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(content.items()):
                info = zipfile.ZipInfo("TradingLab/" + name, (2026, 1, 1, 0, 0, 0))
                archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
        with zipfile.ZipFile(staged) as archive:
            for name, digest in manifest["files"].items():
                if hashlib.sha256(archive.read("TradingLab/" + name)).hexdigest() != digest:
                    raise ValueError("Contenido de ZIP inconsistente")
        checksum = hashlib.sha256(staged.read_bytes()).hexdigest()
        if output.exists():
            if hashlib.sha256(output.read_bytes()).hexdigest() != checksum:
                raise FileExistsError(output)
        else:
            os.link(staged, output)
        output.with_suffix(".zip.sha256").write_text(
            checksum + "  " + output.name + "\n", encoding="ascii"
        )
    finally:
        staged.unlink(missing_ok=True)
    return output


if __name__ == "__main__":
    print(package())
