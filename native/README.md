# Native OpenClaw distribution

OpenClaw owns chat, sessions, streaming and subagents. AgentLabs adds a profile,
research tools/state machine, a private model-budget proxy and a Docker worker.
The original Python/LangGraph/React prototype remains available through `start.ps1`.

The native host is pinned to **2026.10.10-beta.3 / 15dffe52**, an official
prerelease containing the canonical-startup checkpoint repair. Stable 2026.10.7
reproduced agent admission failures after restart here. See
[upstream issue/provenance](https://github.com/openclaw/openclaw/issues/166634).
It is not described as a stable release or automatically updated. The runtime is
installed separately from V1; `native/runtime/package-lock.json` pins dependencies.
State was backed up before the supported schema migration. Downgrading requires a
matching pre-upgrade backup, not an older runtime writing newer databases.

## Quick start (Windows / local only)

```powershell
cd D:\ResearchLab\research-studio
# Fresh install only: .\setup-native.ps1
.\agentlabs.ps1 start
# Another terminal; opens the authenticated native UI without printing tokens:
.\agentlabs.ps1 dashboard
```

Default UI: `http://127.0.0.1:18790`. Model proxy: loopback port 18791.
Ctrl+C in the start terminal stops its owned processes. `openclaw` on PATH may
select another installation/profile; use the AgentLabs launcher for this lab.
Double-click `Start AgentLabs.cmd` starts the same native distribution.

Put `OPENAI_API_KEY` in local `.env` for Lean. No keys were added in development;
opening the UI does not mean a model is configured. Do not use the native
"Connect provider" shortcut to create routes outside the metered profile.

```powershell
.\agentlabs.ps1 setup -Mode hybrid  # requires GATEWAY_API_KEY + tool-capable GATEWAY_MODEL ending :free
.\agentlabs.ps1 setup -Mode free    # all roles free; no paid fallback
.\agentlabs.ps1 setup -Mode lean    # Luna; Sol only for Methods and Chair
.\agentlabs.ps1 validate
.\agentlabs.ps1 agents
.\agentlabs.ps1 status    # probes all 10 agents, not just a listening Gateway
.\agentlabs.ps1 budget
```

Stop the start terminal before changing profiles. Setup backs up config and keeps
local UI preferences. Existing role contracts are preserved unless you request
`setup -RefreshContracts`; that option backs them up before replacing them.

## Chat, code and research

Chat normally with Director. A compact **Chat / Nghiên cứu** toolbar sits above
OpenClaw's built-in composer. Research mode offers four task suggestions:
literature, experiment design, paper review and the full lifecycle. Switching
mode or choosing a suggestion edits the draft only; it preserves the typed text
and never sends automatically. Submit with the ordinary Send button.
**+ Chat mới** opens a native Director conversation directly, without a model call.
The upstream sidebar's New conversation still opens OpenClaw's workspace picker.

The empty Director chat has a simple AI/ML welcome in place of upstream channel
configuration shortcuts. Conversations with messages retain the built-in transcript.
This is a native Control UI contribution using the public SDK contract,
not a separate frontend. The built-in composer retains attachments, draft state,
send/stop and permissions. The profile enables its local custom-plugin UI;
Plugins → Advanced → Customize UI can restore Built-in. The native distribution
selects the AgentLabs composer/welcome again on browser activation. `setup-native.ps1`
builds immutable UI assets using `npm run build:ui` in `native/plugin`; source
edits need that build and a plugin reload/restart. Generated `dist/` is local.

Examples:

Native prompt hooks narrow ordinary chat to read-only/status tools. An explicit
research action opens orchestration tools; an existing project's continuation
can resume its workflow. `RESEARCH: <task>` forces research intent and
`CHAT: <message>` keeps a turn in chat. Ambiguous phrasing remains chat.

- “Giải thích overfitting và data leakage.” — direct chat.
- “Đọc repo qnmln, tìm cách chia train/test và giải thích.” — read-only repo tools, no lab job.
- “Hãy khảo sát ba baseline phù hợp cho đề tài này.” — explicit research, `survey` recipe.
- “Thiết kế và chạy một smoke experiment sklearn; cho tôi duyệt code trước.” — `experiment`, human gate.
- “Viết và phản biện bản nháp từ nội dung tôi cung cấp.” — `paper`, three independent reviewers and Chair.

Register a local project before asking the agent to read it. Replace the example
path with the actual source checkout; registering a runtime/data directory is not
equivalent to registering the repository.

```powershell
.\agentlabs.ps1 repo-add -RepoName qnmln -RepoPath 'D:\actual\path\to\qnmln'
.\agentlabs.ps1 repo-list
```

Repo tools return bounded source text with SHA256 and line references. They reject
traversal, resolved paths outside the registered root, credentials, datasets and
caches. No repo writes, Git mutations or arbitrary host commands are exposed.
Text snippets selected by agents are sent to the configured model API.

Each conversation owns one research project. New conversation starts another.
`lab_inspect` returns phase, artifacts and next roles; workers must submit through
role-bound tools. A final chat response alone does not count as a completed phase.
Three reviews use one manuscript hash/round; reviewers cannot fetch peer reports.
Chair sees all three only after the barrier. A revise/hold vote prevents a ready
verdict. `ready_for_human` is a draft status, not scientific validation.
Chair can independently veto unanimous reviews. `lab_decide` requires an explicit
`verdict: ready_for_human` with `action: finish` to request readiness; omission,
pending work or a Chair hold stays HOLD even when all reviewer votes are positive.

## Experiments

Build the local image only after Docker Desktop is running:

```powershell
docker build -t research-studio-sandbox:local .\sandbox
```

Director shows `experiment.py` and its SHA256, then requests one-time native UI
approval. HTTP tools cannot bypass that gate. Changed code requires new approval.
The worker uses a fixed argv, no network, no API credentials, read-only root,
non-root user, 2 CPU, 1 GB, 120s. It never pulls an image automatically.

This native worker currently imports stdout/stderr, execution metadata and bounded
`metrics.json`. **It does not mount user datasets**, import figures, edit a repo,
use GPU or install packages. Synthetic/sklearn tests are smoke experiments.
Interrupted/unknown work remains marked executing for manual inspection; no
automatic replay. Docker engine was off during development, so actual container
execution and the native approval UI still require an end-to-end pilot.

## Cost and data

All configured model refs use a private loopback proxy. Defaults: $15/month, $1/day,
4000 output tokens/call and 30 free calls/day. SQLite reserves before upstream
dispatch, settles reported usage, and keeps the reservation after uncertain
completion. Free requests consume quota even when their outcome is uncertain.
Monthly/daily dollar periods use UTC+7; free request quota uses UTC.

The ledger is a conservative **local admission estimate**, not the provider's
invoice or an account-wide billing cap. It excludes prototype V1, other tools,
taxes and other accounts. Provider spending controls remain necessary. The proxy
accepts only configured text models, local function tools and full client history;
it rejects paid hosted tools, hidden server history and background generation.
Free mode rejects paid requests and never falls back. The proxy never retries an
upstream request. OpenClaw recovery may issue another request; every such request
is separately admitted/accounted by the proxy. Missing credentials are blocked
before agent execution. Set provider spending limits as an additional control.

Standard text prices used in estimates (USD/1M tokens, checked 2026-10-26):
Luna $0.10 input / $0.50 output; GPT-6.1 Sol $2 input / $10 output.
Cached input is conservatively counted as ordinary input. Source:
[official OpenAI API pricing](https://developers.openai.com/api/docs/pricing).
Example workload assumption: 3M/0.5M Luna input/output tokens plus 2M/0.3M Sol
input/output tokens costs about $7.55 before taxes, uncertainty and other usage.
It is a planning example, not a promised number of papers or tasks per month.

State, credentials, repo allowlist, approvals and ledger stay under
`D:\ResearchLab\work\agentlabs-native`, outside Git. Cloud model calls receive the
necessary chat/tool text. No public listener, tunnel, messaging channel or service
is installed. Back up state only after stopping the lab.

## Validation and remaining work

Unit/contract tests cover phase order, ownership, stale tokens/snapshots, sealed
reviews, bounded revision, one-time approval, code hash, CAS conflicts, read-only
repository boundaries, atomic budget admission and streaming usage. Tests use
fake API responses, not paid models.

Remaining: native research panels/export, PDF evidence ingestion with page spans,
dataset snapshots/mounts, Git worktrees, LaTeX/PDF build, and a measured scientific
pilot against single-agent and AgentLaboratory baselines. The repository contains
working infrastructure; it has not demonstrated autonomous paper quality.
