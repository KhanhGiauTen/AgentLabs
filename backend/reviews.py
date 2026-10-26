import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from .catalog import REVIEWERS


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["hold", "revise", "ready_for_human"]
    action: Literal["no_change", "revise_manuscript", "new_experiment", "more_literature"]
    score: int = Field(ge=1, le=5, strict=True)
    confidence: Literal["low", "medium", "high"]
    rationale: str = Field(min_length=10, max_length=8000)
    evidence_refs: list[str] = Field(max_length=20)
    blocking_issues: list[str] = Field(max_length=10)
    recommended_fixes: list[str] = Field(max_length=10)


def submit_review(store, run_id, role, args):
    if role not in [*REVIEWERS, "review"]:
        raise ValueError("Only a server-selected reviewer can submit a scorecard")
    review = Review.model_validate(args).model_dump()
    run = store.get(run_id)
    allowed = {s["id"] for s in run.get("sources", [])}
    allowed |= {a["name"] for a in store.artifacts(run_id) if not a["name"].startswith("review")}
    allowed |= {d["id"] for d in run.get("datasets", [])}
    if role in REVIEWERS:
        allowed -= {"board-decision.json", "quality-gates.json"}
    for doc in run.get("documents", []):
        allowed.add(doc["id"])
        data = json.loads(store.artifact_path(run_id, doc["artifact"]).read_text(encoding="utf-8"))
        allowed.update(c["id"] for c in data["chunks"])
    if role == "review":
        allowed.update(x + ".json" for x in REVIEWERS)
    unknown = [r for r in review["evidence_refs"] if r not in allowed]
    if unknown:
        raise ValueError("Unregistered evidence_refs: " + ", ".join(unknown)[:300])
    if role == "review" and any(x not in run.get("reviews", {}) for x in REVIEWERS):
        raise ValueError("Chair must wait for all three sealed reviews")
    manuscript = store.artifact_path(run_id, "manuscript.md")
    digest = (
        __import__("hashlib").sha256(manuscript.read_bytes()).hexdigest()
        if manuscript.exists()
        else None
    )
    if role == "review" and any(
        r.get("round") != run.get("revision_count", 0) or r.get("manuscript_sha256") != digest
        for k, r in run.get("reviews", {}).items()
        if k in REVIEWERS
    ):
        raise ValueError("Sealed reviews do not match the same manuscript snapshot/round")
    if review["verdict"] == "ready_for_human" and (
        run.get("execution", {}).get("status") != "completed" or review["blocking_issues"]
    ):
        review["verdict"] = "hold"
        review[
            "rationale"
        ] += "\nHarness override: unresolved issues or no completed experiment; this is not evidence of research readiness."
    review.update(reviewer=role, round=run.get("revision_count", 0), manuscript_sha256=digest)
    store.save_review(run_id, role, review)
    store.write(run_id, role + ".json", json.dumps(review, ensure_ascii=False, indent=2))
    store.write(
        run_id,
        f"{role}-round{review['round']}.json",
        json.dumps(review, ensure_ascii=False, indent=2),
    )
    store.event(
        run_id,
        "review_submitted",
        reviewer=role,
        verdict=review["verdict"],
        action=review["action"],
        round=review["round"],
    )
    return {"stored": True, "review": review}


def board_decision(store, run_id, max_revisions):
    run = store.get(run_id)
    reviews = run.get("reviews", {})
    chair = reviews.get("review", {})
    action = chair.get("action", "no_change")
    reason = chair.get("rationale", "Missing chair decision; human review required")
    if any(x not in reviews for x in REVIEWERS):
        action, reason = "no_change", "Missing sealed review; workflow held for human review"
    elif run.get("revision_count", 0) >= max_revisions:
        action, reason = (
            "no_change",
            "Revision limit reached; unresolved issues are retained for human review",
        )
    decision = {
        "action": action,
        "verdict": chair.get("verdict", "hold"),
        "reason": reason,
        "blocking_issues": chair.get("blocking_issues", []),
        "recommended_fixes": chair.get("recommended_fixes", []),
        "revision_count": run.get("revision_count", 0),
        "max_revisions": max_revisions,
        "independent_reviews": {k: v.get("verdict") for k, v in reviews.items() if k in REVIEWERS},
        "human_approval_required": action in {"new_experiment", "more_literature"},
    }
    store.update(run_id, board=decision)
    store.write(run_id, "board-decision.json", json.dumps(decision, ensure_ascii=False, indent=2))
    return decision
