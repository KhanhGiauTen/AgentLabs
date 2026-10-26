import json
import re


def audit(store, run_id):
    run = store.get(run_id)
    manuscript = run.get("outputs", {}).get("writing", "")
    registered = {
        s.get("doi", "").lower().rstrip(".,)") for s in run.get("sources", []) if s.get("doi")
    }
    cited = set(x.lower().rstrip(".,)") for x in re.findall(r"10\.\d{4,9}/[^\s<>\]}]+", manuscript))
    missing = sorted(cited - registered)
    result = {
        "scope": "structural audit only; no automated claim of scientific correctness",
        "checks": [
            {
                "name": "DOI strings registered",
                "status": "fail" if missing else "pass",
                "detail": missing,
            },
            {
                "name": "Research experiment evidence",
                "status": (
                    "needs_human_review"
                    if run.get("execution", {}).get("status") == "completed"
                    else "missing"
                ),
                "detail": "Inspect dataset, raw metrics, code and logs; successful process exit does not validate research claims.",
            },
            {
                "name": "Full text grounding",
                "status": "needs_human_review" if run.get("documents") else "missing",
                "detail": "Search metadata/abstracts do not establish claim support. Uploaded chunks retain page IDs but require reading.",
            },
            {
                "name": "Draft marker",
                "status": "pass" if "DRAFT" in manuscript else "fail",
                "detail": "Manuscript must remain a clearly marked draft.",
            },
            {
                "name": "Novelty, statistics, leakage and ethics",
                "status": "needs_human_review",
                "detail": "Not machine-verifiable by this MVP; review protocol, data and venue requirements.",
            },
        ],
        "ready_to_submit": False,
        "sealed_reviews": {
            k: {"verdict": v.get("verdict"), "score": v.get("score"), "round": v.get("round")}
            for k, v in run.get("reviews", {}).items()
        },
    }
    store.write(run_id, "quality-gates.json", json.dumps(result, ensure_ascii=False, indent=2))
    store.update(run_id, quality=result)
    return result
