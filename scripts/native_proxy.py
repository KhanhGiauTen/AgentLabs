"""Loopback model transport with durable, conservative pre-dispatch admission.

This proxy forwards model protocols, including tool calls; OpenClaw owns the loop.
No retries, provider tools, hidden server history or automatic model fallback.
"""

import asyncio
import hashlib
import hmac
import json
import math
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

RATES = {"gpt-6-luna": (0.10, 0.50), "gpt-6.1-sol": (2.0, 10.0)}
MAX_BODY = 256000
MAX_OUTPUT = 4000
LOCAL_ZONE = timezone(timedelta(hours=7))


class Ledger:
    def __init__(self, path, monthly=15, daily=1, free_daily=30, clock=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.monthly = self.money(monthly)
        self.daily = self.money(daily)
        self.free_daily = int(free_daily)
        if not (self.monthly > 0 and self.daily > 0 and 1 <= self.free_daily <= 1000):
            raise ValueError("Budget and free quota must be positive")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY, model TEXT NOT NULL, month TEXT NOT NULL,
                day TEXT NOT NULL, free_day TEXT NOT NULL, is_free INTEGER NOT NULL,
                reserved INTEGER NOT NULL, charged INTEGER NOT NULL,
                status TEXT NOT NULL, input_tokens INTEGER, output_tokens INTEGER)""")

    @staticmethod
    def money(value):
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError("Invalid budget")
        return math.ceil(number * 1_000_000)

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def periods(self):
        now = self.clock()
        return (
            now.astimezone(LOCAL_ZONE).strftime("%Y-%m"),
            now.astimezone(LOCAL_ZONE).strftime("%Y-%m-%d"),
            now.astimezone(timezone.utc).strftime("%Y-%m-%d"),
        )

    def reserve(self, model, amount, is_free):
        month, day, free_day = self.periods()
        identity = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            used_month = db.execute(
                "SELECT COALESCE(SUM(charged),0) FROM calls WHERE month=?", (month,)
            ).fetchone()[0]
            used_day = db.execute(
                "SELECT COALESCE(SUM(charged),0) FROM calls WHERE day=?", (day,)
            ).fetchone()[0]
            free_count = db.execute(
                "SELECT COUNT(*) FROM calls WHERE is_free=1 AND free_day=?", (free_day,)
            ).fetchone()[0]
            if used_month + amount > self.monthly or used_day + amount > self.daily:
                raise ValueError(
                    "Native estimated budget reached; review local ledger before increasing limits"
                )
            if is_free and free_count >= self.free_daily:
                raise ValueError("Native free-model daily quota reached; no paid fallback")
            db.execute(
                "INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identity,
                    model,
                    month,
                    day,
                    free_day,
                    int(is_free),
                    amount,
                    amount,
                    "reserved",
                    None,
                    None,
                ),
            )
        return identity

    def settle(self, identity, usage=None, status="uncertain"):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT model,is_free,reserved,status FROM calls WHERE id=?", (identity,)
            ).fetchone()
            if not row or row[3] != "reserved":
                return  # A settled or uncertain admission is never silently replayed.
            if usage is None:
                db.execute("UPDATE calls SET status=? WHERE id=?", (status, identity))
                return
            input_tokens, output_tokens = usage
            charged = (
                0
                if row[1]
                else math.ceil(input_tokens * RATES[row[0]][0] + output_tokens * RATES[row[0]][1])
            )
            # Rates are USD/1M, so the expression above is already in micro-USD.
            db.execute(
                "UPDATE calls SET charged=?,status=?,input_tokens=?,output_tokens=? WHERE id=?",
                (
                    charged,
                    "settled" if charged <= row[2] else "estimate_exceeded",
                    input_tokens,
                    output_tokens,
                    identity,
                ),
            )

    def summary(self):
        month, day, free_day = self.periods()
        with self.connect() as db:
            used = db.execute(
                "SELECT COALESCE(SUM(charged),0),COUNT(*),SUM(CASE WHEN status IN ('reserved','uncertain') THEN 1 ELSE 0 END) FROM calls WHERE month=?",
                (month,),
            ).fetchone()
            daily = db.execute(
                "SELECT COALESCE(SUM(charged),0) FROM calls WHERE day=?", (day,)
            ).fetchone()[0]
            free = db.execute(
                "SELECT COUNT(*) FROM calls WHERE is_free=1 AND free_day=?", (free_day,)
            ).fetchone()[0]
        return {
            "month": month,
            "timezone": "UTC+7",
            "admitted_usd": used[0] / 1e6,
            "monthly_limit_usd": self.monthly / 1e6,
            "daily_admitted_usd": daily / 1e6,
            "daily_limit_usd": self.daily / 1e6,
            "calls": used[1],
            "uncertain_or_pending": used[2] or 0,
            "free_calls_today_utc": free,
            "free_daily_limit": self.free_daily,
            "scope": "native proxy only; estimated billing, excludes other apps/accounts",
        }


def prepare(body, route, free_model, mode):
    if not isinstance(body, dict):
        raise ValueError("Expected a JSON object")
    model = body.get("model", "")
    free = route == "free"
    if free:
        if (
            mode not in {"free", "hybrid"}
            or not free_model.endswith(":free")
            or model != free_model
        ):
            raise ValueError("Only the configured :free model is permitted")
    elif mode == "free" or model not in RATES:
        raise ValueError("Paid model is not permitted by this profile")
    if body.get("previous_response_id") or body.get("conversation") or body.get("background"):
        raise ValueError(
            "Hidden server history/background work is not permitted through this budget proxy"
        )
    if any(tool.get("type") != "function" for tool in body.get("tools", [])):
        raise ValueError("Only locally executed function tools are permitted")
    denied_types = {
        "input_image",
        "image_url",
        "input_audio",
        "audio",
        "input_file",
        "file",
        "video",
        "input_video",
    }

    def check(value):
        if isinstance(value, dict):
            if value.get("type") in denied_types:
                raise ValueError("Text-only budget profile; import bounded text with local tools")
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    check(body)
    payload = dict(body)
    for name in [
        "models",
        "route",
        "provider",
        "max_tokens",
        "max_completion_tokens",
        "max_output_tokens",
        "service_tier",
        "prompt_cache_retention",
    ]:
        payload.pop(name, None)
    requested = body.get(
        "max_output_tokens", body.get("max_completion_tokens", body.get("max_tokens", MAX_OUTPUT))
    )
    if not isinstance(requested, int) or isinstance(requested, bool) or requested < 1:
        raise ValueError("Invalid output token limit")
    ceiling = min(requested, MAX_OUTPUT)
    if free:
        payload["max_tokens"] = ceiling
        payload["provider"] = {"allow_fallbacks": False, "require_parameters": True}
        if payload.get("stream"):
            payload["stream_options"] = {"include_usage": True}
    else:
        payload["max_output_tokens"] = ceiling
        payload["store"] = False
        payload["service_tier"] = "default"
        payload["prompt_cache_retention"] = "in_memory"
    wire = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(wire) > MAX_BODY:
        raise ValueError("Model context too large for the bounded native profile")
    amount = (
        0 if free else math.ceil((len(wire) + 2048) * RATES[model][0] + ceiling * RATES[model][1])
    )
    return payload, wire, amount, free


def token_usage(data):
    usage = data.get("usage") or data.get("response", {}).get("usage")
    if not isinstance(usage, dict):
        return None
    values = (
        usage.get("input_tokens", usage.get("prompt_tokens")),
        usage.get("output_tokens", usage.get("completion_tokens")),
    )
    if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in values):
        return None
    return values


class UsageStream:
    def __init__(self):
        self.buffer = b""
        self.usage = None
        self.finished = False

    def feed(self, chunk):
        self.buffer += chunk
        if len(self.buffer) > 2_000_000:
            raise ValueError("Upstream SSE event exceeded bounded parser capacity")
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            if not line.startswith(b"data:"):
                continue
            raw = line[5:].strip()
            if raw == b"[DONE]":
                self.finished = True
                continue
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            self.usage = token_usage(data) or self.usage
            if data.get("type") in {"response.completed", "response.incomplete", "response.failed"}:
                self.finished = True


def create_app(state=None, env=None, transport=None):
    values = dict(os.environ if env is None else env)
    state = Path(state or values["OPENCLAW_STATE_DIR"])
    token = values["AGENTLABS_MODEL_TOKEN"]
    mode = values.get("AGENTLABS_NATIVE_MODE", "lean")
    ledger = Ledger(
        state / "model-budget.sqlite",
        values.get("MONTHLY_BUDGET_USD", 15),
        values.get("NATIVE_DAILY_BUDGET_USD", 1),
        values.get("NATIVE_FREE_DAILY_CALLS", 30),
    )
    free_model = values.get("GATEWAY_MODEL", "").removeprefix("openrouter/")
    keys = {"openai": values.get("OPENAI_API_KEY", ""), "free": values.get("GATEWAY_API_KEY", "")}
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(150, connect=15),
        follow_redirects=False,
        transport=transport,
        trust_env=False,
    )

    @asynccontextmanager
    async def lifespan(app):
        yield
        await client.aclose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ledger = ledger

    def authenticate(request):
        actual = request.headers.get("authorization", "")
        if not hmac.compare_digest(actual.encode(), ("Bearer " + token).encode()):
            raise HTTPException(401, "Private model proxy token required")

    @app.get("/health")
    async def health(request: Request):
        authenticate(request)
        return {
            "ok": True,
            "mode": mode,
            "instance": hashlib.sha256(token.encode()).hexdigest()[:12],
            "paid_credential_configured": bool(keys["openai"]),
            "free_credential_configured": bool(keys["free"]),
        }

    @app.get("/budget")
    async def budget(request: Request):
        authenticate(request)
        return await asyncio.to_thread(ledger.summary)

    @app.post("/openai/v1/responses")
    @app.post("/free/v1/chat/completions")
    async def forward(request: Request):
        authenticate(request)
        route = "free" if request.url.path.startswith("/free/") else "openai"
        if not keys[route]:
            raise HTTPException(
                400,
                f"Configure {'GATEWAY_API_KEY' if route == 'free' else 'OPENAI_API_KEY'} in local .env and restart AgentLabs",
            )
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BODY:
                raise HTTPException(413, "Native model request too large")
        try:
            payload, wire, amount, is_free = prepare(json.loads(raw), route, free_model, mode)
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        try:
            identity = await asyncio.to_thread(ledger.reserve, payload["model"], amount, is_free)
        except ValueError as exc:
            raise HTTPException(429, str(exc)) from exc
        url = (
            "https://openrouter.ai/api/v1/chat/completions"
            if is_free
            else "https://api.openai.com/v1/responses"
        )
        try:
            upstream = await client.send(
                client.build_request(
                    "POST",
                    url,
                    content=wire,
                    headers={
                        "Authorization": "Bearer " + keys[route],
                        "Content-Type": "application/json",
                        "Accept": (
                            "text/event-stream" if payload.get("stream") else "application/json"
                        ),
                    },
                ),
                stream=True,
            )
        except BaseException:
            await asyncio.shield(asyncio.to_thread(ledger.settle, identity))
            raise HTTPException(
                502, "Upstream transport failed; reservation retained; no automatic retry"
            )
        if upstream.status_code != 200:
            await upstream.aclose()
            await asyncio.to_thread(ledger.settle, identity)
            return JSONResponse(
                {
                    "error": {
                        "message": f"Upstream HTTP {upstream.status_code}; reservation retained; inspect provider account",
                        "type": "native_upstream_error",
                    }
                },
                status_code=upstream.status_code if upstream.status_code >= 400 else 502,
            )
        if payload.get("stream"):

            async def stream():
                tracker = UsageStream()
                settled = False
                try:
                    async for chunk in upstream.aiter_bytes():
                        tracker.feed(chunk)
                        yield chunk
                    if tracker.finished and tracker.usage is not None:
                        await asyncio.shield(
                            asyncio.to_thread(ledger.settle, identity, tracker.usage)
                        )
                        settled = True
                finally:
                    await upstream.aclose()
                    if not settled:
                        await asyncio.shield(asyncio.to_thread(ledger.settle, identity))

            return StreamingResponse(
                stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        try:
            output = bytearray()
            async for chunk in upstream.aiter_bytes():
                output.extend(chunk)
                if len(output) > 4_000_000:
                    raise ValueError("Upstream response exceeded limit")
            data = json.loads(output)
            usage = token_usage(data)
            await asyncio.to_thread(ledger.settle, identity, usage)
            return Response(bytes(output), media_type="application/json")
        finally:
            await upstream.aclose()
            await asyncio.shield(asyncio.to_thread(ledger.settle, identity))

    return app
