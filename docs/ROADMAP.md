# AgentLabs roadmap

The current release establishes a local harness with 10 logical roles, three sealed reviewers and a Chair, bounded revision routes, checkpoint recovery and explicit experiment approval. Milestones below are planned, not completed features.

## 1. Validate research quality on a small pilot

Create 10–20 tasks with known evidence or seeded errors. Measure citation existence/support, detection of leakage and metric bugs, reproducibility, reviewer false alarms, Chair handling of disagreement, latency and cost. Compare the same tasks with a single-agent baseline and the original AgentLaboratory where feasible. Do not expand the agent count before this evaluation.

## 2. Improve experiment iteration

Introduce a constrained git worktree worker, structured experiment manifests, reproducible environment snapshots and bounded debug/repair loops. Every new execution must preserve approval, code/data hashes, logs and budget. Add Docker smoke tests on the target Windows/Linux configuration before calling the worker production-ready.

## 3. Strengthen evidence and review

Improve full-text ingestion, page/section span citations, optional OCR and claim-to-evidence tables. Add semantic retrieval only if lexical retrieval misses relevant evidence in the pilot. Calibrate reviewers and test mixed-model reviewing against shared-model correlated failures.

## 4. Add compute and observability

Support an explicit remote GPU/SSH or cluster backend with a compute budget, cancellation and environment provenance. Add MLflow or another established tracking backend once JSON artifacts are insufficient. Do not automatically rent compute or pass provider credentials into experiment containers.

## 5. Manuscript delivery

Add LaTeX templates, bibliography validation, figures generated from raw metrics, compile/render checks and a revision diff. Keep submission/publication under author control.

## Release discipline

Use small versioned changes, CI and migration tests for persisted graph/state changes. Separate software-contract tests from model-quality evaluation and end-to-end provider/compute checks. Track limitations openly and avoid treating unit-test counts as research-quality scores.
