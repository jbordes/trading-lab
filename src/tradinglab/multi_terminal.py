"""Stage the multicuenta collectors in one explicitly selected MT5 data directory."""

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from tradinglab.installation import private_directory

COLLECTORS = ("TradingLabTelemetry", "TradingLabActivity")
HELPER = "TradingLabAttachCollectors"


def replace_preset(path: Path, encoded: bytes) -> None:
    """Publish the complete generated preset inside its private directory."""
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        except OSError:
            stream.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _checked(path: Path) -> Path:
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError("La ruta contiene enlaces o uniones de directorio")
    return path


def stage_collectors(
    terminal: Path, binaries: Path, presets: Path, *, owned: dict[str, str]
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
    for source, dest in copies:
        if not _checked(source).is_file() or not source.stat().st_size:
            raise ValueError(f"Falta el archivo de instalación {source.name}")
        if _checked(dest).exists():
            with source.open("rb") as left, dest.open("rb") as right:
                current = hashlib.file_digest(right, "sha256").hexdigest()
                unchanged = hashlib.file_digest(left, "sha256").hexdigest() == current
                if not unchanged:
                    if current == owned.get(dest.name):
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
