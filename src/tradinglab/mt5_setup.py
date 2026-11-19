"""Stage the stable collectors in one explicitly selected MT5 data directory."""

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from tradinglab.collector_presets import replace_preset
from tradinglab.installation import private_directory

COLLECTORS = ("TradingLabTelemetry", "TradingLabActivity")
HELPER = "TradingLabAttachCollectors"
# Previously distributed stable setup scripts. Never upgrade a trading EA by name.
PREVIOUS_HELPERS = frozenset(
    {
        "ed731b5275607d0b7b9bfb473e5d1b059c8010a352f3b648b1af2e6946969d6c",
        "86d4d321a5784d3ce829e542b73cb21fc095ec55a5b5a54509c8326b0f337079",
        "a381d9e3722bdab8344e4d6d0a2316731bd69720ca052c9a37566db2a7941688",
        "8227099ceea97cb3fc75e3b26139e3366e40fc6e484778f05560a9371a7306fc",
        "256de699110e752f80d7ac11df33cbebc7185f8e6b1fcc9d418784485ee7d89a",
    }
)


def _checked(path: Path) -> Path:
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError("La ruta contiene enlaces o uniones de directorio")
    return path


def _preset_identity(path: Path) -> tuple[str, ...]:
    fields = ("ExpectedDemoLogin", "ExpectedDemoServer", "AllowRealAccount")
    identity = {}
    if path.stat().st_size <= 8192:
        try:
            lines = path.read_bytes().decode("utf-16").splitlines()
        except UnicodeError:
            raise ValueError("El preset existente no identifica la cuenta MT5") from None
        for line in lines:
            key, _, value = line.partition("=")
            if key in fields:
                if key in identity or not value:
                    raise ValueError("Identidad de preset ambigua")
                identity[key] = value
    if not all(key in identity for key in fields):
        raise ValueError("El preset existente no identifica la cuenta MT5")
    return tuple(identity[key] for key in fields)


def stage_collectors(
    terminal: Path, binaries: Path, presets: Path, *, resume: bool = False
) -> None:
    if not terminal.is_absolute() or ".." in terminal.parts:
        raise ValueError("Seleccione la carpeta de datos absoluta de MT5")
    root = _checked(terminal / "MQL5")
    for folder in ("Experts", "Scripts", "Files"):
        if not _checked(root / folder).is_dir():
            raise ValueError("Seleccione Archivo > Abrir carpeta de datos en la terminal elegida")
    template = _checked(root / "Profiles/Templates/default.tpl")
    if template.exists():
        raw = template.read_bytes()
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            content = raw.decode("utf-16")
        elif b"\0" in raw:
            content = raw.decode("utf-16-le")
        else:
            content = raw.decode("ascii", errors="replace")
        if "<chart>" not in content.lower() or "<expert" in content.lower():
            raise ValueError("Revise default.tpl de MT5 antes de abrir gráficos automáticamente")
    target = root / "Files/TradingLabSetup"
    copies = [(binaries / f"{HELPER}.ex5", root / f"Scripts/TradingLab/{HELPER}.ex5")]
    for name in COLLECTORS:
        copies.extend(
            [
                (binaries / f"{name}.ex5", root / f"Experts/TradingLab/{name}.ex5"),
                (presets / f"{name}.set", target / f"{name}.set"),
            ]
        )
    pending = []
    replacements = []
    telemetry_unchanged = False
    for source, dest in copies:
        if not _checked(source).is_file() or not source.stat().st_size:
            raise ValueError(f"Falta el archivo de instalación {source.name}")
        if _checked(dest).exists():
            with source.open("rb") as left, dest.open("rb") as right:
                current = hashlib.file_digest(right, "sha256").hexdigest()
                unchanged = hashlib.file_digest(left, "sha256").hexdigest() == current
                if dest == target / "TradingLabTelemetry.set":
                    telemetry_unchanged = unchanged
                if not unchanged:
                    if (
                        dest == root / f"Scripts/TradingLab/{HELPER}.ex5"
                        and current in PREVIOUS_HELPERS
                    ):
                        replacements.append((source, dest))
                        continue
                    if dest.parent == target:
                        try:
                            same_account = _preset_identity(dest) == _preset_identity(source)
                        except ValueError:
                            same_account = (
                                resume
                                and telemetry_unchanged
                                and dest.name == "TradingLabActivity.set"
                            )
                        if same_account:
                            replacements.append((source, dest))
                            continue
                    raise ValueError(f"Existe otra versión de {dest.name}. Revise la terminal.")
        else:
            pending.append((source, dest))
    # Publish both presets together after restricting the Windows ACL. Never
    # add a token to a pre-existing sandbox directory of unknown ownership.
    if not target.exists():
        with tempfile.TemporaryDirectory(dir=target.parent) as staging_dir:
            secured = Path(staging_dir) / "presets"
            private_directory(secured)
            for name in COLLECTORS:
                shutil.copyfile(presets / f"{name}.set", secured / f"{name}.set")
            secured.rename(target)
    elif any(dest.parent == target for _, dest in pending):
        raise ValueError("El directorio privado de presets ya existe y está incompleto")
    for source, dest in pending:
        if dest.parent == target:
            continue
        dest.parent.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as staging:
            temp = Path(staging.name)
        try:
            shutil.copyfile(source, temp)
            # Publish complete files without replacing a concurrent installation.
            os.link(temp, dest)
        finally:
            temp.unlink()
    for source, dest in replacements:
        replace_preset(dest, source.read_bytes())
