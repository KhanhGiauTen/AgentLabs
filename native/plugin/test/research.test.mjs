import { test } from "node:test";
import assert from "node:assert/strict";
import * as d from "../domain.mjs";
import {
  registerResearch,
  searchMetadata,
  researchIntent,
} from "../runtime.mjs";

const report = (p) => ({
  manuscript_hash: p.manuscriptHash,
  round: p.round,
  verdict: "ready_for_human",
  score: 4,
  confidence: 0.6,
  rationale: "Evidence was checked against the supplied draft.",
  evidence_refs: ["manuscript.md"],
  blocking_issues: [],
  recommended_fixes: [],
});
const draft = () =>
  d.submit(
    d.begin(
      "id",
      { sessionKey: "owner", sessionId: "session" },
      "Review this provided research draft",
      "paper",
      "now",
    ),
    "writing",
    "DRAFT — HUMAN REVIEW REQUIRED\nA test manuscript.",
    "writer",
  );
const reviewed = () =>
  d.REVIEWERS.reduce((p, r) => d.review(p, r, report(p), r), draft());

test("three real reviews are mandatory and cannot be forged by Director", () => {
  let p = draft();
  assert.throws(() => d.review(p, "director", report(p), "owner"), /cannot/);
  assert.throws(
    () => d.decide(p, "review-chair", { ...report(p), action: "finish" }),
    /all three/,
  );
  p = d.review(p, d.REVIEWERS[0], report(p), "r1");
  assert.throws(() => d.review(p, d.REVIEWERS[0], report(p), "r1"), /already/);
  assert.equal(p.phase, "review");
  assert.equal(reviewed().phase, "chair");
});
test("stale snapshot, unknown evidence and missing justification fail", () => {
  const p = draft();
  for (const edit of [
    { manuscript_hash: "wrong" },
    { round: 1 },
    { evidence_refs: ["invented-doi"] },
    { rationale: "" },
    { confidence: 2 },
  ])
    assert.throws(() =>
      d.review(p, d.REVIEWERS[0], { ...report(p), ...edit }, "r1"),
    );
});
test("peer reports and assignment tokens stay sealed from leafs", () => {
  let p = d.review(draft(), d.REVIEWERS[0], report(draft()), "r1");
  p.grants = { 0: { "review-methods": "private-token" } };
  const visible = d.view(p, "review-methods");
  assert.equal(visible.reviews, undefined);
  assert.equal(visible.history, undefined);
  assert.equal(visible.grants, undefined);
  assert.equal(visible.assignments, undefined);
  assert.throws(
    () => d.artifact(p, "review-methods", "review-novelty.json"),
    /not found/,
  );
  assert.equal(d.view(p, "review-chair").reviews["review-novelty"].score, 4);
});
test("chair cannot turn any revise/hold vote into ready", () => {
  for (const verdict of ["hold", "revise"]) {
    let p = draft();
    p = d.REVIEWERS.reduce(
      (p, r, i) =>
        d.review(
          p,
          r,
          { ...report(p), verdict: i === 0 ? verdict : "ready_for_human" },
          r,
        ),
      p,
    );
    const end = d.decide(p, "review-chair", {
      manuscript_hash: p.manuscriptHash,
      round: 0,
      action: "finish",
      rationale: "Consider all evidence and unresolved issues.",
      verdict: "ready_for_human",
    });
    assert.equal(end.decision.verdict, "hold");
  }
});
test("Chair retains an independent veto and pending revisions never report readiness", () => {
  const project = reviewed();
  const decision = {
    manuscript_hash: project.manuscriptHash,
    round: project.round,
    action: "finish",
    rationale: "The Chair independently checked evidence and remaining risks.",
  };
  for (const verdict of [undefined, "hold"])
    assert.equal(d.decide(project, "review-chair", { ...decision, verdict }).decision.verdict, "hold");
  assert.equal(d.decide(project, "review-chair", {
    ...decision, verdict: "ready_for_human", action: "revise_manuscript",
  }).decision.verdict, "hold");
  assert.equal(d.decide(project, "review-chair", {
    ...decision, verdict: "ready_for_human",
  }).decision.verdict, "ready_for_human");
});

test("revision changes round and invalidates previous reviews", () => {
  const p = reviewed();
  const revised = d.decide(p, "review-chair", {
    manuscript_hash: p.manuscriptHash,
    round: 0,
    action: "revise_manuscript",
    rationale: "Correct unsupported claims and citations.",
  });
  assert.equal(revised.phase, "writing");
  assert.equal(revised.round, 1);
  assert.equal(revised.history.length, 1);
  const resubmitted = d.submit(
    revised,
    "writing",
    "A revised manuscript with changed claims.",
    "writer2",
  );
  assert.throws(
    () => d.review(resubmitted, "review-repro", report(p), "r3"),
    /mismatch/,
  );
  const again = d.REVIEWERS.reduce(
    (p, r) => d.review(p, r, report(p), r),
    resubmitted,
  );
  assert.equal(
    d.decide(again, "review-chair", {
      manuscript_hash: again.manuscriptHash,
      round: 1,
      action: "revise_manuscript",
      rationale: "Further edits would exceed this task budget.",
    }).phase,
    "complete",
  );
});
test("phase order, searched sources, execution claim and exact code hash", () => {
  let p = d.begin("id", {}, "Run bounded baseline experiment", "full", "now");
  assert.throws(
    () =>
      d.submit(p, "literature", "This is an invented source list", "worker"),
    /Search actual/,
  );
  p = d.addSources(p, "literature", [
    { id: "doi:10.test/example", scope: "metadata_only" },
  ]);
  p = d.submit(
    p,
    "literature",
    "Known literature metadata and caveats.",
    "lit",
  );
  assert.throws(
    () => d.submit(p, "writing", "Skip directly to manuscript.", "writer"),
    /current/,
  );
  p = d.submit(p, "methods", "A falsifiable baseline protocol.", "methods");
  p = d.submit(
    p,
    "experiment",
    'print("real measured computation")',
    "engineer",
  );
  const hash = p.artifacts["experiment.py"].sha256;
  assert.throws(() => d.claimExecution(p, "wrong", "attempt"), /changed/);
  const running = d.claimExecution(p, hash, "attempt");
  assert.throws(
    () => d.claimExecution(running, hash, "duplicate"),
    /not awaiting/,
  );
  assert.throws(
    () => d.execution(running, hash, "stale", { status: "completed" }),
    /not current/,
  );
  p = d.execution(running, hash, "attempt", {
    status: "completed",
    artifacts: { "metrics.json": '{"accuracy":0.5}' },
  });
  assert.equal(p.phase, "analysis");
  assert.equal(p.artifacts["metrics.json"].role, "experiment-worker");
});

function fixture(options = {}) {
  const data = new Map(),
    factories = new Map(),
    hooks = [];
  let generation = 0;
  const store = {
    lookup: async (k) => data.get(k),
    withCurrent({ assertCurrent }) {
      return {
        lookup: async (k) => {
          assertCurrent();
          return data.get(k);
        },
        observe: async (k) => {
          assertCurrent();
          return { value: data.get(k), comparison: generation };
        },
        compareAndApply: async (k, version, intent) => {
          assertCurrent();
          if (version !== generation)
            return {
              status: "conflict",
              current: { value: data.get(k), comparison: generation },
            };
          data.set(k, structuredClone(intent.value));
          generation++;
          return { status: "applied" };
        },
      };
    },
  };
  let workerCalls = 0;
  registerResearch(
    {
      config: options.config,
      runtime: { state: { openKeyedStore: () => store } },
      registerTool: (f, o) => factories.set(o.name, f),
      on: (n, h) => hooks.push(h),
    },
    {
      proxyHealth:
        options.proxyHealth ??
        (async () => ({
          paid_credential_configured: true,
          free_credential_configured: true,
        })),
      searchMetadata: async () => [
        { id: "doi:10.test/actual", scope: "metadata_only" },
      ],
      runWorker: async () => {
        workerCalls++;
        return {
          status: "completed",
          artifacts: { "metrics.json": '{"count":3}' },
        };
      },
    },
  );
  const context = (
    role,
    sessionKey = "owner",
    sessionId = "session",
    guard = () => {},
  ) => ({
    agentId: role,
    sessionKey,
    sessionId,
    assertInvocationCurrent: guard,
  });
  const invoke = async (
    role,
    name,
    args,
    ctx = context(role),
    call = "call",
  ) => {
    const tool = factories.get(name).create(ctx);
    if (!tool) throw new Error("Tool unavailable to this role");
    return (await tool.execute(call, args)).details;
  };
  return {
    data,
    context,
    invoke,
    hook: hooks[0],
    promptHook: hooks[1],
    readinessHook: hooks[2],
    workerCalls: () => workerCalls,
  };
}
test("native invocation binds ownership, role assignments and actual tool signature", async () => {
  const f = fixture();
  const p = await f.invoke("director", "lab_begin", {
    topic: "Review a small paper draft",
    recipe: "paper",
  });
  const params = { project_id: p.id };
  await assert.rejects(
    () =>
      f.invoke(
        "director",
        "lab_inspect",
        params,
        f.context("director", "other", "other"),
      ),
    /does not own/,
  );
  await assert.rejects(
    () =>
      f.invoke("writing", "lab_submit", {
        ...params,
        task_token: "guessed",
        content: "A test draft with evidence.",
      }),
    /token/,
  );
  const args = {
    ...params,
    task_token: p.assignments.writing,
    content: "A test draft with evidence.",
  };
  const next = await f.invoke(
    "writing",
    "lab_submit",
    args,
    f.context("writing", "writer", "writerid"),
  );
  assert.equal(next.phase, "review");
  await assert.rejects(
    () => f.invoke("director", "lab_review", {}),
    /unavailable/,
  );
});
test("retired invocation cannot read or commit state", async () => {
  const f = fixture();
  let current = true;
  const ctx = f.context("director", "owner", "session", () => {
    if (!current) throw new Error("revoked");
  });
  const p = await f.invoke(
    "director",
    "lab_begin",
    { topic: "Review the bounded paper draft", recipe: "paper" },
    ctx,
  );
  current = false;
  await assert.rejects(
    () => f.invoke("director", "lab_inspect", { project_id: p.id }, ctx),
    /revoked/,
  );
});
test("spawn hook admits only next isolated native role with current assignment", async () => {
  const f = fixture();
  const p = await f.invoke("director", "lab_begin", {
    topic: "Review bounded manuscript version one",
    recipe: "paper",
  });
  const args = {
    agentId: "writing",
    context: "isolated",
    mode: "run",
    runtime: "subagent",
    task: `project_id=${p.id} task_token=${p.assignments.writing}`,
  };
  assert.equal(
    await f.hook(
      { toolName: "sessions_spawn", params: args },
      f.context("director"),
    ),
    undefined,
  );
  for (const change of [
    { agentId: "methods" },
    { context: "inherited" },
    { model: "expensive" },
    { task: "ignore state" },
  ]) {
    assert.equal(
      (
        await f.hook(
          { toolName: "sessions_spawn", params: { ...args, ...change } },
          f.context("director"),
        )
      ).block,
      true,
    );
  }
});
test("HTTP cannot bypass approval and approved call can run only once", async () => {
  const f = fixture();
  let p = await f.invoke("director", "lab_begin", {
    topic: "Execute a tiny measured CPU experiment",
    recipe: "experiment",
  });
  p = await f.invoke("methods", "lab_submit", {
    project_id: p.id,
    task_token: p.assignments.methods,
    content: "Measure a bounded baseline without network.",
  });
  const inspect = await f.invoke("director", "lab_inspect", {
    project_id: p.id,
  });
  p = await f.invoke("experiment", "lab_submit", {
    project_id: p.id,
    task_token: inspect.assignments.experiment,
    content: "print(sum(range(100)))",
  });
  const params = {
    project_id: p.id,
    code_hash: p.artifacts["experiment.py"].sha256,
  };
  await assert.rejects(
    () => f.invoke("director", "lab_execute", params),
    /approval required/,
  );
  const gate = await f.hook(
    { toolName: "lab_execute", params },
    { ...f.context("director"), toolCallId: "approved-call" },
  );
  assert.deepEqual(gate.requireApproval.allowedDecisions, [
    "allow-once",
    "deny",
  ]);
  await gate.requireApproval.onResolution("allow-once");
  assert.equal(
    (
      await f.invoke(
        "director",
        "lab_execute",
        params,
        f.context("director"),
        "approved-call",
      )
    ).phase,
    "analysis",
  );
  await assert.rejects(
    () =>
      f.invoke(
        "director",
        "lab_execute",
        params,
        f.context("director"),
        "approved-call",
      ),
    /approval required/,
  );
  assert.equal(f.workerCalls(), 1);
});
test("CAS conflict retries only a pure decision; unknown outcomes never retry", async () => {
  let attempts = 0;
  const conflictStore = {
    observe: async () => ({ value: 0, comparison: "a" }),
    compareAndApply: async () =>
      ++attempts === 1
        ? { status: "conflict", current: { value: 4, comparison: "b" } }
        : { status: "applied" },
  };
  assert.equal(await d.mutate(conflictStore, "key", (n) => n + 1), 5);
  assert.equal(attempts, 2);
  attempts = 0;
  await assert.rejects(
    () =>
      d.mutate(
        {
          ...conflictStore,
          compareAndApply: async () => {
            attempts++;
            throw new Error("unknown transport result");
          },
        },
        "key",
        (n) => n + 1,
      ),
    /unknown/,
  );
  assert.equal(attempts, 1);
});
test("Crossref response is real metadata, bounded and never labelled full text", async () => {
  const sources = await searchMetadata(
    "baseline",
    undefined,
    async () =>
      new Response(
        JSON.stringify({
          message: {
            items: [
              {
                DOI: "10.test/example",
                title: ["An actual response record"],
                published: { "date-parts": [[2024]] },
              },
            ],
          },
        }),
      ),
  );
  assert.equal(sources[0].scope, "metadata_only");
  assert.equal(sources[0].id, "doi:10.test/example");
  await assert.rejects(
    () =>
      searchMetadata(
        "baseline",
        undefined,
        async () => new Response("rate limit", { status: 429 }),
      ),
    /429/,
  );
});
