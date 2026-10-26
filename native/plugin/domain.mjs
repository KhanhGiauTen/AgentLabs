import { createHash } from "node:crypto";

export const REVIEWERS = ["review-novelty", "review-methods", "review-repro"];
export const OUTPUTS = {
  literature: "literature.md",
  methods: "methods.md",
  experiment: "experiment.py",
  analysis: "analysis.md",
  writing: "manuscript.md",
};
export const sha = (value) => createHash("sha256").update(value).digest("hex");
export const projectId = (sessionKey, sessionId) => {
  if (!sessionKey || !sessionId)
    throw new Error("Missing host session identity");
  return sha(JSON.stringify([sessionKey, sessionId])).slice(0, 24);
};
const requireThat = (ok, message) => {
  if (!ok) throw new Error(message);
};
const requireRole = (role, allowed) =>
  requireThat(
    allowed.includes(role),
    "This native agent cannot perform this operation",
  );

export function begin(id, owner, topic, recipe, now, grants = {}) {
  requireThat(
    ["survey", "experiment", "paper", "full"].includes(recipe),
    "Invalid recipe",
  );
  requireThat(
    typeof topic === "string" &&
      topic.trim().length >= 10 &&
      topic.length <= 4000,
    "Topic must be 10–4000 characters",
  );
  return {
    id,
    owner,
    topic,
    recipe,
    phase:
      recipe === "paper"
        ? "writing"
        : recipe === "experiment"
          ? "methods"
          : "literature",
    round: 0,
    maxRevisions: 1,
    createdAt: now,
    grants,
    artifacts: {},
    sources: [],
    reviews: {},
    history: [],
    execution: { status: "not_run" },
    decision: null,
  };
}

export function nextRoles(project) {
  if (project.phase === "review")
    return REVIEWERS.filter((r) => !project.reviews[r]);
  if (project.phase === "chair") return ["review-chair"];
  return Object.hasOwn(OUTPUTS, project.phase) ? [project.phase] : [];
}

export function view(project, role) {
  const { reviews, history, grants, ...safe } = project;
  return {
    ...safe,
    artifacts: Object.fromEntries(
      Object.entries(project.artifacts).map(([name, a]) => [
        name,
        {
          sha256: a.sha256,
          role: a.role,
          bytes: Buffer.byteLength(a.content),
          round: a.round,
        },
      ]),
    ),
    nextRoles: nextRoles(project),
    reviewCount: Object.keys(reviews).length,
    ...(role === "review-chair" ||
    (role === "director" && project.phase !== "review")
      ? {
          reviews,
          history: history.map((h) => ({
            round: h.round,
            decision: h.decision,
          })),
        }
      : {}),
    ...(role === "director"
      ? {
          assignments: Object.fromEntries(
            nextRoles(project).map((r) => [r, grants?.[project.round]?.[r]]),
          ),
        }
      : {}),
  };
}

export function artifact(project, role, name) {
  requireThat(Object.hasOwn(project.artifacts, name), "Artifact not found");
  // Review reports are stored outside the artifact map; leafs cannot fetch peer reports.
  return project.artifacts[name];
}

export function addSources(project, role, sources) {
  requireRole(role, ["literature"]);
  requireThat(project.phase === "literature", "Literature phase is not active");
  const merged = new Map(project.sources.map((s) => [s.id, s]));
  for (const s of sources) merged.set(s.id, s);
  requireThat(merged.size <= 40, "Source limit: 40 per project");
  return { ...project, sources: [...merged.values()] };
}

export function submit(project, role, content, sessionKey) {
  requireRole(role, Object.keys(OUTPUTS));
  requireThat(
    project.phase === role,
    "This role is not the current project phase",
  );
  requireThat(
    typeof content === "string" &&
      content.trim().length >= 10 &&
      content.length <= 40000,
    "Artifact content must be 10–40000 characters",
  );
  if (role === "literature")
    requireThat(
      project.sources.length > 0,
      "Search actual sources before submitting literature",
    );
  const name = OUTPUTS[role];
  const item = {
    content,
    sha256: sha(content),
    role,
    sessionKey,
    round: project.round,
  };
  const next = structuredClone(project);
  next.artifacts[name] = item;
  next.phase = {
    literature: project.recipe === "survey" ? "complete" : "methods",
    methods: "experiment",
    experiment: "awaiting_execution",
    analysis: project.recipe === "experiment" ? "complete" : "writing",
    writing: "review",
  }[role];
  if (role === "writing") {
    next.manuscriptHash = item.sha256;
    next.reviews = {};
  }
  if (role === "experiment")
    next.execution = { status: "not_run", codeHash: item.sha256 };
  return next;
}

export function review(project, role, report, sessionKey) {
  requireRole(role, REVIEWERS);
  requireThat(project.phase === "review", "Review phase is not active");
  requireThat(
    report.manuscript_hash === project.manuscriptHash &&
      report.round === project.round,
    "Review snapshot or round mismatch",
  );
  requireThat(
    !project.reviews[role],
    "This reviewer already submitted this snapshot",
  );
  requireThat(
    ["hold", "revise", "ready_for_human"].includes(report.verdict),
    "Invalid review verdict",
  );
  requireThat(
    Number.isInteger(report.score) && report.score >= 1 && report.score <= 5,
    "Score must be 1–5",
  );
  const known = new Set([
    ...Object.keys(project.artifacts),
    ...project.sources.map((s) => s.id),
  ]);
  requireThat(
    Array.isArray(report.evidence_refs) &&
      report.evidence_refs.length > 0 &&
      report.evidence_refs.every((r) => known.has(r)),
    "Unregistered or missing evidence reference",
  );
  requireThat(
    Array.isArray(report.blocking_issues) &&
      Array.isArray(report.recommended_fixes),
    "Missing review issue/fix lists",
  );
  requireThat(
    [...report.blocking_issues, ...report.recommended_fixes].every(
      (v) => typeof v === "string" && v.length <= 2000,
    ),
    "Invalid review issues",
  );
  requireThat(
    typeof report.rationale === "string" &&
      report.rationale.trim().length >= 10 &&
      report.rationale.length <= 5000,
    "Review rationale required",
  );
  requireThat(
    typeof report.confidence === "number" &&
      report.confidence >= 0 &&
      report.confidence <= 1,
    "Confidence must be 0–1",
  );
  const next = structuredClone(project);
  next.reviews[role] = { ...report, role, sessionKey };
  if (REVIEWERS.every((r) => next.reviews[r])) next.phase = "chair";
  return next;
}

export function decide(project, role, decision) {
  requireRole(role, ["review-chair"]);
  requireThat(
    project.phase === "chair" && REVIEWERS.every((r) => project.reviews[r]),
    "Chair needs all three actual reviews",
  );
  requireThat(
    decision.manuscript_hash === project.manuscriptHash &&
      decision.round === project.round,
    "Chair snapshot mismatch",
  );
  requireThat(
    [
      "finish",
      "revise_manuscript",
      "new_experiment",
      "more_literature",
    ].includes(decision.action),
    "Invalid board action",
  );
  requireThat(
    typeof decision.rationale === "string" &&
      decision.rationale.trim().length >= 10,
    "Board rationale required",
  );
  const next = structuredClone(project);
  const missingExecution =
    project.recipe !== "paper" && project.execution.status !== "completed";
  const blocked = REVIEWERS.some(
    (r) =>
      project.reviews[r].blocking_issues.length > 0 ||
      project.reviews[r].verdict !== "ready_for_human",
  );
  next.decision = {
    ...decision,
    verdict:
      blocked || missingExecution || decision.action !== "finish" ||
      decision.verdict !== "ready_for_human" ? "hold" : "ready_for_human",
  };
  if (decision.action === "finish" || project.round >= project.maxRevisions)
    next.phase = "complete";
  else if (decision.action === "revise_manuscript") {
    next.history.push({
      round: project.round,
      artifacts: project.artifacts,
      reviews: project.reviews,
      decision: next.decision,
      execution: project.execution,
    });
    next.round += 1;
    next.phase = "writing";
    next.reviews = {};
  } else next.phase = "awaiting_rework";
  return next;
}

export function claimExecution(project, codeHash, attemptId) {
  requireThat(
    project.phase === "awaiting_execution",
    "Project is not awaiting experiment approval",
  );
  requireThat(
    project.artifacts["experiment.py"]?.sha256 === codeHash,
    "Experiment code changed after approval",
  );
  return {
    ...project,
    phase: "executing",
    execution: { status: "running", codeHash, attemptId },
  };
}

export function execution(project, codeHash, attemptId, result) {
  requireThat(
    project.phase === "executing" && project.execution.attemptId === attemptId,
    "Worker attempt is not current",
  );
  requireThat(
    project.artifacts["experiment.py"]?.sha256 === codeHash,
    "Experiment code changed after approval",
  );
  requireThat(
    ["completed", "skipped", "error"].includes(result.status),
    "Invalid worker result",
  );
  const next = structuredClone(project);
  const { artifacts, ...metadata } = result;
  next.execution = { ...metadata, codeHash, attemptId };
  for (const [name, content] of Object.entries(result.artifacts || {})) {
    requireThat(
      ["stdout.txt", "stderr.txt", "metrics.json", "execution.json"].includes(
        name,
      ),
      "Unexpected worker artifact",
    );
    next.artifacts[name] = {
      content,
      sha256: sha(content),
      role: "experiment-worker",
      round: project.round,
    };
  }
  next.phase = result.status === "error" ? "awaiting_execution" : "analysis";
  return next;
}

export function rework(project, expectedHash) {
  requireThat(
    project.phase === "awaiting_rework" && project.round < project.maxRevisions,
    "No approved rework available",
  );
  requireThat(
    project.manuscriptHash === expectedHash,
    "Rework snapshot changed",
  );
  const next = structuredClone(project);
  next.history.push({
    round: project.round,
    artifacts: project.artifacts,
    reviews: project.reviews,
    decision: project.decision,
    execution: project.execution,
  });
  next.round += 1;
  next.artifacts = {};
  next.reviews = {};
  next.execution = { status: "not_run" };
  next.phase =
    project.decision.action === "more_literature" ? "literature" : "methods";
  return next;
}

export async function mutate(store, key, reducer) {
  requireThat(
    store.observe && store.compareAndApply,
    "Host lacks atomic plugin-state comparisons",
  );
  let observed = await store.observe(key);
  for (let attempt = 0; attempt < 8; attempt++) {
    const next = reducer(observed.value);
    requireThat(
      Buffer.byteLength(JSON.stringify(next)) <= 800000,
      "Project record capacity reached; export before adding more artifacts",
    );
    const result = await store.compareAndApply(key, observed.comparison, {
      operation: "update",
      action: "set",
      value: next,
    });
    if (result.status === "applied") return next;
    if (result.status !== "conflict")
      throw new Error("State mutation did not commit");
    observed = result.current;
  }
  throw new Error("Project is busy; inspect before retrying");
}
