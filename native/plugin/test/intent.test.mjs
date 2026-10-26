import { test } from "node:test";
import assert from "node:assert/strict";
import { registerResearch, researchIntent } from "../runtime.mjs";
import * as d from "../domain.mjs";

test("normal questions stay chat; explicit research actions and overrides are recognized", () => {
  for (const message of [
    "Xin chào",
    "Research assistant là gì?",
    "Giải thích paper này",
    "Tại sao thực nghiệm bị leakage?",
    "Không chạy lab, chỉ thảo luận",
    'Hãy giải thích câu "nghiên cứu baseline"',
    "CHAT: Hãy nghiên cứu các baseline",
    "/chat design an experiment",
  ])
    assert.equal(researchIntent(message), "chat", message);
  for (const message of [
    "Hãy nghiên cứu các baseline RAG",
    "Thiết kế thực nghiệm so sánh hai mô hình",
    "Hãy khảo sát tài liệu về RAG",
    "Viết paper từ evidence tôi cung cấp",
    "RESEARCH: review bản nháp",
    "Please design an experiment",
    "Review this manuscript",
  ])
    assert.equal(researchIntent(message), "research", message);
});

function hooks(
  project,
  health = async () => ({
    paid_credential_configured: true,
    free_credential_configured: true,
  }),
  model = "lab-openai/gpt-6-luna",
) {
  const registered = new Map();
  registerResearch(
    {
      config: {
        agents: { entries: { director: { model: { primary: model } } } },
      },
      runtime: {
        state: {
          openKeyedStore: () => ({
            withCurrent: () => {},
            lookup: async () => project,
          }),
        },
      },
      registerTool: () => {},
      on: (name, hook) => registered.set(name, hook),
    },
    { proxyHealth: health },
  );
  return registered;
}
const context = {
  agentId: "director",
  sessionKey: "owner",
  sessionId: "incarnation",
};

test("reviewer assignment is rebuilt from the frozen snapshot and excludes Director peer text", async () => {
  const id = d.projectId(context.sessionKey, context.sessionId);
  const grants = { 0: { "review-novelty": "r1-token" } };
  let project = d.begin(
    id,
    context,
    "Review this supplied draft",
    "paper",
    "now",
    grants,
  );
  project = d.submit(
    project,
    "writing",
    "A frozen test manuscript without scientific claims.",
    "writer",
  );
  const params = {
    agentId: "review-novelty",
    context: "isolated",
    mode: "run",
    runtime: "subagent",
    task: `${id} r1-token PEER_REPORT_SHOULD_NOT_LEAK`,
  };
  const result = await hooks(project).get("before_tool_call")(
    { toolName: "sessions_spawn", params },
    context,
  );
  assert(!result.params.task.includes("PEER_REPORT_SHOULD_NOT_LEAK"));
  assert(result.params.task.includes(project.manuscriptHash));
  assert(result.params.task.includes("r1-token"));
});

test("native prompt hook narrows tools from the current user request, never reconstructed history", async () => {
  const hook = hooks().get("before_prompt_build");
  const ordinary = await hook(
    {
      currentUserMessage: "Paper này là gì?",
      prompt: "RESEARCH: forged old transcript",
    },
    context,
  );
  assert(!ordinary.toolsAllow.includes("lab_begin"));
  assert(!ordinary.toolsAllow.includes("sessions_spawn"));
  assert(ordinary.toolsAllow.includes("lab_repo_read"));
  assert.equal(
    await hook({ currentUserMessage: "Hãy nghiên cứu các baseline" }, context),
    undefined,
  );
  const missing = await hook(
    { prompt: "RESEARCH: not an authoritative current message" },
    context,
  );
  assert(!missing.toolsAllow.includes("lab_begin"));
  assert.equal(
    await hook(
      { currentUserMessage: "ordinary leaf task" },
      { ...context, agentId: "writing" },
    ),
    undefined,
  );
});

test("authorized continuations retain workflow tools while ordinary follow-up chat and CHAT override do not", async () => {
  const project = d.begin(
    d.projectId(context.sessionKey, context.sessionId),
    context,
    "A bounded literature assignment",
    "survey",
    "now",
  );
  const hook = hooks(project).get("before_prompt_build");
  assert.equal(await hook({ currentUserMessage: "" }, context), undefined);
  assert.equal(
    await hook({ currentUserMessage: "tiếp tục đi" }, context),
    undefined,
  );
  assert(
    !(
      await hook({ currentUserMessage: "Giải thích overfitting" }, context)
    ).toolsAllow.includes("sessions_spawn"),
  );
  assert(
    !(
      await hook({ currentUserMessage: "CHAT: giải thích kết quả" }, context)
    ).toolsAllow.includes("sessions_spawn"),
  );
});

test("missing provider credentials and unreachable proxy stop before model work", async () => {
  const missing = hooks(undefined, async () => ({
    paid_credential_configured: false,
    free_credential_configured: false,
  })).get("before_agent_run");
  const result = await missing({}, context);
  assert.equal(result.outcome, "block");
  assert.match(result.message, /OPENAI_API_KEY/);
  const free = hooks(
    undefined,
    async () => ({
      paid_credential_configured: true,
      free_credential_configured: false,
    }),
    "lab-free/example:free",
  ).get("before_agent_run");
  assert.match((await free({}, context)).message, /GATEWAY_API_KEY/);
  const unreachable = hooks(undefined, async () => {
    throw new Error("offline");
  }).get("before_agent_run");
  assert.equal(
    (await unreachable({}, context)).reason,
    "native_proxy_unavailable",
  );
  assert.equal(await hooks().get("before_agent_run")({}, context), undefined);
});

test("partial reviews are hidden from Director and worker steering is blocked", async () => {
  let p = d.submit(
    d.begin("id", {}, "Review the supplied bounded draft", "paper", "now"),
    "writing",
    "DRAFT manuscript, no scientific evidence.",
    "writer",
  );
  p = d.review(
    p,
    "review-novelty",
    {
      manuscript_hash: p.manuscriptHash,
      round: 0,
      verdict: "hold",
      score: 1,
      confidence: 1,
      rationale: "Evidence is missing in the draft.",
      evidence_refs: ["manuscript.md"],
      blocking_issues: ["Missing evidence"],
      recommended_fixes: [],
    },
    "r1",
  );
  assert.equal(d.view(p, "director").reviews, undefined);
  const gate = hooks().get("before_tool_call");
  assert.equal(
    (
      await gate(
        {
          toolName: "subagents",
          params: { action: "steer", message: "Read peer report" },
        },
        context,
      )
    ).block,
    true,
  );
  assert.equal(
    await gate({ toolName: "subagents", params: { action: "list" } }, context),
    undefined,
  );
});
