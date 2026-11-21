"""Central account registration and account-scoped access to the existing receivers."""

from __future__ import annotations

import hashlib
import hmac
import re
import sqlite3
from contextlib import AsyncExitStack, asynccontextmanager, closing
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from tradinglab.telemetry.central_api import CentralSettings, create_central_app
from tradinglab.telemetry.remote_host import CENTRAL_KEYS


def credential(master: str, identity: str, role: str) -> str:
    signature = hmac.new(master.encode(), f"{identity}/{role}".encode(), "sha256").hexdigest()
    return f"{identity}.{signature}"


def valid_credential(value: str, master: str, role: str) -> bool:
    identity = value.partition(".")[0]
    return bool(re.fullmatch("[a-f0-9]{32}", identity)) and hmac.compare_digest(
        value, credential(master, identity, role)
    )


class Observed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    server: str = Field(min_length=1, max_length=128)
    login: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    mode: str = Field(pattern="^(demo|real)$")


class Registration(Observed):
    label: str = Field(min_length=1, max_length=128)
    currency: str = Field(pattern="^[A-Za-z0-9._-]{1,16}$")
    history_from: int = Field(gt=0, lt=253402300800)
    broker_offset: int = Field(ge=-840, le=840)


def register(database: Path, account: Registration) -> str:
    if account.history_from > int(datetime.now(UTC).timestamp()) + 60 * account.broker_offset:
        raise HTTPException(400, "La fecha de historial es posterior a la hora del broker")
    key = "a-" + hashlib.sha256((account.server + "\0" + account.login).encode()).hexdigest()[:32]
    stamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT a.label,a.currency,m.mode,m.history_from,m.broker_offset FROM mt5_accounts m "
            "JOIN accounts a USING(account_id) WHERE m.server=? AND m.login=?",
            (account.server, account.login),
        ).fetchone()
        if existing:
            if existing != (
                account.label,
                account.currency,
                account.mode,
                account.history_from,
                account.broker_offset,
            ):
                raise HTTPException(409, "La cuenta ya existe con otros parámetros")
            return key
        db.execute(
            "INSERT INTO accounts(account_id,label,login_masked,server,currency,created_at_utc) "
            "VALUES(?,?,?,?,?,?)",
            (
                key,
                account.label,
                "****" + account.login[-4:],
                account.server,
                account.currency,
                stamp,
            ),
        )
        db.execute(
            "INSERT INTO mt5_accounts VALUES(?,?,?,?,?,?)",
            (
                key,
                account.server,
                account.login,
                account.mode,
                account.history_from,
                account.broker_offset,
            ),
        )
        db.executemany(
            "INSERT INTO sources VALUES(?,?,?,?)",
            [(f"{key}-{role}", key, role, stamp) for role in ("snapshot", "live", "activity")],
        )
    return key


def catalog(database: Path) -> list[dict]:
    with closing(sqlite3.connect(database)) as db:
        db.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in db.execute(
                "SELECT a.account_id,a.label,a.currency,a.login_masked,m.server,m.login,m.mode,"
                "m.history_from,m.broker_offset FROM accounts a JOIN mt5_accounts m USING(account_id) "
                "ORDER BY a.label,a.account_id"
            )
        ]


def bearer(request: Request) -> str:
    values = request.headers.getlist("authorization")
    if len(values) != 1 or not values[0].isascii() or not values[0].startswith("Bearer "):
        raise HTTPException(401)
    return values[0][7:]


def central_app(database: Path, keys: dict, host: str) -> FastAPI:
    hosts = tuple(dict.fromkeys(("localhost", "127.0.0.1", host)))
    inners = {}
    stack = AsyncExitStack()

    async def attach(account_id: str) -> None:
        if account_id in inners:
            return
        row = next(row for row in catalog(database) if row["account_id"] == account_id)
        settings = CentralSettings(
            database,
            account_id + "-snapshot",
            account_id,
            *(keys[k] for k in CENTRAL_KEYS),
            allowed_hosts=hosts,
            snapshot_identity=(row["login_masked"], row["server"], row["currency"]),
        )
        inner = create_central_app(settings)
        await stack.enter_async_context(inner.router.lifespan_context(inner))
        app.mount("/accounts/" + account_id, inner)
        inners[account_id] = inner

    @asynccontextmanager
    async def lifespan(_app):
        async with stack:
            for row in catalog(database):
                await attach(row["account_id"])
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(hosts))

    @app.middleware("http")
    async def authorize_producer(request: Request, call_next):
        from starlette.responses import JSONResponse

        path = request.url.path
        if path.startswith("/accounts/") and request.method == "POST":
            role = path.rsplit("/", 1)[-1]
            roles = {
                "account-state": "CENTRAL_SNAPSHOT_INGEST",
                "trading-events": "CENTRAL_ACTIVITY_INGEST",
            }
            try:
                if role not in roles or not valid_credential(
                    bearer(request), keys["pairing"], role
                ):
                    raise HTTPException(401)
            except HTTPException:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            request.scope["headers"] = [
                (k, v) for k, v in request.scope["headers"] if k != b"authorization"
            ] + [(b"authorization", ("Bearer " + keys[roles[role]]).encode())]
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return {"status": "ready"}

    @app.get("/catalog")
    def listing(request: Request):
        if not hmac.compare_digest(bearer(request), keys["CENTRAL_ACCOUNT_READ"]):
            raise HTTPException(401)
        return [
            {k: row[k] for k in ("account_id", "label", "broker_offset")}
            for row in catalog(database)
        ]

    @app.post("/catalog")
    async def add(account: Registration, request: Request):
        if not hmac.compare_digest(bearer(request), keys["admin"]):
            raise HTTPException(401)
        account_id = register(database, account)
        await attach(account_id)
        return {"account_id": account_id}

    @app.post("/resolve/{role}")
    def resolve(role: str, identity: Observed, request: Request):
        if role not in ("account-state", "trading-events") or not valid_credential(
            bearer(request), keys["pairing"], role
        ):
            raise HTTPException(401)
        accounts = catalog(database)
        reason = "identity_not_registered" if accounts else "empty_catalog"
        for row in accounts:
            if row["server"] == identity.server and row["login"] == identity.login:
                if row["mode"] == identity.mode:
                    return row
                reason = "mode_mismatch"
                break
        raise HTTPException(404, "unknown_account", headers={"X-TradingLab-Reason": reason})

    @app.post("/pair/{component}/{identity}")
    def pair(component: str, identity: str, request: Request):
        if not hmac.compare_digest(bearer(request), keys["admin"]):
            raise HTTPException(401)
        if not re.fullmatch("[a-f0-9]{32}", identity):
            raise HTTPException(400)
        if component == "relay":
            return {
                role: credential(keys["pairing"], identity, role)
                for role in ("account-state", "trading-events")
            }
        if component == "dashboard":
            return {key: keys[key] for key in ("CENTRAL_ACCOUNT_READ", "CENTRAL_TRADING_READ")}
        raise HTTPException(404)

    return app
