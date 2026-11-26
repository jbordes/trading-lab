"""Dashboard providers bound to the account selected by each browser tab."""

from __future__ import annotations

from datetime import timedelta
from threading import Event, Lock, RLock
from urllib.parse import urlsplit

from tradinglab.dashboard.service import LiveDashboardService
from tradinglab.dashboard.telemetry import LoopbackTelemetryClient, TelemetrySnapshotSource
from tradinglab.dashboard.telemetry_v2 import LoopbackV2HistoryClient, V2HistoryProvider
from tradinglab.dashboard.web import create_server
from tradinglab.multi_config import Settings, api_request


class AccountViews:
    def __init__(self, api: str, keys: dict):
        self.api = api
        self.keys = keys
        self.lock = RLock()
        self.catalog = {}
        self.active = {}
        self.account_locks = {}
        self.closed = False

    def listing(self) -> list[dict]:
        rows = api_request(self.api + "/catalog", self.keys["CENTRAL_ACCOUNT_READ"])
        with self.lock:
            self.catalog = {row["account_id"]: row for row in rows}
        return rows

    def view(self, key: str) -> tuple:
        with self.lock:
            row = self.catalog[key]
            if self.closed:
                raise RuntimeError("El dashboard se está cerrando")
            if key in self.active:
                return self.active[key]
            account_lock = self.account_locks.setdefault(key, Lock())
        with account_lock:
            with self.lock:
                if self.closed:
                    raise RuntimeError("El dashboard se está cerrando")
                if key in self.active:
                    return self.active[key]
            base = self.api + "/accounts/" + key
            source_id = key + "-snapshot"
            source = TelemetrySnapshotSource(
                LoopbackTelemetryClient(
                    token=self.keys["CENTRAL_ACCOUNT_READ"],
                    source_id=source_id,
                    base_url=base,
                    central_api=True,
                ),
                source_id=source_id,
                max_age=timedelta(seconds=30),
            )
            history = V2HistoryProvider(
                LoopbackV2HistoryClient(
                    read_authorization=self.keys["CENTRAL_TRADING_READ"],
                    activity_source_id=key + "-activity",
                    base_url=base,
                )
            )
            service = LiveDashboardService(
                source, health_provider=source, capture_interval_seconds=20
            )
            service.start()
            with self.lock:
                self.active[key] = service, history, history, history, source, row["broker_offset"]
                return self.active[key]

    def close(self) -> None:
        with self.lock:
            self.closed = True
            accounts = list(self.account_locks.items())
        for key, account_lock in accounts:
            with account_lock:
                with self.lock:
                    view = self.active.pop(key, None)
                if view is not None:
                    view[0].stop()


def serve_dashboard(settings: Settings, keys: dict, stop: Event) -> None:
    views = AccountViews(settings.api_base_url, keys)
    public = urlsplit(settings.dashboard_url)
    server = create_server(
        None,
        port=settings.port("dashboard"),
        dashboard_token=keys["password"],
        accounts=views,
        public_authority=public.netloc.lower(),
        secure_cookie=public.scheme == "https",
    )
    try:
        server.timeout = 0.5
        while not stop.is_set():
            server.handle_request()
    finally:
        server.server_close()
        views.close()
