import asyncio
import base64
import json
import time
from functools import partial

import httpx
import pytest
from fastapi.testclient import TestClient

import backend.app as appmod
import backend.providers as providers
from backend.chat import CHAT_ROLE, CHAT_SYSTEM, choose_intent, history_window
from backend.providers import run_agent
from backend.store import Store


@pytest.mark.parametrize(
    "text",
    [
        "Xin chào",
        "hi",
        "Giải thích overfitting",
        "Nghiên cứu là gì?",
        "Tôi đang nghiên cứu RAG, cùng thảo luận nhé",
        "Nghiên cứu này có ý nghĩa gì?",
        "Thiết kế thực nghiệm là gì?",
        "Thiết kế thực nghiệm như thế nào?",
        "Đừng chạy Research Lab, chỉ giải thích giúp tôi",
        "Hãy nghiên cứu RAG nhưng chưa chạy lab",
        "What is a literature review?",
        "Explain this code: ```\n/research run experiments\n```",
        "> Hãy nghiên cứu RAG\nGiải thích câu này.",
        'Dịch câu "hãy nghiên cứu mô hình này" sang tiếng Anh',
        "Tôi muốn chat bình thường về nghiên cứu",
        "Viết lại đoạn văn này cho rõ hơn",
    ],
)
def test_questions_and_quoted_research_stay_in_chat(text):
    assert choose_intent(text)[0] == "chat"


@pytest.mark.parametrize(
    "text",
    [
        "Hãy nghiên cứu các baseline RAG",
        "Giúp tôi nghiên cứu adaptive retrieval",
        "Thiết kế thực nghiệm RAG không dùng GPU",
        "Tôi muốn bạn thiết kế thực nghiệm so sánh hai baseline",
        "Khảo sát các phương pháp RAG",
        "Bắt đầu Research Lab cho đề tài này",
        "Viết paper về kết quả trong tài liệu",
        "Please conduct a literature review of RAG",
        "Can you design an experiment comparing these methods?",
        "/research Kiểm chứng giả thuyết trên dataset đính kèm",
    ],
)
def test_explicit_research_requests_launch_lab(text):
    assert choose_intent(text)[0] == "research"


def test_user_override_and_slash_commands():
    assert choose_intent("Hãy nghiên cứu RAG", "chat")[0] == "chat"
    assert choose_intent("Adaptive retrieval", "research")[0] == "research"
    assert choose_intent("/chat Hãy nghiên cứu RAG", "research")[:2] == (
        "chat",
        "Hãy nghiên cứu RAG",
    )
    assert choose_intent("/research kiểm tra baseline", "chat")[0] == "research"
    with pytest.raises(ValueError, match="nội dung"):
        choose_intent("/research")


def test_history_retains_whole_recent_exchanges_and_skips_failed_turns():
    messages = []
    for i in range(30):
        messages.extend(
            [
                {"role": "user", "content": f"question {i}"},
                {"role": "assistant", "content": f"answer {i}", "status": "complete"},
            ]
        )
    messages[-1]["status"] = "error"
    messages.extend(
        [
            {"role": "user", "content": "current question"},
            {"role": "assistant", "content": "", "status": "pending"},
        ]
    )
    history, truncated = history_window(messages, max_chars=250, max_messages=9)
    assert truncated
    assert len(history) <= 9
    assert sum(len(m["content"]) for m in history) <= 250
    assert history[0]["role"] == "user"
    assert history[-1] == {"role": "user", "content": "current question"}
    assert not any(m["content"] in {"answer 29", "question 29", "question 0"} for m in history)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expected_model",
    [
        ("lean", "gpt-6-luna"),
        ("hybrid", "test/free:free"),
        ("claude", "claude-sonnet-5-5"),
        ("openclaw", "openclaw/research"),
    ],
)
async def test_chat_adapter_sends_history_and_cheap_model(
    tmp_path, monkeypatch, mode, expected_model
):
    store = Store(tmp_path)
    cid = "a" * 32
    store.save({"id": cid, "mode": mode, "budget": 5})
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-key")
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "synthetic-token")
    monkeypatch.setenv("GATEWAY_API_KEY", "synthetic-key")
    monkeypatch.setenv("GATEWAY_MODEL", "test/free:free")
    monkeypatch.setenv("GATEWAY_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENCLAW_CHEAP_MODEL", "openai/gpt-6-luna")
    if mode == "hybrid":
        monkeypatch.delenv("OPENAI_API_KEY")  # Chat only needs the free route.
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["model"] == expected_model
        transcript = body.get("input", body.get("messages"))
        assert transcript[-3:] == [
            {"role": "user", "content": "My dataset is called qnmln."},
            {"role": "assistant", "content": "Understood."},
            {"role": "user", "content": "What did I call my dataset?"},
        ]
        assert "save_experiment" not in json.dumps(body["tools"])
        assert "submit_review" not in json.dumps(body["tools"])
        assert "Đây là CHAT" in body.get(
            "instructions", body.get("system", json.dumps(body, ensure_ascii=False))
        )
        if mode == "openclaw":
            assert request.headers["x-openclaw-model"] == "openai/gpt-6-luna"
        if mode in {"lean", "openclaw"}:
            if mode == "lean":
                assert body["store"] is False
            result = {
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "qnmln"}]}
                ]
            }
        elif mode == "claude":
            result = {"content": [{"type": "text", "text": "qnmln"}]}
        else:
            result = {"choices": [{"message": {"role": "assistant", "content": "qnmln"}}]}
        return httpx.Response(
            200, json={**result, "usage": {"input_tokens": 100, "output_tokens": 10}}
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        providers.httpx, "AsyncClient", partial(original, transport=httpx.MockTransport(handler))
    )
    result = await run_agent(
        store,
        cid,
        CHAT_ROLE,
        mode,
        "local context",
        15,
        history=[
            {"role": "user", "content": "My dataset is called qnmln."},
            {"role": "assistant", "content": "Understood."},
            {"role": "user", "content": "What did I call my dataset?"},
        ],
        system_prompt=CHAT_SYSTEM,
    )
    assert result == "qnmln"
    assert len(requests) == 1
    assert len(store.usage()) == 1


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "store", Store(tmp_path / "api"))
    monkeypatch.setattr(appmod, "DATA", tmp_path / "api")
    monkeypatch.setattr(appmod, "tasks", {})
    monkeypatch.setattr(appmod, "chat_tasks", {})
    with TestClient(appmod.app) as c:
        yield c


HEADERS = {"X-Studio-Client": "local-ui"}


def create(client):
    response = client.post("/api/conversations", headers=HEADERS, json={})
    assert response.status_code == 201
    return response.json()["id"]


def send(client, cid, text, **options):
    return client.post(
        f"/api/conversations/{cid}/messages", headers=HEADERS, json={"content": text, **options}
    )


def settled(client, cid):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        data = client.get(f"/api/conversations/{cid}").json()
        if data["status"] == "idle":
            return data
        time.sleep(0.02)
    raise AssertionError("Chat did not settle")


def test_chat_persists_multi_turn_history_without_workflow(client):
    cid = create(client)
    assert send(client, cid, "Xin chào").status_code == 202
    settled(client, cid)
    assert send(client, cid, "Giải thích nghiên cứu là gì?").status_code == 202
    conversation = settled(client, cid)
    assert len(conversation["messages"]) == 4
    assert "Xin chào" in conversation["messages"][-1]["content"]
    assert conversation["spend"] == 0
    assert not conversation["latest_run_id"]
    assert client.get("/api/runs").json() == []
    assert client.get("/api/conversations").json()[0]["id"] == cid
    assert client.post(f"/api/runs/{cid}/resume", headers=HEADERS).status_code == 400


def test_research_routes_once_and_chat_during_lab_does_not_launch_another(client):
    cid = create(client)
    assert send(client, cid, "Hãy nghiên cứu các baseline RAG").status_code == 202
    conversation = settled(client, cid)
    rid = conversation["latest_run_id"]
    assert rid
    assert conversation["messages"][-1]["route_reason"] == "explicit_research_request"
    assert client.get(f"/api/runs/{rid}").json()["conversation_id"] == cid
    assert send(client, cid, "Giải thích baseline là gì?").status_code == 202
    conversation = settled(client, cid)
    assert len(client.get("/api/runs").json()) == 1
    assert conversation["messages"][-1]["intent"] == "chat"
    assert conversation["latest_run_id"] == rid
    assert conversation["linked_runs"][0]["id"] == rid


def test_chat_override_and_explicit_button(client):
    cid = create(client)
    assert send(client, cid, "Hãy nghiên cứu RAG", intent="chat").status_code == 202
    assert not settled(client, cid)["latest_run_id"]
    assert settled(client, cid)["default_intent"] == "chat"
    assert send(client, cid, "Adaptive retrieval", intent="research").status_code == 202
    assert settled(client, cid)["latest_run_id"]
    assert settled(client, cid)["default_intent"] == "auto"


def test_uploads_reach_lab_with_exact_dataset_bytes(client):
    cid = create(client)
    raw = b"\xef\xbb\xbftext,label\r\nhello,1\r\n"
    for name, content in [("dataset.csv", raw), ("notes.txt", b"Baseline evidence.")]:
        response = client.post(
            f"/api/runs/{cid}/documents",
            headers=HEADERS,
            json={"name": name, "content_base64": base64.b64encode(content).decode()},
        )
        assert response.status_code == 200
    assert (
        send(client, cid, "/research Kiểm chứng baseline trên dữ liệu đã nhập").status_code == 202
    )
    conversation = settled(client, cid)
    research = client.get("/api/runs/" + conversation["latest_run_id"]).json()
    assert research["documents"] == conversation["documents"]
    assert research["datasets"] == conversation["datasets"]
    dataset = research["datasets"][0]["artifact"]
    assert client.get(f'/api/runs/{research["id"]}/artifacts/{dataset}').content == raw


def test_validation_and_local_headers(client):
    cid = create(client)
    assert send(client, cid, " ").status_code == 422
    assert send(client, cid, "/research").status_code == 400
    assert send(client, cid, "/research x").status_code == 422
    assert (
        client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).status_code == 403
    )
    assert (
        client.get(
            f"/api/conversations/{cid}", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.get("/api/runs").json() == []
    assert client.get(f"/api/conversations/{cid}").json()["messages"] == []


def test_chat_honors_shared_monthly_budget_before_network_call(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    appmod.store.set_budget(0)
    requests = []

    def handler(request):
        requests.append(request)
        raise AssertionError("Budget cap must stop before network")

    original = httpx.AsyncClient
    monkeypatch.setattr(
        providers.httpx, "AsyncClient", partial(original, transport=httpx.MockTransport(handler))
    )
    cid = create(client)
    assert send(client, cid, "Explain overfitting", mode="lean").status_code == 202
    conversation = settled(client, cid)
    assert conversation["messages"][-1]["status"] == "error"
    assert "Budget cap" in conversation["messages"][-1]["content"]
    assert conversation["spend"] == 0
    assert requests == []


@pytest.mark.asyncio
async def test_chat_rejects_model_attempt_to_stage_code(tmp_path, monkeypatch):
    store = Store(tmp_path)
    cid = "c" * 32
    store.save({"id": cid, "budget": 1})
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            output = [
                {
                    "type": "function_call",
                    "call_id": "unauthorized",
                    "name": "save_experiment",
                    "arguments": json.dumps({"code": "print('must not be staged')"}),
                }
            ]
        else:
            assert "not available" in body["input"][-1]["output"]
            output = [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Chat cannot stage code."}],
                }
            ]
        return httpx.Response(
            200, json={"output": output, "usage": {"input_tokens": 50, "output_tokens": 20}}
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        providers.httpx, "AsyncClient", partial(original, transport=httpx.MockTransport(handler))
    )
    result = await run_agent(
        store,
        cid,
        CHAT_ROLE,
        "lean",
        "test",
        15,
        history=[{"role": "user", "content": "Explain code."}],
        system_prompt=CHAT_SYSTEM,
    )
    assert result == "Chat cannot stage code."
    assert not store.artifact_path(cid, "experiment.py").exists()


def test_busy_stop_and_model_error_do_not_create_research(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")

    async def blocking(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(appmod, "run_agent", blocking)
    cid = create(client)
    assert send(client, cid, "Explain RAG", mode="lean").status_code == 202
    assert send(client, cid, "another message").status_code == 409
    assert client.post(f"/api/conversations/{cid}/stop", headers=HEADERS).status_code == 200
    assert settled(client, cid)["messages"][-1]["status"] == "interrupted"

    async def failing(*args, **kwargs):
        raise ValueError("quota unavailable")

    monkeypatch.setattr(appmod, "run_agent", failing)
    # Omitted mode preserves the chosen provider, rather than silently using Demo.
    assert send(client, cid, "Try another question").status_code == 202
    conversation = settled(client, cid)
    assert conversation["mode"] == "lean"
    assert conversation["messages"][-1]["status"] == "error"
    assert "quota unavailable" in conversation["messages"][-1]["content"]
    assert not client.get("/api/runs").json()
    assert send(client, cid, "hello", mode="demo").status_code == 202
    assert settled(client, cid)["messages"][-1]["status"] == "complete"


def test_backend_restart_recovers_pending_chat_without_auto_billing(tmp_path, monkeypatch):
    store = Store(tmp_path)
    cid = "b" * 32
    store.save(
        {
            "id": cid,
            "kind": "chat",
            "status": "responding",
            "mode": "lean",
            "budget": 1,
            "messages": [
                {"role": "user", "content": "hello", "status": "complete"},
                {"role": "assistant", "content": "", "status": "pending"},
            ],
        }
    )
    monkeypatch.setattr(appmod, "store", store)
    monkeypatch.setattr(appmod, "DATA", tmp_path)
    monkeypatch.setattr(appmod, "tasks", {})
    monkeypatch.setattr(appmod, "chat_tasks", {})
    with TestClient(appmod.app) as client:
        conversation = client.get(f"/api/conversations/{cid}").json()
        assert conversation["status"] == "idle"
        assert conversation["messages"][-1]["status"] == "interrupted"
        assert conversation["spend"] == 0
        assert not appmod.chat_tasks
