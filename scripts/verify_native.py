"""Operator integration fixture against a running native gateway; no model calls.

Creates labelled test sessions, exercises actual role tools and archives those
sessions afterwards. It does not claim to test LLM reasoning or native spawning.
"""

import asyncio
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import native_lab

import httpx


async def verify():
    env = native_lab.environment()
    node = native_lab.runtime.node_binary()
    cli = native_lab.cli_path()
    suffix = "integration-" + uuid.uuid4().hex[:8]
    roles = [
        "director",
        "writing",
        "review-novelty",
        "review-methods",
        "review-repro",
        "review-chair",
    ]
    keys = {role: f"agent:{role}:{suffix}" for role in roles}
    created = []

    def rpc(method, params):
        result = subprocess.run(
            [
                str(node),
                str(cli),
                "gateway",
                "call",
                method,
                "--params",
                json.dumps(params),
                "--json",
            ],
            env=env,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=100,
        )
        if result.returncode:
            raise RuntimeError(f"{method} failed: {result.stderr[-500:]}")
        return json.loads(result.stdout)

    checks = []
    try:
        for role in roles:
            entry = await asyncio.to_thread(
                rpc,
                "sessions.create",
                {
                    "agentId": role,
                    "key": keys[role],
                    "label": f"TEST native integration {suffix[-8:]} {role}",
                },
            )
            created.append(
                {"key": entry["key"], "agentId": role, "expectedSessionId": entry["sessionId"]}
            )
            keys[role] = entry["key"]
            print(f"Prepared host session: {role}", flush=True)
        headers = {"Authorization": "Bearer " + env["AGENTLABS_NATIVE_TOKEN"]}
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{native_lab.PORT}",
            headers=headers,
            timeout=40,
            trust_env=False,
        ) as client:

            async def call(role, tool, args, expected=200):
                result = await client.post(
                    "/tools/invoke",
                    json={"agentId": role, "sessionKey": keys[role], "tool": tool, "args": args},
                )
                if result.status_code != expected:
                    raise AssertionError(
                        f"{role}/{tool}: expected {expected}, got {result.status_code}"
                    )
                if expected == 200:
                    return result.json()["result"]["details"]

            p = await call(
                "director",
                "lab_begin",
                {
                    "topic": "INTEGRATION FIXTURE — not a scientific paper or model-generated result",
                    "recipe": "paper",
                },
            )
            p = await call(
                "writing",
                "lab_submit",
                {
                    "project_id": p["id"],
                    "task_token": p["assignments"]["writing"],
                    "content": "# TEST FIXTURE\nDRAFT — HUMAN REVIEW REQUIRED\nNo research evidence or experiments are asserted by this integration fixture.",
                },
            )
            owner = await call("director", "lab_inspect", {"project_id": p["id"]})
            assert p["phase"] == "review" and len(owner["assignments"]) == 3
            checks.append("real_host_phase_and_role_assignment")
            await call(
                "review-chair",
                "lab_decide",
                {
                    "project_id": p["id"],
                    "task_token": "not-assigned",
                    "manuscript_hash": p["manuscriptHash"],
                    "round": 0,
                    "action": "finish",
                    "rationale": "Premature Chair must be blocked.",
                    "verdict": "ready_for_human",
                },
                500,
            )
            checks.append("premature_chair_blocked")

            def report(role):
                return {
                    "project_id": p["id"],
                    "task_token": owner["assignments"][role],
                    "manuscript_hash": p["manuscriptHash"],
                    "round": 0,
                    "verdict": "hold",
                    "score": 1,
                    "confidence": 1,
                    "rationale": "This is an integration fixture with no scientific evidence.",
                    "evidence_refs": ["manuscript.md"],
                    "blocking_issues": ["No scientific evidence in fixture"],
                    "recommended_fixes": [
                        "Run a separate scientific pilot with real sources and data"
                    ],
                }

            await call(
                "review-novelty",
                "lab_review",
                {**report("review-novelty"), "manuscript_hash": "0" * 64},
                500,
            )
            await call("review-novelty", "lab_review", report("review-novelty"))
            peer = await call(
                "review-methods",
                "lab_inspect",
                {"project_id": p["id"], "task_token": owner["assignments"]["review-methods"]},
            )
            assert "reviews" not in peer and "history" not in peer and "grants" not in peer
            checks.append("peer_reviews_sealed_in_real_host")
            await asyncio.gather(
                *(
                    call(role, "lab_review", report(role))
                    for role in ["review-methods", "review-repro"]
                )
            )
            board = await call("director", "lab_inspect", {"project_id": p["id"]})
            assert board["phase"] == "chair" and board["reviewCount"] == 3
            checks.append("concurrent_reviews_durable_cas_merge")
            await call("review-novelty", "lab_review", report("review-novelty"), 500)
            finished = await call(
                "review-chair",
                "lab_decide",
                {
                    "project_id": p["id"],
                    "task_token": board["assignments"]["review-chair"],
                    "manuscript_hash": p["manuscriptHash"],
                    "round": 0,
                    "action": "finish",
                    "rationale": "All three fixture reviews correctly identify missing scientific evidence.",
                    "verdict": "ready_for_human",
                },
            )
            assert finished["phase"] == "complete" and finished["decision"]["verdict"] == "hold"
            checks.append("chair_barrier_and_hold_verdict")
            await call(
                "director", "lab_execute", {"project_id": p["id"], "code_hash": "0" * 64}, 404
            )
            checks.append("execution_http_surface_denied")
            budget = await call("director", "lab_budget", {})
            repos = await call("director", "lab_repo_list", {})
            assert "admitted_usd" in budget and repos["mode"] == "read_only"
            checks.append("budget_and_repo_tools_loaded")
        proof = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
            "project_id": p["id"],
            "scope": "operator HTTP/CLI integration fixtures, no LLM inference, no sessions_spawn, no Docker execution or approval UI test",
        }
        (native_lab.STATE / "native-verification.json").write_text(
            json.dumps(proof, indent=2), encoding="utf-8"
        )
        print(json.dumps(proof, indent=2), flush=True)
    finally:
        if created:
            result = await asyncio.to_thread(
                rpc, "sessions.patchMany", {"targets": created, "patch": {"archived": True}}
            )
            if not all(item["ok"] for item in result["outcomes"]):
                raise RuntimeError("Some integration fixture sessions could not be archived")
            print("Integration fixture sessions archived (recoverable).", flush=True)


if __name__ == "__main__":
    asyncio.run(verify())
