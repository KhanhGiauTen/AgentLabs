# Developing AgentLabs

AgentLabs is a local research harness. Keep workflow control, scientific evidence and model capabilities separate: an agent's fluent explanation is not proof that a tool ran or a claim is true.

## Development setup

1. Install Python 3.11+ and Node 24 compatible with the pinned frontend dependencies.
2. Run `setup.ps1` on Windows, or create a Python venv and install `requirements-dev.txt`, then `npm ci` in `frontend` on another OS.
3. Run `python -m uvicorn backend.app:app --host 127.0.0.1 --port 8765` from the repository root. For hot frontend development run `npm run dev` in `frontend`; Vite proxies `/api` to port 8765.
4. Start with demo mode. No API key or Docker is needed for the test suite.

## Validation

```text
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
cd frontend
npm ci --no-audit --no-fund
npm run build
```

On this machine, set TEMP/TMP or `--basetemp` to a new directory on D if the default Windows temp path has permission restrictions. CI runs the harness tests and frontend build without provider keys.

## Change contracts

- Put role/model/tool ownership in `backend/catalog.py`, `providers.py` and `tools.py`. Review identities are server-owned.
- Change graph routing in `backend/workflow.py`. Any new side effect must have an explicit owner, budget, recovery behavior and test.
- Preserve reviewer isolation and the barrier before Chair. A new reviewer must not gain peer-report access accidentally.
- Keep draft/evidence/quality labels honest. Do not replace missing evidence with fabricated demo results.
- Pin dependency changes deliberately, update lock snapshots where appropriate and record verification limits.
- Never commit `.env`, local datasets, runtime state, model weights, dependency directories or API logs containing secrets.
- Avoid editing the cloned OpenClaw source or installed package to make an integration work. Prefer the documented public API and a pinned release.

See `docs/ARCHITECTURE.md` for the current system, `docs/VALIDATION.md` for what was tested, and `docs/ROADMAP.md` for the next milestones. Discuss broader changes in an issue/PR before expanding capabilities.
