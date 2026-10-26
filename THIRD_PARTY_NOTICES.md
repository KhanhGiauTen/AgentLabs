# Third-party references and dependencies

AgentLabs uses third-party packages through their published distribution interfaces. Their licenses and notices remain applicable; this file is an inventory, not a replacement for those licenses.

| Project | Relationship |
| --- | --- |
| LangGraph / LangChain Core | Installed orchestration/checkpoint dependencies; upstream MIT licenses |
| FastAPI, React, Vite, lucide-react, react-markdown, remark-gfm | Installed API/frontend packages; see package distributions for notices |
| HTTPX, pypdf, python-dotenv, defusedxml, Uvicorn | Installed Python dependencies; see distribution licenses |
| SQLite | Storage engine via Python/runtime |
| OpenClaw | Primary separately installed MIT-licensed host, native UI and agent runtime, pinned release; not vendored in this repository |
| AgentLaboratory | Architecture/reference source cloned separately, MIT; no upstream source copied into AgentLabs |
| AI Scientist v2, LiteLLM, MLflow | Research/design references or future integration candidates; not integrated unless explicitly documented |

TypeBox 1.3.34 is the native plugin schema dependency (MIT). OpenClaude is a separately cloned read-only reference. Its LICENSE NOTICE states that underlying source derives from proprietary Claude Code and is not authorized for redistribution. AgentLabs does not install, execute, copy or distribute that source. See the pinned notice at https://github.com/Twigpine/openclaude/blob/cb4a72bf1c14cd754e545b985a38a53938dda656/LICENSE.

Native design and source boundaries: `docs/NATIVE_RESEARCH_DESIGN.md`. Prototype V1 boundaries: `docs/ARCHITECTURE.md` and `docs/OPENCLAW.md`.
