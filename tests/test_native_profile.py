import json

import pytest
import httpx

from scripts import native_lab


def test_native_runtime_refuses_unreviewed_version(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    package = tmp_path / "work/openclaw-native-runtime/node_modules/openclaw"
    package.mkdir(parents=True)
    (package / "openclaw.mjs").write_text("// fixture")
    (package / "package.json").write_text(json.dumps({"version": "0.0.0"}))
    monkeypatch.setattr(native_lab, "ROOT", project)
    with pytest.raises(SystemExit, match="reviewed pin"):
        native_lab.cli_path()


def test_native_installer_lock_and_sdk_peer_match_reviewed_pin():
    root = native_lab.ROOT
    manifest = json.loads((root / "native/runtime/package.json").read_text())
    lock = json.loads((root / "native/runtime/package-lock.json").read_text())
    plugin = json.loads((root / "native/plugin/package.json").read_text())
    pin = native_lab.NATIVE_PIN
    assert manifest["dependencies"]["openclaw"] == pin["version"]
    assert plugin["peerDependencies"]["openclaw"] == pin["version"]
    assert plugin["openclaw"]["compat"]["minGatewayVersion"] == pin["version"]
    assert lock["packages"]["node_modules/openclaw"]["version"] == pin["version"]
    assert lock["packages"]["node_modules/openclaw"]["integrity"] == pin["runtime_integrity"]


def test_native_status_requires_every_agent_not_just_gateway_health():
    def reply(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True, "paid_credential_configured": False})
        args = json.loads(request.content)
        return httpx.Response(
            400 if args["agentId"] == "review-novelty" else 200, json={"ok": True}
        )

    result = native_lab.readiness(
        {"AGENTLABS_NATIVE_TOKEN": "synthetic-gateway", "AGENTLABS_MODEL_TOKEN": "synthetic-proxy"},
        httpx.MockTransport(reply),
    )
    assert not result["ok"]
    assert result["agents_ready"] == 9
    assert next(a for a in result["agents"] if a["id"] == "review-novelty")["ready"] is False


def test_native_roster_isolated_and_delegation_cannot_recurse(tmp_path):
    config = native_lab.make_config(tmp_path, "lean", {})
    entries = config["agents"]["entries"]
    assert len(entries) == 10
    assert len({r["workspace"] for r in entries.values()}) == 10
    assert len({r["agentDir"] for r in entries.values()}) == 10
    assert config["gateway"]["bind"] == "loopback"
    assert config["gateway"]["controlUi"]["enabled"]
    assert config["gateway"]["controlUi"]["experimental"]["customPlugins"] is True
    assert (
        config["plugins"]["entries"]["agentlabs-research"]["hooks"]["allowConversationAccess"]
        is True
    )
    assert config["meta"]["lastTouchedVersion"] == native_lab.NATIVE_PIN["version"]
    assert config["tools"]["fs"]["workspaceOnly"]
    assert config["agents"]["defaults"]["subagents"]["maxSpawnDepth"] == 1
    assert set(entries["director"]["subagents"]["allowAgents"]) == set(entries) - {"director"}
    for agent_id, role in entries.items():
        assert role["model"]["fallbacks"] == []
        assert "exec" in role["tools"]["deny"]
        if agent_id != "director":
            assert role["subagents"]["allowAgents"] == []
            assert "sessions_spawn" not in role["tools"]["alsoAllow"]


def test_free_native_profile_never_introduces_paid_model(tmp_path):
    with pytest.raises(ValueError, match="No paid fallback"):
        native_lab.make_config(tmp_path, "hybrid", {})
    config = native_lab.make_config(tmp_path, "free", {"GATEWAY_MODEL": "example/model:free"})
    assert set(config["agents"]["defaults"]["models"]) == {"lab-free/example/model:free"}
    assert all(
        r["model"]["primary"].endswith(":free") for r in config["agents"]["entries"].values()
    )
    hybrid = native_lab.make_config(tmp_path, "hybrid", {"GATEWAY_MODEL": "example/model:free"})
    paid = {
        name
        for name, role in hybrid["agents"]["entries"].items()
        if not role["model"]["primary"].endswith(":free")
    }
    assert paid == {"methods", "review-chair"}
    for role in hybrid["agents"]["entries"].values():
        assert role["modelPolicy"]["allow"] == [role["model"]["primary"]]
    assert set(config["models"]["providers"]) == {"lab-free"}
    assert config["gateway"]["tools"]["deny"] == ["lab_execute", "lab_rework"]


def test_native_setup_keeps_user_instructions_and_credentials_out_of_config(tmp_path, monkeypatch):
    monkeypatch.setattr(native_lab, "STATE", tmp_path)
    monkeypatch.setattr(
        native_lab.runtime,
        "environment",
        lambda: {"OPENAI_API_KEY": "synthetic-credential-never-in-config"},
    )
    native_lab.setup()
    contract = tmp_path / "workspaces" / "director" / "AGENTS.md"
    assert "sessions_spawn" in contract.read_text(encoding="utf-8")
    contract.write_text("User customized this contract", encoding="utf-8")
    first_token = (tmp_path / "gateway-token").read_text()
    native_lab.setup()
    assert contract.read_text() == "User customized this contract"
    assert (tmp_path / "gateway-token").read_text() == first_token
    assert list(tmp_path.glob("openclaw-backup-*.json"))
    raw = (tmp_path / "openclaw.json").read_text()
    assert first_token not in raw
    assert "synthetic-credential-never-in-config" not in raw
    assert json.loads(raw)["gateway"]["auth"]["token"] == "${AGENTLABS_NATIVE_TOKEN}"
    assert json.loads(raw)["meta"]["lastTouchedVersion"] == native_lab.NATIVE_PIN["version"]
    env = native_lab.environment()
    assert env["OPENCLAW_GATEWAY_TOKEN"] == first_token
    assert env["OPENCLAW_STATE_DIR"] == str(tmp_path)
