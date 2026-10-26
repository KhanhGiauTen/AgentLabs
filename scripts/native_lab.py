"""AgentLabs distribution of pinned OpenClaw: native UI and native agent roster.

No patching node_modules, no global OpenClaw state, no LLM calls during setup.
"""

import argparse
import json
import secrets
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import openclaw as runtime

STATE = ROOT.parent / "work" / "agentlabs-native"
PORT = 18790
MODEL_PORT = 18791
NATIVE_PIN = json.loads((ROOT / "upstreams.lock.json").read_text(encoding="utf-8"))[
    "openclaw_native"
]


def cli_path():
    path = ROOT.parent / "work/openclaw-native-runtime/node_modules/openclaw/openclaw.mjs"
    if not path.exists():
        raise SystemExit("Native runtime missing. Run setup-native.ps1 first.")
    installed = json.loads((path.parent / "package.json").read_text(encoding="utf-8"))
    if installed.get("version") != NATIVE_PIN["version"]:
        raise SystemExit(
            "Native runtime version differs from the reviewed pin. Stop the lab and run setup-native.ps1."
        )
    return path


def readiness(env, transport=None):
    import httpx

    agents = []
    with httpx.Client(timeout=4, trust_env=False, transport=transport) as client:
        for role in roles():
            try:
                response = client.post(
                    f"http://127.0.0.1:{PORT}/tools/invoke",
                    headers={"Authorization": "Bearer " + env["AGENTLABS_NATIVE_TOKEN"]},
                    json={"tool": "lab_repo_list", "agentId": role["id"], "args": {}},
                )
                agents.append(
                    {
                        "id": role["id"],
                        "ready": response.status_code == 200,
                        "http_status": response.status_code,
                    }
                )
            except httpx.HTTPError:
                agents.append(
                    {"id": role["id"], "ready": False, "reason": "Gateway did not respond"}
                )
        try:
            response = client.get(
                f"http://127.0.0.1:{MODEL_PORT}/health",
                headers={"Authorization": "Bearer " + env["AGENTLABS_MODEL_TOKEN"]},
            )
            proxy = response.json() if response.status_code == 200 else {"ok": False}
        except (httpx.HTTPError, ValueError):
            proxy = {"ok": False}
    count = sum(a["ready"] for a in agents)
    return {
        "ok": count == len(agents) and bool(proxy.get("ok")),
        "agents_ready": count,
        "agents_total": len(agents),
        "agents": agents,
        "model_proxy": proxy,
    }


def roles():
    # Domain role contracts are shared; execution ownership is now OpenClaw.
    from backend.catalog import ROLES

    mapping = {"intake": "director", "review": "review-chair"}
    result = [
        {**role, "id": mapping.get(role["id"], role["id"].replace("_", "-"))} for role in ROLES
    ]
    for role in result:
        role["brief"] = role["brief"].replace(
            "qua save_experiment", "bằng lab_submit (content chỉ chứa mã Python)"
        )
        role["brief"] = role["brief"].replace(
            "submit_review", "lab_decide" if role["id"] == "review-chair" else "lab_review"
        )
    return result


def environment():
    env = runtime.environment()
    STATE.mkdir(parents=True, exist_ok=True)
    token_path = STATE / "gateway-token"
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(36), encoding="utf-8")
    env["AGENTLABS_NATIVE_TOKEN"] = token_path.read_text(encoding="utf-8").strip()
    env["OPENCLAW_GATEWAY_TOKEN"] = env["AGENTLABS_NATIVE_TOKEN"]
    env["OPENCLAW_STATE_DIR"] = str(STATE)
    env["OPENCLAW_CONFIG_PATH"] = str(STATE / "openclaw.json")
    env["OPENCLAW_LOG_DIR"] = str(STATE / "logs")
    env["AGENTLABS_PYTHON"] = sys.executable
    proxy_token = STATE / "model-proxy-token"
    if not proxy_token.exists():
        proxy_token.write_text(secrets.token_urlsafe(36), encoding="utf-8")
    env["AGENTLABS_MODEL_TOKEN"] = proxy_token.read_text(encoding="utf-8").strip()
    distribution = STATE / "distribution.json"
    env["AGENTLABS_NATIVE_MODE"] = (
        json.loads(distribution.read_text(encoding="utf-8"))["mode"]
        if distribution.exists()
        else "lean"
    )
    return env


def make_config(state, mode, env):
    cheap = "lab-openai/gpt-6-luna"
    strong = "lab-openai/gpt-6.1-sol"
    if mode in {"hybrid", "free"}:
        model = env.get("GATEWAY_MODEL", "")
        if not model or not model.endswith(":free"):
            raise ValueError(
                "Set GATEWAY_MODEL to a tool-capable :free model before Hybrid/Free setup. No paid fallback."
            )
        cheap = "lab-free/" + model.removeprefix("openrouter/")
        if mode == "free":
            strong = cheap
    roster = roles()
    children = [r["id"] for r in roster if r["id"] != "director"]
    entries = {}
    for role in roster:
        agent_id = role["id"]
        director = agent_id == "director"
        model = strong if agent_id in {"methods", "review-chair"} else cheap
        tools = [
            "web_fetch",
            "lab_inspect",
            "lab_read",
            "lab_repo_list",
            "lab_repo_tree",
            "lab_repo_read",
            "lab_repo_search",
        ]
        if director:
            tools += [
                "agents_list",
                "sessions_spawn",
                "sessions_yield",
                "subagents",
                "lab_begin",
                "lab_execute",
                "lab_rework",
                "lab_budget",
            ]
        if agent_id in {"literature", "methods", "experiment", "analysis", "writing"}:
            tools += ["lab_submit"]
        if agent_id == "literature":
            tools += ["lab_search"]
        if agent_id.startswith("review-"):
            tools += ["lab_decide" if agent_id == "review-chair" else "lab_review"]
        entries[agent_id] = {
            "name": "AgentLabs" if director else role["name"],
            "description": role["department"],
            "workspace": str(state / "workspaces" / agent_id),
            "agentDir": str(state / "agents" / agent_id / "agent"),
            "model": {"primary": model, "fallbacks": []},
            "modelPolicy": {"allow": [model]},
            "skills": [],
            "subagents": {"allowAgents": children if director else [], "requireAgentId": True},
            "tools": {
                "profile": "minimal",
                "alsoAllow": tools,
                "deny": ["exec", "process", "browser", "message", "cron", "gateway"],
            },
        }
    return {
        "meta": {"lastTouchedVersion": NATIVE_PIN["version"]},
        "gateway": {
            "mode": "local",
            "bind": "loopback",
            "port": PORT,
            "auth": {"mode": "token", "token": "${AGENTLABS_NATIVE_TOKEN}"},
            "controlUi": {"enabled": True, "experimental": {"customPlugins": True}},
            "terminal": {"enabled": False},
            "tailscale": {"mode": "off"},
            "tools": {"deny": ["lab_execute", "lab_rework"]},
        },
        "agents": {
            "ownership": "explicit",
            "defaults": {
                "systemAgent": {"agentId": "director"},
                "authInheritance": {"agentId": "director"},
                "model": {"primary": cheap, "fallbacks": []},
                "models": {
                    m: {"params": {"maxTokens": 4000, "transport": "sse"}}
                    for m in sorted({cheap, strong})
                },
                "utilityModel": "",
                "thinkingDefault": "low",
                "timeoutSeconds": 240,
                "skipBootstrap": True,
                "bootstrapMaxChars": 12000,
                "heartbeat": {"every": "0m"},
                "maxConcurrent": 3,
                "subagents": {
                    "maxSpawnDepth": 1,
                    "maxConcurrent": 3,
                    "maxChildrenPerAgent": 3,
                    "runTimeoutSeconds": 180,
                    "requireAgentId": True,
                },
            },
            "entries": entries,
        },
        "tools": {
            "profile": "minimal",
            "fs": {"workspaceOnly": True},
            "elevated": {"enabled": False},
            "subagents": {
                "tools": {
                    "allow": [
                        "web_fetch",
                        "session_status",
                        "lab_inspect",
                        "lab_read",
                        "lab_submit",
                        "lab_search",
                        "lab_review",
                        "lab_decide",
                        "lab_repo_list",
                        "lab_repo_tree",
                        "lab_repo_read",
                        "lab_repo_search",
                    ]
                }
            },
        },
        "plugins": {
            "allow": ["openai", "openrouter", "web-readability", "agentlabs-research"],
            "load": {"paths": [str(ROOT / "native" / "plugin")]},
            "entries": {
                "agentlabs-research": {
                    "enabled": True,
                    "hooks": {"allowConversationAccess": True, "allowPromptInjection": True},
                }
            },
            "slots": {"memory": "none"},
        },
        "logging": {"file": str(state / "logs" / "openclaw.log")},
        "browser": {"enabled": False},
        "cron": {"enabled": False},
        "models": {
            "catalogRefresh": {"enabled": False},
            "providers": model_providers(cheap, strong),
        },
        "update": {"checkOnStart": False},
    }


def model_providers(cheap, strong):
    from backend.catalog import MODELS

    providers = {}
    for ref in sorted({cheap, strong}):
        provider, model = ref.split("/", 1)
        free = provider == "lab-free"
        rates = {"input": 0, "output": 0} if free else MODELS[model]
        entry = providers.setdefault(
            provider,
            {
                "baseUrl": f"http://127.0.0.1:{MODEL_PORT}/{'free' if free else 'openai'}/v1",
                "api": "openai-completions" if free else "openai-responses",
                "apiKey": "${AGENTLABS_MODEL_TOKEN}",
                "models": [],
            },
        )
        entry["models"].append(
            {
                "id": model,
                "name": model,
                "reasoning": not free,
                "input": ["text"],
                "contextWindow": 32768,
                "maxTokens": 4000,
                "cost": {
                    "input": rates["input"],
                    "output": rates["output"],
                    "cacheRead": rates["input"],
                    "cacheWrite": rates["input"],
                },
            }
        )
    return providers


def setup(mode="lean", refresh_contracts=False):
    env = environment()
    config = make_config(STATE, mode, env)
    common = (ROOT / "native" / "COMMON.md").read_text(encoding="utf-8")
    for role in roles():
        workspace = Path(config["agents"]["entries"][role["id"]]["workspace"])
        workspace.mkdir(parents=True, exist_ok=True)
        instruction = common + "\n\n# Your assignment\n" + role["name"] + "\n" + role["brief"]
        if role["id"] == "director":
            instruction += "\n\n" + (ROOT / "native" / "DIRECTOR.md").read_text(encoding="utf-8")
        # Preserve locally edited instructions on subsequent setup.
        files = {
            "AGENTS.md": instruction,
            "IDENTITY.md": f"# Identity\n- Name: {config['agents']['entries'][role['id']]['name']}\n- Role: {role['department']}\n",
            "USER.md": "# User preferences\nVietnamese. AI/ML research. Target API budget $10–20/month. Chat normally; research only on explicit assignment.\n",
        }
        for name, text in files.items():
            target = workspace / name
            if refresh_contracts and target.exists():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
                shutil.copy2(target, workspace / f"{name}.backup-{stamp}")
            if refresh_contracts or not target.exists():
                target.write_text(text, encoding="utf-8")
    path = STATE / "openclaw.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        for key in ("ui",):
            if key in previous:
                config[key] = previous[key]
        config["meta"] = {**previous.get("meta", {}), "lastTouchedVersion": NATIVE_PIN["version"]}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        shutil.copy2(path, STATE / f"openclaw-backup-{stamp}.json")
    staged = path.with_suffix(".staged.json")
    staged.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    staged.replace(path)
    (STATE / "distribution.json").write_text(
        json.dumps(
            {
                "mode": mode,
                "upstream": NATIVE_PIN,
                "stage": "native-research-plugin-with-budget-proxy",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    env["AGENTLABS_NATIVE_MODE"] = mode
    print(
        f"Native OpenClaw profile: {STATE}; {len(roles())} agents; UI http://127.0.0.1:{PORT}/; mode {mode}"
    )
    return env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=[
            "setup",
            "install",
            "start",
            "validate",
            "status",
            "agents",
            "dashboard",
            "budget",
            "repo-add",
            "repo-list",
        ],
    )
    parser.add_argument("--mode", choices=["lean", "hybrid", "free"], default="lean")
    parser.add_argument(
        "--refresh-contracts",
        action="store_true",
        help="Back up existing role contracts and replace them with the current distribution contracts",
    )
    parser.add_argument("--repo-name")
    parser.add_argument("--repo-path")
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Save dashboard handoff locally without launching a browser",
    )
    args = parser.parse_args()
    if args.action in {"setup", "install"}:
        for port in (PORT, MODEL_PORT):
            try:
                connection = socket.create_connection(("127.0.0.1", port), timeout=0.3)
            except OSError:
                pass
            else:
                connection.close()
                raise SystemExit(
                    "Stop the running AgentLabs terminal before changing its native profile/runtime."
                )
    env = (
        setup(args.mode, args.refresh_contracts)
        if args.action == "setup" or not (STATE / "openclaw.json").exists()
        else environment()
    )
    if args.action == "setup":
        return
    if args.action == "install":
        npm = shutil.which("npm.cmd", path=env["PATH"])
        npm_cli = Path(npm).parent / "node_modules/npm/bin/npm-cli.js" if npm else None
        if not npm_cli or not npm_cli.exists():
            raise SystemExit("npm.cmd and its npm CLI entrypoint are required")
        destination = ROOT.parent / "work/openclaw-native-runtime"
        destination.mkdir(parents=True, exist_ok=True)
        for name in ("package.json", "package-lock.json"):
            shutil.copy2(ROOT / "native/runtime" / name, destination / name)
        subprocess.run(
            [
                str(runtime.node_binary()),
                str(npm_cli),
                "ci",
                "--prefix",
                str(destination),
                "--omit=dev",
                "--no-audit",
                "--no-fund",
            ],
            env=env,
            cwd=ROOT,
            check=True,
        )
        setup(args.mode)
        return
    if args.action == "status":
        result = readiness(env)
        print(json.dumps(result, indent=2))
        if not result["ok"]:
            raise SystemExit(1)
        return
    if args.action in {"repo-add", "repo-list"}:
        path = STATE / "repos.json"
        repos = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if args.action == "repo-add":
            import re

            if (
                not args.repo_name
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.repo_name)
                or not args.repo_path
            ):
                raise SystemExit("repo-add requires --repo-name alias and --repo-path directory")
            directory = Path(args.repo_path).resolve(strict=True)
            if not directory.is_dir() or directory == Path(directory.anchor):
                raise SystemExit("Choose a project directory, not an entire drive")
            repos[args.repo_name] = str(directory)
            path.write_text(json.dumps(repos, indent=2), encoding="utf-8")
        print(json.dumps(repos, indent=2))
        return
    if args.action == "budget":
        from scripts.native_proxy import Ledger

        print(
            json.dumps(
                Ledger(
                    STATE / "model-budget.sqlite",
                    env.get("MONTHLY_BUDGET_USD", 15),
                    env.get("NATIVE_DAILY_BUDGET_USD", 1),
                    env.get("NATIVE_FREE_DAILY_CALLS", 30),
                ).summary(),
                indent=2,
            )
        )
        return
    commands = {
        "start": ["gateway", "run", "--port", str(PORT), "--bind", "loopback"],
        "validate": ["config", "validate"],
        "status": ["gateway", "health"],
        "agents": ["agents", "list", "--json"],
        "dashboard": ["dashboard", "--json"],
    }
    command = [str(runtime.node_binary()), str(cli_path()), *commands[args.action]]
    if args.action == "dashboard":
        # Do not print browser bootstrap/shared credentials into logs or chat.
        result = subprocess.run(
            command, env=env, cwd=ROOT, capture_output=True, text=True, check=True
        )
        data = json.loads(result.stdout)
        if not data.get("browserUrl"):
            raise SystemExit(
                "Gateway did not return a browser handoff. Start the native gateway first."
            )
        (STATE / "dashboard-link.json").write_text(json.dumps(data), encoding="utf-8")
        if not args.no_open:
            import webbrowser

            webbrowser.open(data["browserUrl"])
        print("Native UI handoff saved locally; credentials not printed.")
        return
    proxy = None
    try:
        if args.action == "start":
            import httpx

            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", MODEL_PORT))
                except OSError as exc:
                    raise SystemExit(
                        f"Model proxy port {MODEL_PORT} is busy; stop the existing AgentLabs terminal before restarting."
                    ) from exc
            proxy = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "scripts.native_proxy:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(MODEL_PORT),
                    "--no-access-log",
                ],
                env=env,
                cwd=ROOT,
            )
            ready = False
            for _ in range(100):
                if proxy.poll() is not None:
                    break
                try:
                    response = httpx.get(
                        f"http://127.0.0.1:{MODEL_PORT}/health",
                        headers={"Authorization": "Bearer " + env["AGENTLABS_MODEL_TOKEN"]},
                        timeout=0.5,
                        trust_env=False,
                    )
                    ready = response.status_code == 200
                    if ready:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            if not ready:
                raise SystemExit(
                    "Native model proxy did not become ready; Gateway was not started."
                )
            # Upstream credentials stay in the proxy process. Native agents can
            # only select their exact configured loopback model route.
            env = {
                k: v
                for k, v in env.items()
                if k
                not in {
                    "OPENAI_API_KEY",
                    "OPENROUTER_API_KEY",
                    "GATEWAY_API_KEY",
                    "ANTHROPIC_API_KEY",
                }
            }
        subprocess.run(command, env=env, cwd=ROOT, check=True)
    except KeyboardInterrupt:
        pass
    finally:
        if proxy is not None and proxy.poll() is None:
            proxy.terminate()
            try:
                proxy.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proxy.kill()
                proxy.wait()


if __name__ == "__main__":
    main()
