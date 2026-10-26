# Third-party references and dependencies

AgentLabs uses third-party packages through their published distribution interfaces. Their licenses and notices remain applicable; this file is an inventory, not a replacement for those licenses.

| Project | Relationship |
| --- | --- |
| LangGraph / LangChain Core | Installed orchestration/checkpoint dependencies; upstream MIT licenses |
| FastAPI, React, Vite, lucide-react, react-markdown, remark-gfm | Installed API/frontend packages; see package distributions for notices |
| HTTPX, pypdf, python-dotenv, defusedxml, Uvicorn | Installed Python dependencies; see distribution licenses |
| SQLite | Storage engine via Python/runtime |
| OpenClaw | Optional separately installed MIT-licensed local gateway, pinned release; not vendored in this repository |
| AgentLaboratory | Architecture/reference source cloned separately, MIT; no upstream source copied into AgentLabs |
| AI Scientist v2, LiteLLM, MLflow | Research/design references or future integration candidates; not integrated unless explicitly documented |

OpenClaude source is not included. The current design and source boundaries are documented in `docs/ARCHITECTURE.md` and `docs/OPENCLAW.md`.
