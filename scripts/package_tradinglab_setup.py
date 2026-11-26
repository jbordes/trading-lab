"""Build the distributable Windows SetUp from product files and matching MT5 binaries."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "_storage/setup"
sys.path.insert(0, str(ROOT / "src"))

from tradinglab.multi_terminal import verified_collector_build  # noqa: E402


def package() -> Path:
    content = {}
    for name in (
        "TradingLab SetUp.cmd",
        "scripts/tradinglab_setup_windows.ps1",
        "scripts/tradinglab_setup.py",
        "scripts/backup_telemetry_db.py",
        "scripts/run_telemetry_maintenance.py",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        "docs/development/tradinglab-setup.md",
    ):
        content[name] = (ROOT / name).read_bytes()
    tracked = (
        subprocess.check_output(["git", "ls-files", "-z", "--", "src/tradinglab"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    for name in sorted(filter(None, tracked)):
        path = ROOT / name
        if path.suffix == ".py" or name.startswith("src/tradinglab/dashboard/static/"):
            if path.is_symlink() or not path.is_file():
                raise ValueError("Archivo inesperado en el paquete: " + name)
            content[name] = path.read_bytes()
    sources, binaries = verified_collector_build(ROOT)
    content.update({"apps/mt5-telemetry-collector/" + name: data for name, data in sources.items()})
    content.update({"collectors/" + name: data for name, data in binaries.items()})
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
