import asyncio
import hashlib
import json
from typing import TypedDict, Annotated

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from .catalog import ROLES, REVIEWERS
from .providers import run_agent, route
from .tools import execute_sandbox
from .quality import audit
from .reviews import submit_review, board_decision


def merge_outputs(current, updates):
    result = dict(current or {})
    for key, value in (updates or {}).items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = value
    return result


class ResearchState(TypedDict, total=False):
    run_id: str
    outputs: Annotated[dict, merge_outputs]
    execution: dict
    approval: dict
    revision_count: int
    next_action: str
    rework_approved: bool


DEMO_CODE = """# DEMO SMOKE TEST: synthetic observations, not research evidence.
import json, random, statistics
seeds = [17, 42, 93]
scores = []
for seed in seeds:
    rng = random.Random(seed)
    points = [(rng.uniform(-1, 1), rng.gauss(0, .1)) for _ in range(120)]
    # Fixed baseline y_hat=2*x on synthetic y=2*x+noise.
    mse = statistics.mean(noise**2 for x, noise in points)
    scores.append({"seed": seed, "n": len(points), "mse": mse})
result = {"kind": "synthetic smoke test", "dataset": "generated Gaussian noise; NOT user's research dataset", "baseline": "fixed y_hat=2*x", "splits": "no training or test split; smoke test only", "runs": scores, "mean_mse": statistics.mean(s["mse"] for s in scores), "research_claims_supported": False}
with open("metrics.json", "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)
print(json.dumps(result))
"""


def demo_text(stage, run, execution):
    topic = run["topic"]
    heading = (
        "> **DEMO · Nội dung theo kịch bản, không phải output model. Không có API charge.**\n\n"
    )
    sources = run.get("sources", [])
    if stage in REVIEWERS:
        role = next(r for r in ROLES if r["id"] == stage)
        return (
            heading
            + f"## {role['name']} · sealed review\n\n**Verdict: HOLD · confidence low**\n\nChưa có bằng chứng nghiên cứu để đánh giá đầy đủ.\n\n"
            + role["brief"]
            + "\n\nĐã lưu scorecard JSON riêng; chưa đọc peer reviews."
        )
    texts = {
        "intake": f"## Research brief\n\n**Câu hỏi của bạn:** {topic}\n\n- Chuyển câu hỏi thành một giả thuyết có thể bác bỏ.\n- Chốt dataset, baseline, metric chính và giới hạn CPU/GPU.\n- Mục tiêu lượt đầu: protocol nhỏ và tái lập được.\n\nCần nhà nghiên cứu xác nhận phạm vi trước khi dùng làm kế hoạch thật.",
        "literature": "## Evidence map\n\n"
        + (
            "\n".join(f"- [{p['title']}]({p['url']}) — {p['evidence']}" for p in sources)
            if sources
            else "Chưa có nguồn được truy xuất. Dùng tab **Tài liệu** để tìm Crossref/arXiv thật. Demo không tự tạo citation."
        )
        + "\n\nĐọc full text và xác minh mức độ liên quan trước khi kết luận research gap.",
        "methods": "## Experiment protocol · checklist\n\n1. Tái lập baseline trước khi sửa phương pháp.\n2. Tách train/validation/test, kiểm tra trùng lặp và leakage.\n3. Chạy nhiều seed, báo mean và độ biến thiên.\n4. Ablation từng thành phần với cùng compute budget.\n5. Lưu dataset/version, dependency, cấu hình và raw metrics.\n\nDemo chỉ tạo smoke test tổng hợp để thử đường chạy Docker; chưa triển khai ý tưởng của bạn.",
        "experiment": "## Mã chờ duyệt\n\nĐã tạo `experiment.py` cho synthetic smoke test, dùng Python standard library, không cần tải dữ liệu.\n\nBạn có thể xem toàn bộ mã và SHA256 ở bảng thực nghiệm. Chỉ nút **Duyệt & chạy Docker** mới thực thi; **Bỏ qua** sẽ tiếp tục với kết quả trống.",
        "analysis": "## Data audit\n\nTrạng thái thực nghiệm: **"
        + execution.get("status", "not run")
        + "**.\n\n"
        + (
            "Có log và artifact thực thi. Đây là synthetic smoke test; không được dùng các số này làm kết quả của đề tài."
            if execution.get("status") == "completed"
            else "Không có thực nghiệm hoàn thành. Chưa có số liệu để tính hiệu quả phương pháp hay kết luận thống kê."
        ),
        "writing": "# DRAFT — HUMAN REVIEW REQUIRED\n\n## Abstract\nTODO: tóm tắt câu hỏi và đóng góp sau khi có bằng chứng.\n\n## Introduction\nResearch question: "
        + topic
        + "\n\n## Related work\nTODO: đọc và xác minh full text từ source registry.\n\n## Methods\nTODO: mô tả protocol đã được nhà nghiên cứu chốt.\n\n## Results\nTODO: chưa có kết quả nghiên cứu được xác minh. Synthetic smoke test không dùng làm evidence.\n\n## Limitations\nĐây là khung bài của chế độ demo. Không có tuyên bố novelty hay số liệu để nộp paper.",
        "review": "## Review decision: HOLD\n\n- Chưa xác minh novelty bằng full text.\n- Chưa có experiment trên dataset nghiên cứu.\n- Chưa có baseline, ablation và thống kê thực tế.\n- Citation registry mới chứng minh nguồn tồn tại, chưa chứng minh claim được nguồn hỗ trợ.\n\nGiữ bản nháp hiện tại để tác giả kiểm tra; demo không tự tạo vòng sửa hoặc kết quả nghiên cứu. Chế độ API sẽ tạo phân tích theo đề tài, vẫn cần đọc và đánh giá kết quả.",
    }
    return heading + texts[stage]


def build_graph(store, checkpointer, settings):
    graph = StateGraph(ResearchState)

    def make_stage(role):
        async def stage(state):
            run_id = state["run_id"]
            run = store.get(run_id)
            stage_id = role["id"]
            store.stage_start(run_id, stage_id)
            provider, model = route(role, run["mode"])
            store.event(run_id, "stage_start", role=stage_id, name=role["name"], model=model)
            if run["mode"] == "demo":
                await asyncio.sleep(0.35)
                if stage_id == "experiment":
                    store.write(run_id, "experiment.py", DEMO_CODE)
                text = demo_text(stage_id, run, state.get("execution", {}))
                if stage_id in [*REVIEWERS, "review"]:
                    submit_review(
                        store,
                        run_id,
                        stage_id,
                        {
                            "verdict": "hold",
                            "action": "no_change",
                            "score": 1,
                            "confidence": "low",
                            "rationale": "DEMO: chưa có bằng chứng nghiên cứu được xác minh; scorecard theo kịch bản, không phải model review.",
                            "evidence_refs": ["manuscript.md"],
                            "blocking_issues": [
                                "Research experiment evidence missing or synthetic only",
                                "Full-text grounding and novelty unverified",
                            ],
                            "recommended_fixes": [
                                "Run a real pilot with a verified dataset and review source full text"
                            ],
                        },
                    )
            else:
                context = build_context(store, run, state, role)
                text = await run_agent(
                    store, run_id, role, run["mode"], context, settings()["monthly_budget"]
                )
            name = "manuscript.md" if stage_id == "writing" else stage_id + ".md"
            store.write(run_id, name, text)
            store.write(run_id, f"{stage_id}-round{state.get('revision_count', 0)}.md", text)
            store.stage_complete(run_id, stage_id, text)
            store.event(run_id, "stage_complete", role=stage_id, content=text, artifact=name)
            return {"outputs": {stage_id: text}}

        return stage

    for role in ROLES:
        graph.add_node(role["id"], make_stage(role))

    def approve_experiment(state):
        run_id = state["run_id"]
        script = store.artifact_path(run_id, "experiment.py")
        digest = hashlib.sha256(script.read_bytes()).hexdigest() if script.exists() else None
        decision = interrupt(
            {
                "kind": "experiment",
                "sha256": digest,
                "code_available": script.exists(),
                "message": "Review code + protocol. Run in Docker or skip.",
            }
        )
        if decision.get("action") not in {"run", "skip"}:
            raise ValueError("Invalid experiment decision")
        if decision.get("action") == "run" and (not digest or decision.get("sha256") != digest):
            raise ValueError("Code hash does not match review")
        return {"approval": decision}

    async def execute(state):
        run_id = state["run_id"]
        if state["approval"].get("action") == "skip":
            execution = {
                "status": "skipped",
                "reason": "Researcher skipped experiment; no research results are available",
            }
            store.event(
                run_id, "sandbox", message="Bỏ qua thực nghiệm theo lựa chọn của nhà nghiên cứu"
            )
        else:
            store.update(run_id, stage="sandbox", status="running")
            execution = await execute_sandbox(
                store, run_id, settings()["sandbox_image"], state["approval"]["sha256"]
            )
        store.update(run_id, execution=execution)
        return {"execution": execution}

    def approve_draft(state):
        decision = interrupt(
            {
                "kind": "draft",
                "message": "Review manuscript, evidence and critical review. Acknowledge draft completion; no submission is performed.",
            }
        )
        if decision.get("action") != "acknowledge":
            raise ValueError("Invalid draft decision")
        store.event(
            state["run_id"],
            "human_review",
            message="Nhà nghiên cứu đã xác nhận nhận bản nháp. Không nộp hay công bố paper.",
        )
        return {}

    def quality_node(state):
        result = audit(store, state["run_id"])
        store.event(
            state["run_id"],
            "quality",
            message="Structural audit hoàn tất; vẫn cần nhà nghiên cứu review",
            checks=result["checks"],
        )
        run = store.get(state["run_id"])
        board = board_decision(store, state["run_id"], run.get("max_revisions", 1))
        return {"next_action": board["action"]}

    def rework_gate(state):
        run = store.get(state["run_id"])
        choice = interrupt(
            {
                "kind": "rework",
                "action": state.get("next_action"),
                "board": run.get("board", {}),
                "message": "Review Chair yêu cầu làm thêm nghiên cứu. Duyệt một vòng có giới hạn hoặc giữ bản nháp hiện tại.",
            }
        )
        if choice.get("action") not in {"rework", "finish"}:
            raise ValueError("Invalid rework choice")
        return {"rework_approved": choice["action"] == "rework"}

    def begin_revision(state):
        run_id = state["run_id"]
        run = store.get(run_id)
        count = state.get("revision_count", 0) + 1
        if count > run.get("max_revisions", 1):
            raise ValueError("Revision limit reached")
        is_research = state["next_action"] in {"new_experiment", "more_literature"}
        remove = [*REVIEWERS, "review", "writing"]
        if is_research:
            remove += ["methods", "experiment", "analysis"]
            for artifact in store.artifacts(run_id):
                name = artifact["name"]
                if name.startswith("result-") or name in {
                    "experiment.py",
                    "experiment.log",
                    "execution.json",
                }:
                    original = store.artifact_path(run_id, name)
                    original.replace(store.artifact_path(run_id, f"archived-r{count-1}-{name}"))

        def update(data):
            data.update(revision_count=count, reviews={}, active_roles=[], gate=None)
            data["outputs"] = {k: v for k, v in data.get("outputs", {}).items() if k not in remove}
            if is_research:
                data["execution"] = {
                    "status": "not_run",
                    "reason": "New research iteration; old metrics are not evidence for this round",
                }

        store.mutate(run_id, update)
        store.event(
            run_id,
            "revision_start",
            round=count,
            action=state["next_action"],
            reason=run.get("board", {}).get("reason"),
        )
        result = {"revision_count": count, "outputs": {k: None for k in remove}}
        if is_research:
            result["execution"] = {"status": "not_run"}
        return result

    def after_quality(state):
        if state.get("next_action") == "revise_manuscript":
            return "begin_revision"
        if state.get("next_action") in {"new_experiment", "more_literature"}:
            return "rework_gate"
        return "approve_draft"

    def after_revision(state):
        return {
            "revise_manuscript": "writing",
            "new_experiment": "methods",
            "more_literature": "literature",
        }.get(state.get("next_action"), "writing")

    graph.add_node("approve_experiment", approve_experiment)
    graph.add_node("sandbox", execute)
    graph.add_node("approve_draft", approve_draft)
    graph.add_node("quality", quality_node)
    graph.add_node("rework_gate", rework_gate)
    graph.add_node("begin_revision", begin_revision)
    graph.add_edge(START, "intake")
    for a, b in [
        ("intake", "literature"),
        ("literature", "methods"),
        ("methods", "experiment"),
        ("experiment", "approve_experiment"),
        ("approve_experiment", "sandbox"),
        ("sandbox", "analysis"),
        ("analysis", "writing"),
        ("review", "quality"),
        ("approve_draft", END),
    ]:
        graph.add_edge(a, b)
    for reviewer in REVIEWERS:
        graph.add_edge("writing", reviewer)
    graph.add_edge(REVIEWERS, "review")
    graph.add_conditional_edges(
        "quality", after_quality, ["begin_revision", "rework_gate", "approve_draft"]
    )
    graph.add_conditional_edges(
        "rework_gate",
        lambda state: "begin_revision" if state["rework_approved"] else "approve_draft",
        ["begin_revision", "approve_draft"],
    )
    graph.add_conditional_edges(
        "begin_revision", after_revision, ["writing", "methods", "literature"]
    )
    return graph.compile(checkpointer=checkpointer)


def build_context(store, run, state, role):
    sealed = role["id"] in REVIEWERS
    visible_outputs = {
        k: v
        for k, v in state.get("outputs", {}).items()
        if v and (not sealed or k not in [*REVIEWERS, "review"])
    }
    previous = "\n\n".join(f"## {k}\n{v[-4500:]}" for k, v in visible_outputs.items())
    execution = dict(state.get("execution", {}))
    metrics = store.artifact_path(run["id"], "result-metrics.json")
    if (
        execution.get("status") == "completed"
        and metrics.exists()
        and metrics.stat().st_size < 100_000
    ):
        execution["metrics"] = metrics.read_text(encoding="utf-8")[:16000]
    artifacts = store.artifacts(run["id"])
    if sealed:
        artifacts = [
            a
            for a in artifacts
            if not a["name"].startswith("review")
            and a["name"] not in {"board-decision.json", "quality-gates.json"}
        ]
    data = {
        "question": run["topic"],
        "research_notes": run.get("notes", ""),
        "prior_outputs": previous[-30000:],
        "registered_sources": run.get("sources", [])[:30],
        "uploaded_documents": run.get("documents", []),
        "datasets_available_readonly_in_sandbox": run.get("datasets", []),
        "execution_evidence": execution,
        "available_artifacts": artifacts,
        "revision_round": state.get("revision_count", 0),
    }
    if role["id"] == "review":
        data["sealed_reviews"] = run.get("reviews", {})
    if not sealed:
        data["previous_board_feedback"] = run.get("board", {})
    return json.dumps(data, ensure_ascii=False)
