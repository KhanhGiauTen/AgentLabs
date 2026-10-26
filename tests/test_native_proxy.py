import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
import pytest

from scripts.native_proxy import Ledger, UsageStream, create_app, prepare


def test_admission_is_atomic_and_uncertainty_survives_restart(tmp_path):
    path = tmp_path / "budget.sqlite"
    ledger = Ledger(path, monthly=0.01, daily=0.01)

    def admit(_):
        try:
            return ledger.reserve("gpt-6-luna", 6000, False)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(admit, range(4)))
    assert len([v for v in claims if v]) == 1
    identity = next(v for v in claims if v)
    ledger.settle(identity)
    resumed = Ledger(path, monthly=0.01, daily=0.01)
    assert resumed.summary()["admitted_usd"] == 0.006
    assert resumed.summary()["uncertain_or_pending"] == 1
    with pytest.raises(ValueError, match="budget"):
        resumed.reserve("gpt-6-luna", 6000, False)


def test_usage_settlement_and_free_quota_include_unknown_calls(tmp_path):
    ledger = Ledger(tmp_path / "budget.sqlite", free_daily=2)
    identity = ledger.reserve("gpt-6.1-sol", 50000, False)
    ledger.settle(identity, (1000, 100))
    assert ledger.summary()["admitted_usd"] == 0.003
    ledger.reserve("example/model:free", 0, True)
    ledger.reserve("example/model:free", 0, True)
    with pytest.raises(ValueError, match="quota"):
        ledger.reserve("example/model:free", 0, True)
    ledger.settle(identity, (100000, 100000))  # no replay of settled rows
    assert ledger.summary()["admitted_usd"] == 0.003


def test_month_boundary_uses_vietnam_timezone_and_free_quota_utc(tmp_path):
    clock = [datetime(2026, 10, 31, 16, 59, tzinfo=timezone.utc)]
    ledger = Ledger(tmp_path / "budget.sqlite", clock=lambda: clock[0])
    ledger.reserve("gpt-6-luna", 10000, False)
    clock[0] = datetime(2026, 10, 31, 17, 1, tzinfo=timezone.utc)
    assert ledger.summary()["month"] == "2026-11"
    assert ledger.summary()["admitted_usd"] == 0
    assert ledger.periods()[2] == "2026-10-31"


def test_payload_caps_and_rejects_hidden_billing_paths():
    body = {
        "model": "gpt-6-luna",
        "input": "Hello",
        "max_output_tokens": 100000,
        "tools": [{"type": "function", "name": "lab_read"}],
    }
    payload, _, reserve, _ = prepare(body, "openai", "", "lean")
    assert payload["max_output_tokens"] == 4000
    assert payload["store"] is False and payload["service_tier"] == "default"
    assert reserve > 2000
    for extra in [
        {"previous_response_id": "hidden"},
        {"conversation": "hidden"},
        {"background": True},
        {"tools": [{"type": "web_search"}]},
        {"input": [{"type": "input_image", "image_url": "https://example.test"}]},
    ]:
        with pytest.raises(ValueError):
            prepare({**body, **extra}, "openai", "", "lean")
    with pytest.raises(ValueError, match="Paid model"):
        prepare(body, "openai", "example/model:free", "free")
    free, _, reserve, _ = prepare(
        {
            "model": "example/model:free",
            "models": ["paid"],
            "provider": {"allow_fallbacks": True},
            "stream": True,
        },
        "free",
        "example/model:free",
        "hybrid",
    )
    assert "models" not in free and free["provider"]["allow_fallbacks"] is False and reserve == 0
    assert free["stream_options"]["include_usage"]


def test_fragmented_sse_usage_and_missing_terminal_marker():
    tracker = UsageStream()
    raw = b'data: {"type":"response.completed","response":{"usage":{"input_tokens":111,"output_tokens":22}}}\r\n\r\n'
    for i in range(0, len(raw), 3):
        tracker.feed(raw[i : i + 3])
    assert tracker.finished and tracker.usage == (111, 22)
    free = UsageStream()
    free.feed(b'data: {"usage":{"prompt_tokens":50,"completion_tokens":10}}\n\n')
    assert free.usage == (50, 10) and not free.finished
    free.feed(b"data: [DONE]\n\n")
    assert free.finished


def test_proxy_forwards_tool_stream_and_settles_usage(tmp_path):
    observed = []

    def upstream(request):
        observed.append(json.loads(request.content))
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer synthetic-upstream-key"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"type":"response.output_item.added","item":{"type":"function_call","name":"lab_read"}}\n\ndata: {"type":"response.completed","response":{"usage":{"input_tokens":100,"output_tokens":20}}}\n\n',
        )

    app = create_app(
        tmp_path,
        {
            "AGENTLABS_MODEL_TOKEN": "synthetic-local-token",
            "OPENAI_API_KEY": "synthetic-upstream-key",
        },
        httpx.MockTransport(upstream),
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://local"
        ) as client:
            assert (await client.get("/budget")).status_code == 401
            headers = {"Authorization": "Bearer synthetic-local-token"}
            result = await client.post(
                "/openai/v1/responses",
                headers=headers,
                json={"model": "gpt-6-luna", "input": "Hello", "stream": True},
            )
            assert result.status_code == 200 and '"function_call"' in result.text
            budget = (await client.get("/budget", headers=headers)).json()
            assert budget["admitted_usd"] == 0.00002
            assert budget["uncertain_or_pending"] == 0

    asyncio.run(run())
    assert len(observed) == 1 and observed[0]["max_output_tokens"] == 4000


def test_missing_key_and_exhausted_budget_never_dispatch(tmp_path):
    calls = []
    app = create_app(
        tmp_path,
        {
            "AGENTLABS_MODEL_TOKEN": "local",
            "OPENAI_API_KEY": "key",
            "MONTHLY_BUDGET_USD": "0.000001",
        },
        httpx.MockTransport(lambda r: calls.append(r)),
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://local"
        ) as client:
            headers = {"Authorization": "Bearer local"}
            assert (
                await client.post(
                    "/openai/v1/responses",
                    headers=headers,
                    json={"model": "gpt-6-luna", "input": "Hello"},
                )
            ).status_code == 429
            assert (
                await client.post(
                    "/free/v1/chat/completions", headers=headers, json={"model": "x:free"}
                )
            ).status_code == 400

    asyncio.run(run())
    assert not calls and app.state.ledger.summary()["calls"] == 0


def test_incomplete_stream_keeps_conservative_reservation(tmp_path):
    app = create_app(
        tmp_path,
        {"AGENTLABS_MODEL_TOKEN": "local", "OPENAI_API_KEY": "key"},
        httpx.MockTransport(
            lambda r: httpx.Response(
                200, content=b'data: {"type":"response.output_text.delta","delta":"unfinished"}\n\n'
            )
        ),
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://local"
        ) as client:
            result = await client.post(
                "/openai/v1/responses",
                headers={"Authorization": "Bearer local"},
                json={"model": "gpt-6-luna", "input": "Hello", "stream": True},
            )
            assert result.status_code == 200

    asyncio.run(run())
    state = app.state.ledger.summary()
    assert state["uncertain_or_pending"] == 1 and state["admitted_usd"] > 0.002
