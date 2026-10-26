import asyncio
import hashlib
import io
import json
import os
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from pydantic import BaseModel, Field
from typing import Literal

from .catalog import MODELS, REPOS, ROLES
from .providers import readiness, route
from .store import Store, now
from .tools import docker_status, register_sources, search_literature
from .workflow import build_graph
from .documents import ingest

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
os.environ["LANGSMITH_TRACING"] = "false"
DATA = Path(os.getenv("RESEARCH_STUDIO_DATA", str(ROOT / "data")))
store = Store(DATA)
tasks = {}


def settings():
    return {
        **store.settings(float(os.getenv("MONTHLY_BUDGET_USD", "15"))),
        "sandbox_image": os.getenv("SANDBOX_IMAGE", "research-studio-sandbox:local"),
    }


@asynccontextmanager
async def lifespan(app):
    for run in store.list():
        if run["status"] == "running":
            store.update(
                run["id"],
                status="interrupted",
                error="Backend đã dừng. Checkpoint được giữ; bạn có thể tiếp tục thủ công.",
            )
    async with AsyncSqliteSaver.from_conn_string(str(DATA / "checkpoints.sqlite")) as saver:
        app.state.graph = build_graph(store, saver, settings)
        yield
        pending = [t for t in tasks.values() if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(title="AgentLabs", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def local_only(request: Request, call_next):
    host = request.url.hostname
    if host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        return JSONResponse({"detail": "Loopback only"}, status_code=403)
    if request.url.path.startswith("/api"):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).hostname not in {"localhost", "127.0.0.1", "::1"}:
            return JSONResponse({"detail": "Cross-origin access disabled"}, status_code=403)
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.headers.get("x-studio-client") != "local-ui"
        ):
            return JSONResponse({"detail": "Missing local client header"}, status_code=403)
        length = request.headers.get("content-length")
        max_length = 14_000_000 if request.url.path.endswith("/documents") else 250_000
        if length and int(length) > max_length:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'self'"
    )
    return response


def get_run(run_id):
    run = store.get(run_id)
    if not run:
        raise HTTPException(404, "Không tìm thấy nghiên cứu")
    return run


def idle():
    if any(not task.done() for task in tasks.values()):
        raise HTTPException(
            409, "Đang có một workflow chạy. Đợi hoặc tạm dừng trước khi chạy lượt khác."
        )


async def drive(run_id, payload):
    graph = app.state.graph
    store.update(run_id, status="running", error=None, gate=None, active_roles=[])
    try:
        await graph.ainvoke(payload, {"configurable": {"thread_id": run_id}, "recursion_limit": 65})
        snapshot = await graph.aget_state({"configurable": {"thread_id": run_id}})
        interrupts = [i.value for t in snapshot.tasks for i in t.interrupts]
        if interrupts:
            gate = interrupts[0]
            store.update(
                run_id,
                status="waiting",
                gate=gate,
                stage={
                    "experiment": "approval",
                    "rework": "rework_review",
                    "draft": "draft_review",
                }[gate["kind"]],
                active_roles=[],
            )
            store.event(run_id, "approval", gate=gate)
        elif not snapshot.next:
            store.update(run_id, status="completed", stage="completed", gate=None, active_roles=[])
            store.event(
                run_id, "completed", message="Workflow hoàn tất ở mức bản nháp; chưa nộp paper"
            )
        else:
            store.update(run_id, status="interrupted")
    except asyncio.CancelledError:
        store.update(
            run_id,
            status="interrupted",
            error="Đã tạm dừng. API call đang gửi có thể vẫn được tính phí; dự phòng được giữ.",
        )
        store.event(run_id, "paused", message="Tạm dừng; checkpoint được giữ")
        raise
    except Exception as e:
        message = (
            str(e)[:700]
            if isinstance(e, ValueError)
            else f"{type(e).__name__}: bước xử lý lỗi. Kiểm tra cấu hình hoặc thử lại từ checkpoint."
        )
        store.update(run_id, status="error", error=message, active_roles=[])
        store.event(run_id, "error", message=message)


def launch(run_id, payload):
    idle()
    tasks[run_id] = asyncio.create_task(drive(run_id, payload))


class RunCreate(BaseModel):
    topic: str = Field(min_length=5, max_length=8000)
    notes: str = Field(default="", max_length=12000)
    mode: Literal["demo", "lean", "hybrid", "free", "local", "claude", "openclaw"] = "demo"
    budget: float = Field(default=0.75, ge=0.05, le=20)
    parent_id: str | None = None
    autostart: bool = True
    max_revisions: int = Field(default=1, ge=0, le=1)


class Decision(BaseModel):
    action: Literal["run", "skip", "acknowledge", "rework", "finish"]
    sha256: str | None = None


class Search(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    source: Literal["crossref", "arxiv"] = "crossref"
    run_id: str | None = None


class Budget(BaseModel):
    monthly_budget: float = Field(ge=0, le=1000)


class DocumentUpload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(max_length=13_500_000)


@app.get("/api/config")
async def config():
    return {
        "roles": ROLES,
        "models": MODELS,
        "repos": REPOS,
        "settings": settings(),
        "configured": {
            "openai": bool(os.getenv("OPENAI_API_KEY")),
            "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
            "gateway": bool(os.getenv("GATEWAY_API_KEY") and os.getenv("GATEWAY_MODEL")),
            "openclaw": bool(os.getenv("OPENCLAW_GATEWAY_TOKEN")),
            "local": True,
        },
        "routes": {
            mode: [
                {"role": r["id"], "provider": route(r, mode)[0], "model": route(r, mode)[1]}
                for r in ROLES
            ]
            for mode in ["demo", "lean", "hybrid", "free", "local", "claude", "openclaw"]
        },
        "price_date": "2026-10-26",
    }


@app.get("/api/health")
async def health():
    return {"ok": True, "app": "AgentLabs", "mode": "local-only", "docker": await docker_status()}


@app.get("/api/runs")
async def list_runs():
    return [
        {k: v for k, v in r.items() if k not in {"outputs", "sources", "notes"}}
        | {"spend": store.spend(r["id"])}
        for r in store.list()
    ]


@app.post("/api/runs", status_code=201)
async def create_run(data: RunCreate):
    idle()
    try:
        readiness(data.mode)
    except ValueError as e:
        raise HTTPException(400, str(e))
    parent = get_run(data.parent_id) if data.parent_id else None
    run_id = uuid.uuid4().hex
    notes = data.notes
    if parent:
        notes += (
            "\nPrevious research context (unverified drafts):\n"
            + json.dumps(parent.get("outputs", {}), ensure_ascii=False)[-14000:]
        )
    run = {
        "id": run_id,
        "topic": data.topic.strip(),
        "notes": notes,
        "mode": data.mode,
        "budget": data.budget,
        "status": "running" if data.autostart else "draft",
        "stage": "intake",
        "created_at": now(),
        "outputs": {},
        "reviews": {},
        "revision_count": 0,
        "max_revisions": data.max_revisions,
        "sources": [],
        "documents": [],
        "execution": {},
        "gate": None,
        "parent_id": data.parent_id,
    }
    store.save(run)
    if parent:
        register_sources(store, run_id, parent.get("sources", []))
        for doc in parent.get("documents", []) + parent.get("datasets", []):
            original = store.artifact_path(parent["id"], doc["artifact"])
            store.write(run_id, doc["artifact"], original.read_text(encoding="utf-8"))
        store.update(
            run_id, documents=parent.get("documents", []), datasets=parent.get("datasets", [])
        )
    store.event(run_id, "user", content=data.topic, mode=data.mode)
    if data.autostart:
        launch(run_id, {"run_id": run_id, "outputs": {}, "execution": {}})
    return run


@app.get("/api/runs/{run_id}")
async def run_detail(run_id: str):
    run = get_run(run_id)
    script = store.artifact_path(run_id, "experiment.py")
    experiment = (
        {
            "code": script.read_text(encoding="utf-8"),
            "sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        }
        if script.exists()
        else None
    )
    return {
        **run,
        "events": store.events(run_id),
        "artifacts": store.artifacts(run_id),
        "spend": store.spend(run_id),
        "experiment": experiment,
    }


@app.post("/api/runs/{run_id}/decision")
async def decision(run_id: str, data: Decision):
    run = get_run(run_id)
    idle()
    if run["status"] != "waiting" or not run.get("gate"):
        raise HTTPException(409, "Workflow không chờ quyết định")
    gate = run["gate"]
    if gate["kind"] == "experiment":
        if data.action not in {"run", "skip"}:
            raise HTTPException(400, "Chọn run hoặc skip")
        if data.action == "run":
            script = store.artifact_path(run_id, "experiment.py")
            if (
                not script.exists()
                or not data.sha256
                or hashlib.sha256(script.read_bytes()).hexdigest() != data.sha256
                or gate.get("sha256") != data.sha256
            ):
                raise HTTPException(409, "Mã đã thay đổi; cần duyệt lại hash")
            docker = await docker_status()
            if not docker["ready"]:
                raise HTTPException(
                    400,
                    docker["message"] + ". Mở Docker Desktop và build sandbox image; hoặc bỏ qua.",
                )
    elif gate["kind"] == "rework":
        if data.action not in {"rework", "finish"}:
            raise HTTPException(400, "Chọn rework hoặc finish")
        if data.action == "rework" and run.get("revision_count", 0) >= run.get("max_revisions", 1):
            raise HTTPException(409, "Đã đạt giới hạn vòng sửa")
    elif data.action != "acknowledge":
        raise HTTPException(400, "Chọn acknowledge sau khi đọc bản nháp")
    store.event(run_id, "decision", action=data.action, sha256=data.sha256)
    launch(run_id, Command(resume=data.model_dump()))
    return {"ok": True}


@app.post("/api/runs/{run_id}/pause")
async def pause(run_id: str):
    get_run(run_id)
    task = tasks.get(run_id)
    if task and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return {"ok": True}


@app.post("/api/runs/{run_id}/refresh-experiment")
async def refresh_experiment(run_id: str):
    run = get_run(run_id)
    if run["status"] != "waiting" or run.get("gate", {}).get("kind") != "experiment":
        raise HTTPException(409, "Chỉ đọc lại mã tại điểm duyệt thực nghiệm")
    script = store.artifact_path(run_id, "experiment.py")
    if not script.exists() or script.stat().st_size > 100_000:
        raise HTTPException(400, "Experiment script missing or too large")
    try:
        compile(script.read_text(encoding="utf-8"), "experiment.py", "exec")
    except SyntaxError as e:
        raise HTTPException(400, f"Python syntax error: line {e.lineno}")
    digest = hashlib.sha256(script.read_bytes()).hexdigest()
    store.update(run_id, gate={**run["gate"], "sha256": digest, "code_available": True})
    store.event(
        run_id, "code_review_refresh", sha256=digest, message="Mã đã đổi; chưa được duyệt để chạy"
    )
    return {"sha256": digest}


@app.post("/api/runs/{run_id}/resume")
async def resume(run_id: str):
    run = get_run(run_id)
    if run["status"] not in {"draft", "error", "interrupted"}:
        raise HTTPException(409, "Chỉ tiếp tục workflow lỗi hoặc tạm dừng")
    idle()
    snapshot = await app.state.graph.aget_state({"configurable": {"thread_id": run_id}})
    payload = None if snapshot.values else {"run_id": run_id, "outputs": {}, "execution": {}}
    launch(run_id, payload)
    return {"ok": True}


@app.post("/api/search")
async def search(data: Search):
    if data.run_id:
        run = get_run(data.run_id)
        if run["status"] == "running":
            raise HTTPException(409, "Đợi workflow dừng trước khi thêm nguồn")
    try:
        papers = await search_literature(data.query, data.source)
    except Exception as e:
        raise HTTPException(
            502, "Nguồn tìm kiếm không phản hồi. Thử query ngắn hơn hoặc chuyển Crossref/arXiv."
        ) from e
    if data.run_id:
        register_sources(store, data.run_id, papers)
        store.event(data.run_id, "search", query=data.query, source=data.source, count=len(papers))
    return {"papers": papers, "persisted": bool(data.run_id)}


@app.get("/api/usage")
async def usage():
    return {
        "month": store.month(),
        "spent_and_reserved": store.spend(),
        "budget": settings()["monthly_budget"],
        "ledger": store.usage(),
        "note": "Ước tính trong ứng dụng, gồm dự phòng call chưa rõ trạng thái. Không phải hóa đơn nhà cung cấp; không tính usage từ ứng dụng khác.",
    }


@app.post("/api/runs/{run_id}/documents")
async def upload_document(run_id: str, data: DocumentUpload):
    run = get_run(run_id)
    if run["status"] == "running":
        raise HTTPException(409, "Tạm dừng workflow trước khi thêm tài liệu")
    try:
        return await asyncio.to_thread(ingest, store, run_id, data.name, data.content_base64)
    except Exception as e:
        raise HTTPException(
            400,
            (
                str(e)[:300]
                if isinstance(e, ValueError)
                else "Không đọc được PDF/text; thử xuất lại tài liệu"
            ),
        ) from e


@app.get("/api/runs/{run_id}/preview/{name}")
async def preview_image(run_id: str, name: str):
    get_run(run_id)
    try:
        path = store.artifact_path(run_id, name)
    except ValueError:
        raise HTTPException(400, "Invalid name")
    if not path.is_file() or path.suffix.lower() != ".png":
        raise HTTPException(400, "Chỉ preview PNG; SVG được tải xuống để kiểm tra riêng")
    return FileResponse(path, media_type="image/png")


@app.put("/api/settings")
async def update_settings(data: Budget):
    store.set_budget(data.monthly_budget)
    return settings()


@app.get("/api/runs/{run_id}/artifacts/{name}")
async def artifact(run_id: str, name: str):
    get_run(run_id)
    try:
        path = store.artifact_path(run_id, name)
    except ValueError:
        raise HTTPException(400, "Invalid name")
    if not path.is_file():
        raise HTTPException(404, "Artifact missing")
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@app.get("/api/runs/{run_id}/export")
async def export(run_id: str):
    run = get_run(run_id)
    if run["status"] == "running":
        raise HTTPException(409, "Tạm dừng workflow trước khi export để có snapshot nhất quán")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("run.json", json.dumps(run, ensure_ascii=False, indent=2))
        z.writestr("events.json", json.dumps(store.events(run_id), ensure_ascii=False, indent=2))
        for artifact in store.artifacts(run_id):
            path = store.artifact_path(run_id, artifact["name"])
            if path.stat().st_size < 20_000_000:
                z.write(path, path.name)
    out.seek(0)
    return StreamingResponse(
        out,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="research-{run_id[:8]}.zip"'},
    )


dist = ROOT / "frontend" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="ui")
