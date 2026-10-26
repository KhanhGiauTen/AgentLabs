import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from .catalog import MODELS, SYSTEM
from .tools import SCHEMAS, call_tool

MAX_OUTPUT = 6000
MAX_TURNS = 4


def route(role, mode):
    important = role["id"] in {"methods", "review"}
    if mode == "demo":
        return "demo", "Scripted demo"
    if mode == "local":
        return "local", os.getenv("LOCAL_MODEL", "qwen3:8b")
    if mode == "openclaw":
        return "openclaw", (
            "gpt-6.1-sol"
            if important
            else os.getenv("OPENCLAW_CHEAP_MODEL", "openai/gpt-6-luna").removeprefix("openai/")
        )
    if mode == "free" or (mode == "hybrid" and not important):
        return "gateway", os.getenv("GATEWAY_MODEL", "")
    if mode == "claude":
        return "anthropic", "claude-opus-5-5" if important else "claude-sonnet-5-5"
    return "openai", role["model"]


def readiness(mode, role=None):
    if mode == "hybrid" and role and role["id"] == "chat":
        mode = "free"  # Ordinary chat never needs the paid Methods/Chair route.
    required = {
        "lean": ["OPENAI_API_KEY"],
        "hybrid": ["OPENAI_API_KEY", "GATEWAY_API_KEY", "GATEWAY_MODEL"],
        "free": ["GATEWAY_API_KEY", "GATEWAY_MODEL"],
        "claude": ["ANTHROPIC_API_KEY"],
        "openclaw": ["OPENCLAW_GATEWAY_TOKEN", "OPENAI_API_KEY"],
    }.get(mode, [])
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise ValueError(
            "Chưa cấu hình trong .env: "
            + ", ".join(missing)
            + ". Khởi động lại backend sau khi sửa .env."
        )
    if mode in {"hybrid", "free"}:
        if os.getenv("GATEWAY_URL", "https://openrouter.ai/api/v1").rstrip(
            "/"
        ) != "https://openrouter.ai/api/v1" or not os.getenv("GATEWAY_MODEL", "").endswith(":free"):
            raise ValueError(
                "MVP chỉ cho phép gateway OpenRouter và model có hậu tố :free. Không tự fallback sang model trả phí."
            )
    if mode in {"local", "openclaw"}:
        u = urlparse(
            os.getenv("OPENCLAW_URL", "http://127.0.0.1:18789")
            if mode == "openclaw"
            else os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:11434/v1")
        )
        if (
            u.scheme not in {"http", "https"}
            or u.hostname not in {"localhost", "127.0.0.1", "::1"}
            or u.username
            or u.password
        ):
            raise ValueError(
                "Địa chỉ local model/gateway phải là loopback, không chứa thông tin đăng nhập"
            )
    if mode == "openclaw":
        cheap = os.getenv("OPENCLAW_CHEAP_MODEL", "openai/gpt-6-luna")
        if cheap != "openai/gpt-6-luna" and not (
            cheap.startswith("openrouter/") and cheap.endswith(":free")
        ):
            raise ValueError(
                "OpenClaw cheap route phải là openai/gpt-6-luna hoặc openrouter/<model>:free"
            )


def model_cost(model, inp, out, cached=0, cache_write=0):
    rates = MODELS.get(model, {"input": 0, "output": 0})
    # Conservative standard-rate estimate: cache hits charged as uncached input.
    return (
        (inp + cached + 1.25 * cache_write) * rates["input"] + out * rates["output"]
    ) / 1_000_000


async def run_agent(
    store, run_id, role, mode, context, monthly_budget, *, history=None, system_prompt=None
):
    readiness(mode, role)
    provider, model = route(role, mode)
    allowed = list(role["tools"]) + ["read_artifact", "search_documents"]
    schemas = [
        {"type": "function", "name": name, **SCHEMAS[name], "strict": True} for name in allowed
    ]
    system = system_prompt or (
        SYSTEM + "\nVai trò: " + role["name"] + "\nNhiệm vụ: " + role["brief"]
    )
    if role["id"] in {"literature", "experiment"}:
        system += "\nBẮT BUỘC gọi literature_search (vai trò literature) hoặc save_experiment (vai trò experiment) trước khi trả lời cuối. Văn bản khẳng định đã gọi tool không thay thế tool call thật."
    messages = [{"role": "user", "content": context}, *(history or [])]
    response_input = list(messages)
    required_tool_done = False
    async with httpx.AsyncClient(timeout=180, follow_redirects=False) as client:
        for turn in range(MAX_TURNS):
            force_tool = (
                "literature_search"
                if role["id"] == "literature"
                else (
                    "save_experiment"
                    if role["id"] == "experiment"
                    else "submit_review" if "submit_review" in role["tools"] else None
                )
            )
            force_first = turn == 0 and force_tool in {"literature_search", "save_experiment"}
            choice = {"type": "function", "name": force_tool} if force_first else "auto"
            payload_size = len(
                json.dumps(
                    [
                        system,
                        response_input if provider in {"openai", "openclaw"} else messages,
                        schemas,
                    ],
                    ensure_ascii=False,
                ).encode()
            )
            if payload_size > 240_000:
                raise ValueError("Context quá lớn; chia nghiên cứu thành lượt nhỏ hơn")
            # Bytes are a deliberately conservative upper bound for prompt tokens.
            upper = model_cost(model, payload_size + 4000, MAX_OUTPUT)
            if provider == "openclaw":
                upper += max(0.01, float(os.getenv("OPENCLAW_CALL_RESERVE_USD", ".10")))
            run = store.get(run_id)
            if provider == "gateway":
                used = sum(
                    1
                    for u in store.usage()
                    if u["model"] == model
                    and u["at"][:10] == datetime.now(timezone.utc).isoformat()[:10]
                )
                if used >= 30:
                    raise ValueError(
                        "Đã chạm giới hạn ứng dụng 30 free requests/ngày (UTC); quota upstream có thể thấp hơn."
                    )
            reservation = store.reserve(run_id, model, upper, monthly_budget, run["budget"])
            store.event(
                run_id, "model", role=role["id"], model=model, provider=provider, turn=turn + 1
            )
            try:
                if provider == "openclaw":
                    target = "openai/" + model if model in MODELS else model
                    response = await client.post(
                        os.getenv("OPENCLAW_URL", "http://127.0.0.1:18789").rstrip("/")
                        + "/v1/responses",
                        headers={
                            "Authorization": "Bearer " + os.environ["OPENCLAW_GATEWAY_TOKEN"],
                            "x-openclaw-model": target,
                        },
                        json={
                            "model": "openclaw/" + os.getenv("OPENCLAW_AGENT", "research"),
                            "instructions": system,
                            "input": response_input,
                            "tools": schemas,
                            "tool_choice": choice,
                            "max_output_tokens": MAX_OUTPUT,
                        },
                    )
                elif provider == "openai":
                    response = await client.post(
                        "https://api.openai.com/v1/responses",
                        headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]},
                        json={
                            "model": model,
                            "instructions": system,
                            "input": response_input,
                            "tools": schemas,
                            "tool_choice": choice,
                            "max_output_tokens": MAX_OUTPUT,
                            "reasoning": {"effort": "low"},
                            "store": False,
                            "include": ["reasoning.encrypted_content"],
                        },
                    )
                elif provider == "anthropic":
                    # Current Claude 5.5 rejects forced tool_choice. Validate the required call locally.
                    response = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                            "anthropic-version": "2023-06-01",
                        },
                        json={
                            "model": model,
                            "system": system,
                            "messages": messages,
                            "max_tokens": MAX_OUTPUT,
                            "tools": [
                                {
                                    "name": s["name"],
                                    "description": s["description"],
                                    "input_schema": s["parameters"],
                                }
                                for s in schemas
                            ],
                            "tool_choice": {"type": "auto"},
                        },
                    )
                else:
                    base = (
                        os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:11434/v1")
                        if provider == "local"
                        else "https://openrouter.ai/api/v1"
                    )
                    key = "local" if provider == "local" else os.environ["GATEWAY_API_KEY"]
                    payload = {
                        "model": model,
                        "messages": [{"role": "system", "content": system}, *messages],
                        "max_tokens": MAX_OUTPUT,
                        "tools": [
                            {
                                "type": "function",
                                "function": {
                                    "name": s["name"],
                                    "description": s["description"],
                                    "parameters": s["parameters"],
                                },
                            }
                            for s in schemas
                        ],
                    }
                    payload["tool_choice"] = (
                        {"type": "function", "function": {"name": force_tool}}
                        if force_first
                        else "auto"
                    )
                    if provider == "gateway":
                        payload["provider"] = {"require_parameters": True, "allow_fallbacks": False}
                    response = await client.post(
                        base.rstrip("/") + "/chat/completions",
                        headers={"Authorization": "Bearer " + key},
                        json=payload,
                    )
                if response.status_code >= 400:
                    raise ValueError(
                        f"{provider}: HTTP {response.status_code}. Kiểm tra model, key và quota trên dashboard; không chuyển sang provider khác."
                    )
                data = response.json()
            except BaseException:
                store.uncertain(reservation)
                raise
            u = data.get("usage", {})
            inp = int(u.get("input_tokens", u.get("prompt_tokens", 0)))
            out = int(u.get("output_tokens", u.get("completion_tokens", 0)))
            cached = int(u.get("cache_read_input_tokens", 0))
            cache_write = int(u.get("cache_creation_input_tokens", 0))
            cost = model_cost(model, inp, out, cached, cache_write) if u else upper
            if provider == "openclaw":
                # Gateway limits are best effort. Retain overhead reserve conservatively.
                cost = max(cost, upper)
            store.settle(reservation, inp + cached + cache_write, out, cost)
            store.event(
                run_id,
                "usage",
                model=model,
                input_tokens=inp,
                output_tokens=out,
                estimated_usd=cost,
            )
            calls, text = [], ""
            if provider in {"openai", "openclaw"}:
                outputs = data.get("output", [])
                response_input.extend(outputs)
                text = "\n".join(
                    c.get("text", "")
                    for item in outputs
                    if item.get("type") == "message"
                    for c in item.get("content", [])
                    if c.get("type") == "output_text"
                )
                calls = [
                    {"id": i["call_id"], "name": i["name"], "args": i["arguments"]}
                    for i in outputs
                    if i.get("type") == "function_call"
                ]
            elif provider == "anthropic":
                content = data.get("content", [])
                messages.append({"role": "assistant", "content": content})
                text = "\n".join(c["text"] for c in content if c.get("type") == "text")
                calls = [
                    {"id": i["id"], "name": i["name"], "args": i["input"]}
                    for i in content
                    if i.get("type") == "tool_use"
                ]
            else:
                if not data.get("choices"):
                    raise ValueError("Provider returned no choices")
                message = data["choices"][0]["message"]
                messages.append(
                    {k: message[k] for k in ("role", "content", "tool_calls") if k in message}
                )
                text = message.get("content") or ""
                calls = [
                    {
                        "id": i["id"],
                        "name": i["function"]["name"],
                        "args": i["function"]["arguments"],
                    }
                    for i in message.get("tool_calls", [])
                ]
            if not calls:
                if force_tool and not required_tool_done:
                    raise ValueError(
                        f"Model không gọi tool bắt buộc {force_tool}; không chấp nhận lời khẳng định đã làm việc mà thiếu tool log."
                    )
                if not text.strip():
                    raise ValueError(
                        "Model không trả nội dung (có thể hết output tokens). Không tạo kết quả giả."
                    )
                if (
                    data.get("status") == "incomplete"
                    or data.get("stop_reason") == "max_tokens"
                    or (data.get("choices") and data["choices"][0].get("finish_reason") == "length")
                ):
                    raise ValueError("Output bị cắt do token limit; chia nhỏ nhiệm vụ và chạy lại")
                return text
            if len(calls) > 6:
                raise ValueError("Too many tool calls in one turn")
            tool_results = []
            for call in calls:
                try:
                    args = (
                        json.loads(call["args"]) if isinstance(call["args"], str) else call["args"]
                    )
                    store.event(
                        run_id,
                        "tool",
                        role=role["id"],
                        name=call["name"],
                        detail=str(
                            args.get("query", args.get("name", "Staging code for approval"))
                        ),
                    )
                    result = await call_tool(
                        store, run_id, call["name"], args, allowed, role_id=role["id"]
                    )
                    if call["name"] == force_tool:
                        required_tool_done = True
                except Exception as e:
                    result = {"error": str(e)[:500]}
                encoded = json.dumps(result, ensure_ascii=False)
                if provider in {"openai", "openclaw"}:
                    response_input.append(
                        {"type": "function_call_output", "call_id": call["id"], "output": encoded}
                    )
                elif provider == "anthropic":
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": call["id"], "content": encoded}
                    )
                else:
                    messages.append(
                        {"role": "tool", "tool_call_id": call["id"], "content": encoded}
                    )
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
    raise ValueError(
        "Đã đạt 4 model turns cho vai trò này. Dừng để tránh vòng lặp và chi phí ngoài dự kiến."
    )
