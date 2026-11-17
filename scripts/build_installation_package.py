#!/usr/bin/env python3
"""Build a stable Windows installation package without local data or credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

GUIDE = """# TradingLab: prueba de instalacion estable en Windows

1. Extraer TODO el ZIP en una carpeta local, no ejecutar desde el ZIP.
2. Abrir Instalar-TradingLab.cmd con doble clic. Requiere Internet para descargar dependencias.
3. El ejemplo de la cuenta demo esta en _storage/installation/68324616.json.
   Es SOLO referencia. Para otra cuenta cambiar MT5 Account Nr., servidor,
   moneda, fecha de historial (hora broker), UTC offset y puertos segun corresponda.
   Para una cuenta real dejar Es Cuenta Demo DESMARCADO; revisar el resumen.
   Guardar JSON genera un archivo con el numero de la cuenta.
4. Elegir una carpeta de datos nueva fuera de esta carpeta de codigo. Completar instalacion e iniciar.
5. En la terminal MT5 elegida: Archivo > Abrir carpeta de datos.
   Copiar los dos archivos de collectors/ a MQL5/Experts/TradingLab.
   En Navegador > Asesores Expertos, hacer Refrescar.
6. Opciones > Asesores Expertos: permitir WebRequest a los origenes locales
   de los puertos elegidos, por ejemplo http://127.0.0.1:8776 y http://127.0.0.1:8777.
7. Colocar TradingLabTelemetry y TradingLabActivity en graficos distintos.
   En Parametros de entrada > Cargar elegir el .set de igual nombre de
   <carpeta de datos>/collector-presets. Confirmar y aceptar.
   Son collectors de solo lectura; no colocar ni modificar EAs de trading como parte de este procedimiento.
8. Abrir http://127.0.0.1:<Dashboard Port>/dashboard e ingresar con
   TRADINGLAB_DASHBOARD_TOKEN de .env.local en la carpeta privada de datos.
   No compartir tokens, presets ni esa carpeta de datos.
9. Comprobar cuenta, estado en vivo, actividad e historial hasta la fecha elegida.
   La captura e historia de equity empiezan con las observaciones disponibles.
10. Mantener la consola abierta. Ctrl+C detiene estos servicios.
    Para volver a iniciarlos: Iniciar-TradingLab.cmd y seleccionar
    installation.json de la carpeta de datos existente.

Los EAs de este paquete corresponden a esta version estable; no mezclar
con los de la plataforma remota. No incluye bases, credenciales ni presets
de la VPS. La captura es local en este paquete; para acceso desde otro equipo
hace falta un mecanismo de acceso seguro adicional, no expuesto por defecto.

Documentacion ampliada: docs/development/installation.md.
La prueba demo fue confirmada por el usuario. La prueba en cuenta real
y en un host nuevo siguen pendientes. No instala inicio automatico de Windows.
"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    from tradinglab.installation import read_config
    from tradinglab.installation_backend import LAYOUT

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compiled-dir", type=Path, required=True)
    parser.add_argument("--example", type=Path, required=True)
    args = parser.parse_args()
    if LAYOUT != "local-dual-v1":
        raise ValueError("Este paquete es exclusivo de la arquitectura estable")
    read_config(args.example)
    example_data = json.loads(args.example.read_text(encoding="utf-8-sig"))
    if example_data["account_mode"] != "demo":
        raise ValueError("El ejemplo distribuido debe ser demo")
    tracked = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
        )
        .decode()
        .split("\0")
    )
    files: dict[str, bytes] = {}
    for name in tracked:
        if not name:
            continue
        path = Path(name)
        # Product code, locked dependency definitions and text documentation only.
        include = (
            name
            in (
                "Instalar-TradingLab.cmd",
                "Iniciar-TradingLab.cmd",
                "README.md",
                "pyproject.toml",
                "uv.lock",
                ".python-version",
            )
            or path.parts[0] in ("src", "scripts", "apps")
            or (path.parts[0] == "docs" and path.suffix == ".md")
        )
        if not include:
            continue
        if path.suffix in (".ex5", ".sqlite3", ".db", ".pyc") or path.name.startswith(".env"):
            raise ValueError("Artefacto prohibido en los fuentes del paquete")
        source = ROOT / path
        if source.is_symlink() or not source.is_file():
            raise ValueError("Fuente ausente o enlazado")
        files[name.replace("\\", "/")] = source.read_bytes()
    for name in ("TradingLabTelemetry", "TradingLabActivity"):
        source = ROOT / "apps/mt5-telemetry-collector" / (name + ".mq5")
        compiled_source = args.compiled_dir / (name + ".mq5")
        if source.read_text() != compiled_source.read_text():
            raise ValueError("El compilado no corresponde al fuente actual")
        for header in source.parent.glob("*.mqh"):
            if header.read_text() != (args.compiled_dir / header.name).read_text():
                raise ValueError("El compilado no corresponde a los headers actuales")
        binary = (args.compiled_dir / (name + ".ex5")).read_bytes()
        if not binary:
            raise ValueError("Compilado vacio")
        files["collectors/" + name + ".ex5"] = binary
    login = example_data["login_id"]
    files[f"_storage/installation/{login}.json"] = (
        json.dumps(example_data, ensure_ascii=False, indent=2) + "\n"
    ).encode()
    files["LEEME-INSTALACION.md"] = GUIDE.encode()
    required = (
        "Instalar-TradingLab.cmd",
        "Iniciar-TradingLab.cmd",
        "scripts/setup_windows.ps1",
        "scripts/start_windows.ps1",
        "src/tradinglab/installation.py",
        "uv.lock",
    )
    if any(name not in files for name in required):
        raise ValueError("Paquete incompleto")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest = dict(
        layout=LAYOUT,
        base_commit=commit,
        working_tree_snapshot=True,
        created_at_utc=datetime.now(UTC).isoformat(),
        files={name: digest(data) for name, data in sorted(files.items())},
    )
    files["PACKAGE-MANIFEST.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(files.items()):
                archive.writestr("TradingLab-stable/" + name, data)
    with zipfile.ZipFile(args.output) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP corrupto")
        for name, expected in manifest["files"].items():
            if digest(archive.read("TradingLab-stable/" + name)) != expected:
                raise ValueError("Hash del paquete incorrecto")
    checksum = digest(args.output.read_bytes())
    args.output.with_suffix(".zip.sha256").write_text(
        f"{checksum}  {args.output.name}\n", encoding="ascii"
    )
    print(f"Paquete verificado: {args.output}")
    print(f"Archivos: {len(files)}; bytes: {args.output.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
