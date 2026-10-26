"""Dedicated local OpenClaw profile. Never edits the user's global OpenClaw state."""

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT.parent
WORK = BUILD / "work"
STATE = WORK / "openclaw-state"
PIN = json.loads((ROOT / "upstreams.lock.json").read_text(encoding="utf-8"))["openclaw"]
VERSION = PIN["version"]
COMMIT = PIN["commit"]


def node_binary():
    candidates = [
        os.getenv("RESEARCH_NODE"),
        str(
            Path(os.environ.get("USERPROFILE", ""))
            / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
        ),
        shutil.which("node"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            version = (
                subprocess.check_output([candidate, "--version"], text=True).strip().lstrip("v")
            )
            parts = tuple(map(int, version.split(".")[:3]))
            if (parts[0] == 24 and parts >= (24, 22, 1)) or parts >= (26, 12, 1):
                return Path(candidate)
    raise SystemExit(
        "OpenClaw needs Node >=24.22.1 <25 or >=26.12.1. Set RESEARCH_NODE to the supported node executable."
    )


def environment():
    values = dotenv_values(ROOT / ".env")
    env = dict(os.environ)
    env.update({k: v for k, v in values.items() if v})
    node = node_binary()
    env["PATH"] = str(node.parent) + os.pathsep + env.get("PATH", "")
    env["OPENCLAW_STATE_DIR"] = str(STATE)
    env["OPENCLAW_CONFIG_PATH"] = str(STATE / "openclaw.json")
    env["OPENCLAW_LOG_DIR"] = str(STATE / "logs")
    env["OPENROUTER_API_KEY"] = env.get("GATEWAY_API_KEY", "")
    env["npm_config_cache"] = str(WORK / "npm-cache")
    temp = WORK / "tmp"
    temp.mkdir(parents=True, exist_ok=True)
    env["TEMP"] = env["TMP"] = str(temp)
    return env


def setup():
    WORK.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    env_path = ROOT / ".env"
    if not env_path.exists():
        shutil.copyfile(ROOT / ".env.example", env_path)
    values = dotenv_values(env_path)
    if not values.get("OPENCLAW_GATEWAY_TOKEN"):
        text = env_path.read_text(encoding="utf-8")
        token = secrets.token_urlsafe(36)
        import re

        if re.search(r"^OPENCLAW_GATEWAY_TOKEN=.*$", text, flags=re.M):
            text = re.sub(
                r"^OPENCLAW_GATEWAY_TOKEN=.*$", "OPENCLAW_GATEWAY_TOKEN=" + token, text, flags=re.M
            )
        else:
            text += "\nOPENCLAW_GATEWAY_TOKEN=" + token + "\n"
        env_path.write_text(text, encoding="utf-8")
    env = environment()
    cheap = env.get("OPENCLAW_CHEAP_MODEL", "openai/gpt-6-luna")
    models = {
        "openai/gpt-6-luna": {"params": {"maxTokens": 6000}},
        "openai/gpt-6.1-sol": {"params": {"maxTokens": 6000}},
    }
    if cheap.startswith("openrouter/") and cheap.endswith(":free"):
        models[cheap] = {"params": {"maxTokens": 6000}}
    elif cheap != "openai/gpt-6-luna":
        raise SystemExit("Use openai/gpt-6-luna or openrouter/<model>:free for the cheap route.")
    workspace = STATE / "workspace"
    workspace.mkdir(exist_ok=True)
    config = {
        "gateway": {
            "mode": "local",
            "bind": "loopback",
            "port": 18789,
            "auth": {"mode": "token", "token": "${OPENCLAW_GATEWAY_TOKEN}"},
            "http": {
                "endpoints": {
                    "responses": {
                        "enabled": True,
                        "files": {"allowUrl": False},
                        "images": {"allowUrl": False},
                    }
                }
            },
            "controlUi": {"enabled": False},
            "terminal": {"enabled": False},
            "tailscale": {"mode": "off"},
        },
        "agents": {
            "defaults": {
                "model": {"primary": cheap, "fallbacks": []},
                "models": models,
                "utilityModel": "",
                "maxConcurrent": 1,
                "timeoutSeconds": 180,
                "thinkingDefault": "low",
                "skipBootstrap": True,
                "skills": [],
                "heartbeat": {"every": "0m"},
                "compaction": {"enabled": False},
            },
            "entries": {
                "research": {
                    "name": "Research Lab",
                    "workspace": str(workspace),
                    "model": {"primary": cheap, "fallbacks": []},
                    "skills": [],
                    "tools": {"profile": "minimal", "deny": ["*"]},
                }
            },
        },
        "tools": {"profile": "minimal", "deny": ["*"], "elevated": {"enabled": False}},
        "plugins": {"allow": ["openai", "openrouter"], "slots": {"memory": "none"}},
        "logging": {"file": str(STATE / "logs" / "openclaw.log")},
        "browser": {"enabled": False},
        "cron": {"enabled": False},
        "models": {"catalogRefresh": {"enabled": False}},
        "update": {"checkOnStart": False},
    }
    config_path = STATE / "openclaw.json"
    if config_path.exists():
        shutil.copy2(config_path, STATE / "openclaw.previous.json")
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    (WORK / "installation.json").write_text(
        json.dumps(
            {
                "repository": PIN["repository"],
                "tag": PIN["tag"],
                "commit": COMMIT,
                "runtime_package": PIN["runtime_package"],
                "source": str(BUILD / PIN["directory"]),
                "state": str(STATE),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("Dedicated profile prepared. Gateway token stored in .env (not displayed).")
    return env


def cli_path():
    path = WORK / "openclaw-runtime/node_modules/openclaw/openclaw.mjs"
    if not path.exists():
        raise SystemExit("Runtime missing. Run scripts/openclaw.py install first.")
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=["setup", "install", "start", "status", "validate", "version"]
    )
    args = parser.parse_args()
    if args.action == "setup":
        setup()
        return
    env = environment()
    node = node_binary()
    if args.action == "install":
        npm = shutil.which("npm.cmd", path=env["PATH"])
        if not npm:
            raise SystemExit("npm.cmd not found")
        npm_cli = Path(npm).parent / "node_modules/npm/bin/npm-cli.js"
        if not npm_cli.exists():
            raise SystemExit("npm CLI entrypoint missing beside npm.cmd")
        # Use the selected compatible Node explicitly. npm.cmd can otherwise
        # prefer an older node.exe beside itself even when PATH is corrected.
        subprocess.run(
            [
                str(node),
                str(npm_cli),
                "install",
                "--prefix",
                str(WORK / "openclaw-runtime"),
                "--omit=dev",
                "--no-audit",
                "--no-fund",
                "openclaw@" + VERSION,
            ],
            env=env,
            check=True,
        )
        setup()
        return
    commands = {
        "version": ["--version"],
        "validate": ["config", "validate"],
        "status": ["gateway", "health"],
        "start": ["gateway", "run", "--port", "18789", "--bind", "loopback"],
    }
    if args.action in {"start", "validate"} and not (STATE / "openclaw.json").exists():
        env = setup()
    try:
        subprocess.run(
            [str(node), str(cli_path()), *commands[args.action]], env=env, cwd=ROOT, check=True
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
