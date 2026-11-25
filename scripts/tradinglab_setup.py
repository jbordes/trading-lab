#!/usr/bin/env python3
"""Thin command entry for the Windows SetUp. Sensitive inputs arrive on stdin."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    from tradinglab.multi_config import Settings, save_json
    from tradinglab.multi_host import SERVICES, run_service
    from tradinglab.multi_operations import dispatch

    if sys.argv[1:2] == ["serve"]:
        role, dest = sys.argv[2:]
        if role not in SERVICES:
            raise ValueError("Servicio desconocido")
        folder = Path(dest)
        config = Settings.model_validate_json((folder / "setup.json").read_bytes())
        try:
            run_service(config, role)
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            save_json(folder / (role + ".error.json"), {"error": type(exc).__name__})
            raise
        return 0
    data = json.loads(sys.stdin.buffer.read(65537).decode("utf-8-sig"))
    print(json.dumps(dispatch(ROOT, sys.argv[1], data), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    from urllib.error import HTTPError

    from pydantic import ValidationError

    try:
        sys.exit(main())
    except ValidationError as exc:
        fields = ", ".join(
            ".".join(map(str, item["loc"])) or "configuración"
            for item in exc.errors(include_input=False)
        )
        print("Configuración inválida. Revise " + fields, file=sys.stderr)
        sys.exit(1)
    except HTTPError as exc:
        print(
            f"La API respondió HTTP {exc.code}. Revise registro, URL y clave de administración.",
            file=sys.stderr,
        )
        sys.exit(1)
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
