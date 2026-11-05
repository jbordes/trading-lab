#!/usr/bin/env python3
"""Create a fresh current-schema telemetry v2 database; preview unless --apply."""

from provision_telemetry_v2_db import main

if __name__ == "__main__":
    raise SystemExit(main())
