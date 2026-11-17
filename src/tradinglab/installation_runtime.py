"""Supervise owned installation processes; no restart loop or external process control."""

from __future__ import annotations

import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path


def supervise(
    commands: list[list[str]], ready_ports: list[int], ports: list[int], *, root: Path
) -> None:
    for port in ports:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError("Puerto ocupado; ningún proceso fue detenido") from exc
    children: list[subprocess.Popen] = []
    # Each child loads the private files for this installation, not stale shell tokens.
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("CENTRAL_", "RELAY_")) and name != "TRADINGLAB_DASHBOARD_TOKEN"
    }
    try:
        for command, port in zip(commands, ready_ports, strict=True):
            child = subprocess.Popen(command, cwd=root, shell=False, env=environment)
            children.append(child)
            deadline = time.monotonic() + 25
            while True:
                if any(process.poll() is not None for process in children):
                    raise RuntimeError("Un componente terminó durante el arranque")
                try:
                    path = "/login" if command[1].endswith("live_dashboard.py") else "/health"
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}{path}", timeout=2
                    ) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("No se confirmó disponibilidad del servicio")
                time.sleep(0.25)
        print(f"Dashboard: http://127.0.0.1:{ready_ports[-1]}/dashboard")
        while True:
            if any(process.poll() is not None for process in children):
                raise RuntimeError("Un componente terminó; se detiene esta ejecución")
            time.sleep(1)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
