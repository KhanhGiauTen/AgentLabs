import asyncio
import base64
import io
import json
import time
import zipfile
from functools import partial
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from backend.catalog import ROLES, REVIEWERS
from backend.documents import ingest, search_documents
from backend.providers import run_agent, readiness
from backend.quality import audit
from backend.store import Store
from backend.tools import call_tool, execute_sandbox
from backend.workflow import build_graph, build_context
from backend.reviews import submit_review, board_decision
import backend.app as appmod
import backend.providers as providers
import backend.workflow as workflow


def seed(store, mode="demo"):
    rid = "a" * 32
    store.save(
        {
            "id": rid,
            "topic": "Test reproducible AI research",
            "mode": mode,
            "budget": 5,
            "outputs": {},
            "sources": [],
            "documents": [],
            "status": "draft",
        }
    )
    return rid


def test_atomic_budget_reserves(tmp_path):
    store = Store(tmp_path)
    rid = seed(store)
    reservation = store.reserve(rid, "gpt-6.1-sol", 0.7, 1, 1)
    with pytest.raises(ValueError, match="Budget cap"):
        store.reserve(rid, "gpt-6.1-sol", 0.4, 1, 1)
    store.settle(reservation, 100, 50, 0.1)
    assert store.spend() == pytest.approx(0.1)
    reservation = store.reserve(rid, "gpt-6.1-sol", 0.2, 1, 1)
    store.uncertain(reservation)
    assert store.spend() == pytest.approx(0.3)


def test_parallel_reservations_do_not_overspend(tmp_path):
    store = Store(tmp_path)
    rid = seed(store)

    def reserve(_):
        try:
            store.reserve(rid, "test", 0.1, 0.25, 0.25)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=4) as executor:
        accepted = list(executor.map(reserve, range(4)))
    assert accepted.count(True) == 2
    assert store.spend() == pytest.approx(0.2)


def test_artifacts_confined_to_run(tmp_path):
    store = Store(tmp_path)
    rid = seed(store)
    for name in ["../.env", ".env", "a/b.txt", "..", "C:\\secret", "a:stream"]:
        with pytest.raises(ValueError):
            store.artifact_path(rid, name)
    store.write(rid, "note.md", "test")
    assert store.artifacts(rid) == [{"name": "note.md", "bytes": 4}]


@pytest.mark.asyncio
async def test_tool_permissions_and_no_host_execution(tmp_path):
    store = Store(tmp_path)
    rid = seed(store)
    with pytest.raises(ValueError, match="not available"):
        await call_tool(store, rid, "save_experiment", {"code": "print(1)"}, ["read_artifact"])
    sentinel = tmp_path / "MUST_NOT_EXIST"
    code = f'from pathlib import Path\nPath({str(sentinel)!r}).write_text("unsafe")\n'
    result = await call_tool(store, rid, "save_experiment", {"code": code}, ["save_experiment"])
    assert result["staged"]
    assert not sentinel.exists()
    with pytest.raises(ValueError, match="changed since approval"):
        await execute_sandbox(store, rid, "unused", "wrong-hash")


def test_documents_keep_provenance(tmp_path):
    store = Store(tmp_path)
    rid = seed(store)
    doc = ingest(
        store,
        rid,
        "method.txt",
        base64.b64encode(
            b"Dataset leakage invalidates the evaluation. Separate train and test."
        ).decode(),
    )
    result = search_documents(store, rid, "dataset leakage")
    assert result["chunks"][0]["page"] == 1
    assert result["chunks"][0]["id"].startswith(doc["id"])
    assert "leakage" in result["chunks"][0]["text"]
    assert len(doc["sha256"]) == 64


def test_quality_audit_detects_unknown_doi(tmp_path):
    store = Store(tmp_path)
    rid = seed(store)
    store.update(rid, outputs={"writing": "DRAFT\nUnverified source https://doi.org/10.1234/fake"})
    result = audit(store, rid)
    assert result["checks"][0]["status"] == "fail"
    assert result["ready_to_submit"] is False


def test_dataset_import_keeps_hash_and_sandbox_path(tmp_path):
    store = Store(tmp_path)
    rid = seed(store)
    dataset = ingest(store, rid, "small.csv", base64.b64encode(b"x,y\n1,2\n2,4\n").decode())
    assert dataset["sandbox_path"].startswith("/inputs/input-")
    assert store.artifact_path(rid, dataset["artifact"]).read_text() == "x,y\n1,2\n2,4\n"
    assert store.get(rid)["datasets"][0]["sha256"] == dataset["sha256"]


@pytest.mark.asyncio
async def test_checkpoint_restart_resume_and_both_gates(tmp_path):
    store = Store(tmp_path / "data")
    rid = seed(store)
    config = {"configurable": {"thread_id": rid}}
    db = str(tmp_path / "checkpoints.sqlite")
    opts = lambda: {"monthly_budget": 15, "sandbox_image": "unused"}
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        graph = build_graph(store, saver, opts)
        result = await graph.ainvoke({"run_id": rid, "outputs": {}, "execution": {}}, config)
        assert result["__interrupt__"][0].value["kind"] == "experiment"
        assert len(result["outputs"]) == 4
        assert not store.get(rid).get("execution")
    # Construct new graph/checkpointer as if the backend restarted.
    async with AsyncSqliteSaver.from_conn_string(db) as saver:
        graph = build_graph(store, saver, opts)
        result = await graph.ainvoke(Command(resume={"action": "skip"}), config)
        assert result["__interrupt__"][0].value["kind"] == "draft"
        assert result["execution"]["status"] == "skipped"
        assert len(result["outputs"]) == len(ROLES)
        assert all(x in store.get(rid)["reviews"] for x in REVIEWERS)
        assert len(store.get(rid)["reviews"]) == 4
        events = store.events(rid)
        starts = [
            e["seq"]
            for e in events
            if e["kind"] == "stage_start" and e["data"]["role"] in REVIEWERS
        ]
        ends = [
            e["seq"]
            for e in events
            if e["kind"] == "stage_complete" and e["data"]["role"] in REVIEWERS
        ]
        assert max(starts) < min(
            ends
        ), "Three independent reviewer nodes should fan out before joining at Chair"
        assert store.get(rid)["quality"]["ready_to_submit"] is False
        await graph.ainvoke(Command(resume={"action": "acknowledge"}), config)
        assert not (await graph.aget_state(config)).next


@pytest.mark.asyncio
async def test_openai_real_adapter_tool_roundtrip(tmp_path, monkeypatch):
    store = Store(tmp_path)
    rid = seed(store, "lean")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "c1",
                            "name": "read_artifact",
                            "arguments": '{"name":"context.md"}',
                        }
                    ],
                    "usage": {"input_tokens": 100, "output_tokens": 10},
                },
            )
        assert any(
            x.get("type") == "function_call_output" and "known context" in x["output"]
            for x in body["input"]
        )
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Grounded response."}],
                    }
                ],
                "usage": {"input_tokens": 150, "output_tokens": 20},
            },
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        providers.httpx,
        "AsyncClient",
        partial(original_client, transport=httpx.MockTransport(handler)),
    )
    store.write(rid, "context.md", "known context")
    result = await run_agent(store, rid, ROLES[0], "lean", "question", 15)
    assert result == "Grounded response."
    assert len(calls) == 2
    assert calls[0]["store"] is False
    assert store.spend(rid) > 0


@pytest.mark.asyncio
async def test_quota_error_never_falls_back(tmp_path, monkeypatch):
    store = Store(tmp_path)
    rid = seed(store, "lean")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(429, json={"error": "quota exceeded"})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        providers.httpx,
        "AsyncClient",
        partial(original_client, transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ValueError, match="429"):
        await run_agent(store, rid, ROLES[0], "lean", "question", 15)
    assert seen == ["https://api.openai.com/v1/responses"]
    assert store.usage()[0]["status"] == "uncertain"


@pytest.mark.asyncio
async def test_openclaw_bridge_contract(tmp_path, monkeypatch):
    store = Store(tmp_path)
    rid = seed(store, "openclaw")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "synthetic-token")

    def handler(request):
        assert request.url.host == "127.0.0.1"
        assert request.headers["x-openclaw-model"] == "openai/gpt-6.1-sol"
        assert json.loads(request.content)["model"] == "openclaw/research"
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Test bridge."}],
                    }
                ],
                "usage": {"input_tokens": 50, "output_tokens": 20},
            },
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        providers.httpx,
        "AsyncClient",
        partial(original_client, transport=httpx.MockTransport(handler)),
    )
    result = await run_agent(store, rid, ROLES[2], "openclaw", "protocol", 15)
    assert result == "Test bridge."
    assert store.spend(rid) >= 0.1


@pytest.mark.asyncio
async def test_claude_review_uses_auto_tool_choice_and_persists_scorecard(tmp_path, monkeypatch):
    store = Store(tmp_path)
    rid = seed(store, "claude")
    store.write(rid, "manuscript.md", "DRAFT test manuscript")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-key")
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body["tool_choice"] == {"type": "auto"}
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "submit_review",
                            "input": review_args(),
                        }
                    ],
                    "usage": {"input_tokens": 100, "output_tokens": 20},
                },
            )
        assert body["messages"][-1]["content"][0]["type"] == "tool_result"
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "Review submitted."}],
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        providers.httpx, "AsyncClient", partial(original, transport=httpx.MockTransport(handler))
    )
    role = next(r for r in ROLES if r["id"] == REVIEWERS[0])
    assert await run_agent(store, rid, role, "claude", "context", 15) == "Review submitted."
    assert len(calls) == 2
    assert REVIEWERS[0] in store.get(rid)["reviews"]


@pytest.mark.asyncio
async def test_review_cannot_finish_without_submit_tool(tmp_path, monkeypatch):
    store = Store(tmp_path)
    rid = seed(store, "lean")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")

    def handler(request):
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "I reviewed everything, trust me."}
                        ],
                    }
                ],
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        providers.httpx, "AsyncClient", partial(original, transport=httpx.MockTransport(handler))
    )
    role = next(r for r in ROLES if r["id"] == REVIEWERS[0])
    with pytest.raises(ValueError, match="submit_review"):
        await run_agent(store, rid, role, "lean", "context", 15)
    assert not store.get(rid).get("reviews")


def test_reject_nonfree_gateway(monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEY", "synthetic-key")
    monkeypatch.setenv("GATEWAY_MODEL", "a-paid-model")
    with pytest.raises(ValueError, match=":free"):
        readiness("free")


def review_args(action="no_change"):
    return {
        "verdict": "hold",
        "action": action,
        "score": 2,
        "confidence": "low",
        "rationale": "Experimental evidence is not complete for the current manuscript.",
        "evidence_refs": ["manuscript.md"],
        "blocking_issues": ["Evidence missing"],
        "recommended_fixes": ["Verify experimental results"],
    }


@pytest.mark.asyncio
async def test_sealed_reviewers_cannot_read_peers(tmp_path):
    store = Store(tmp_path)
    rid = seed(store)
    store.write(rid, "manuscript.md", "DRAFT content")
    submit_review(store, rid, REVIEWERS[0], review_args())
    with pytest.raises(ValueError, match="Sealed reviewer"):
        await call_tool(
            store,
            rid,
            "read_artifact",
            {"name": "review_novelty.json"},
            ["read_artifact"],
            role_id=REVIEWERS[1],
        )
    run = store.get(rid)
    context = json.loads(
        build_context(
            store,
            run,
            {"outputs": {"writing": "DRAFT", REVIEWERS[0]: "PEER_SECRET_REVIEW"}},
            next(r for r in ROLES if r["id"] == REVIEWERS[1]),
        )
    )
    assert "PEER_SECRET_REVIEW" not in json.dumps(context)
    assert "sealed_reviews" not in context
    assert not any(a["name"].startswith("review") for a in context["available_artifacts"])


def test_board_waits_for_three_and_enforces_iteration_cap(tmp_path):
    store = Store(tmp_path)
    rid = seed(store)
    store.write(rid, "manuscript.md", "DRAFT content")
    with pytest.raises(ValueError, match="all three"):
        submit_review(store, rid, "review", review_args())
    for role in REVIEWERS:
        submit_review(store, rid, role, review_args())
    submit_review(store, rid, "review", review_args("revise_manuscript"))
    assert board_decision(store, rid, 1)["action"] == "revise_manuscript"
    store.update(rid, revision_count=1)
    assert board_decision(store, rid, 1)["action"] == "no_change"


def test_review_rejects_invented_evidence_and_false_readiness(tmp_path):
    store = Store(tmp_path)
    rid = seed(store)
    store.write(rid, "manuscript.md", "DRAFT content")
    args = review_args()
    args["evidence_refs"] = ["doi:10.1234/invented"]
    with pytest.raises(ValueError, match="Unregistered"):
        submit_review(store, rid, REVIEWERS[0], args)
    args = review_args()
    args["verdict"] = "ready_for_human"
    result = submit_review(store, rid, REVIEWERS[0], args)
    assert result["review"]["verdict"] == "hold"


@pytest.mark.asyncio
@pytest.mark.parametrize("chair_action", ["revise_manuscript", "new_experiment"])
async def test_agentic_revisions_are_bounded_and_reexecution_is_gated(
    tmp_path, monkeypatch, chair_action
):
    store = Store(tmp_path / "data")
    rid = seed(store, "lean")
    store.update(rid, max_revisions=1)
    counts = {}

    async def agent(store, rid, role, mode, context, monthly_budget):
        stage = role["id"]
        counts[stage] = counts.get(stage, 0) + 1
        if stage == "experiment":
            store.write(rid, "experiment.py", 'print("test code, not executed")')
        if stage in [*REVIEWERS, "review"]:
            action = (
                chair_action
                if stage == "review" and store.get(rid).get("revision_count", 0) == 0
                else "no_change"
            )
            submit_review(store, rid, stage, review_args(action))
        return f"DRAFT {stage} iteration {counts[stage]}"

    monkeypatch.setattr(workflow, "run_agent", agent)
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(store, saver, lambda: {"monthly_budget": 15, "sandbox_image": "unused"})
        cfg = {"configurable": {"thread_id": rid}, "recursion_limit": 65}
        await graph.ainvoke({"run_id": rid, "outputs": {}, "execution": {}}, cfg)
        result = await graph.ainvoke(Command(resume={"action": "skip"}), cfg)
        if chair_action == "new_experiment":
            assert result["__interrupt__"][0].value["kind"] == "rework"
            assert counts["experiment"] == 1
            result = await graph.ainvoke(Command(resume={"action": "rework"}), cfg)
            assert result["__interrupt__"][0].value["kind"] == "experiment"
            assert counts["experiment"] == 2
            assert result["execution"]["status"] == "not_run"
            assert store.artifact_path(rid, "archived-r0-experiment.py").exists()
            result = await graph.ainvoke(Command(resume={"action": "skip"}), cfg)
        assert result["__interrupt__"][0].value["kind"] == "draft"
        assert result["revision_count"] == 1
        assert counts["writing"] == 2
        assert counts["review"] == 2
        assert store.get(rid)["board"]["action"] == "no_change"
        assert store.artifact_path(rid, "review-round0.json").exists()
        assert store.artifact_path(rid, "review-round1.json").exists()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "store", Store(tmp_path / "api"))
    monkeypatch.setattr(appmod, "DATA", tmp_path / "api")
    monkeypatch.setattr(appmod, "tasks", {})
    with TestClient(appmod.app) as c:
        yield c


def wait_for(client, rid, status):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = client.get("/api/runs/" + rid).json()
        if run["status"] == status:
            return run
        if run["status"] == "error":
            raise AssertionError(run)
        time.sleep(0.02)
    raise AssertionError("Workflow did not reach " + status)


def test_api_workflow_export_and_approval(client):
    headers = {"X-Studio-Client": "local-ui"}
    response = client.post(
        "/api/runs", headers=headers, json={"topic": "Research test workflow", "mode": "demo"}
    )
    assert response.status_code == 201
    rid = response.json()["id"]
    run = wait_for(client, rid, "waiting")
    assert run["gate"]["kind"] == "experiment"
    bad = client.post(
        f"/api/runs/{rid}/decision", headers=headers, json={"action": "run", "sha256": "invalid"}
    )
    assert bad.status_code == 409
    response = client.post(f"/api/runs/{rid}/decision", headers=headers, json={"action": "skip"})
    assert response.status_code == 200
    # Allow the async task to enter running before waiting for the second gate.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = client.get("/api/runs/" + rid).json()
        if run.get("gate", {}).get("kind") == "draft" if run.get("gate") else False:
            break
        time.sleep(0.02)
    assert run["gate"]["kind"] == "draft"
    assert run["quality"]["ready_to_submit"] is False
    response = client.get(f"/api/runs/{rid}/export")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        assert "manuscript.md" in z.namelist()
        assert "quality-gates.json" in z.namelist()
        assert not any("env" in x for x in z.namelist())
    client.post(f"/api/runs/{rid}/decision", headers=headers, json={"action": "acknowledge"})
    assert wait_for(client, rid, "completed")["spend"] == 0


def test_local_api_blocks_cross_origin_and_missing_header(client):
    assert client.post("/api/runs", json={"topic": "unsafe request"}).status_code == 403
    assert client.get("/api/config", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/config", headers={"Host": "evil.example"}).status_code == 403


def test_draft_upload_before_start_and_followup_copies_docs(client):
    headers = {"X-Studio-Client": "local-ui"}
    rid = client.post(
        "/api/runs",
        headers=headers,
        json={"topic": "Research with local documents", "autostart": False},
    ).json()["id"]
    assert client.get("/api/runs/" + rid).json()["status"] == "draft"
    response = client.post(
        f"/api/runs/{rid}/documents",
        headers=headers,
        json={
            "name": "test.txt",
            "content_base64": base64.b64encode(b"We test document grounding.").decode(),
        },
    )
    assert response.status_code == 200
    parent = client.get("/api/runs/" + rid).json()
    new = client.post(
        "/api/runs",
        headers=headers,
        json={"topic": "Continue document research", "parent_id": rid, "autostart": False},
    ).json()
    child = client.get("/api/runs/" + new["id"]).json()
    assert child["documents"] == parent["documents"]
    assert child["documents"][0]["artifact"] in [a["name"] for a in child["artifacts"]]
