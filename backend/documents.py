"""Local document ingestion; exact page/chunk IDs are retained for evidence review."""

import base64
import hashlib
import io
import json
import re
import csv
from pypdf import PdfReader


def ingest(store, run_id, name, encoded):
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > 10_000_000:
        raise ValueError("Tài liệu tối đa 10 MB")
    digest = hashlib.sha256(raw).hexdigest()
    doc_id = "doc-" + digest[:12]
    if name.lower().endswith((".csv", ".json")):
        text = raw.decode("utf-8-sig")
        if name.lower().endswith(".json"):
            parsed = json.loads(text)
            preview = str(parsed)[:1500]
            suffix = ".json"
        else:
            sample = list(__import__("itertools").islice(csv.reader(io.StringIO(text)), 6))
            preview = json.dumps(sample, ensure_ascii=False)
            suffix = ".csv"
        artifact = "input-" + digest[:12] + suffix
        store.artifact_path(run_id, artifact).write_bytes(raw)
        store.event(run_id, "artifact", name=artifact)
        dataset = {
            "id": "data-" + digest[:12],
            "title": name[:180],
            "artifact": artifact,
            "sandbox_path": "/inputs/" + artifact,
            "sha256": digest,
            "bytes": len(raw),
            "preview": preview,
            "evidence": "user supplied dataset; validity, license and leakage not verified",
        }
        datasets = {d["id"]: d for d in store.get(run_id).get("datasets", [])}
        if len(datasets) >= 5 and dataset["id"] not in datasets:
            raise ValueError("Tối đa 5 dataset mỗi lượt")
        datasets[dataset["id"]] = dataset
        store.update(run_id, datasets=list(datasets.values()))
        store.event(run_id, "dataset", name=name, sha256=digest)
        return dataset
    chunks = []
    if name.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(raw), strict=False)
        if reader.is_encrypted:
            raise ValueError("PDF có mật khẩu chưa được hỗ trợ")
        total_pages = len(reader.pages)
        pages = [(i + 1, reader.pages[i].extract_text() or "") for i in range(min(total_pages, 50))]
        extent = f"text extracted from first {len(pages)}/{total_pages} pages; no OCR; not independently verified"
    elif name.lower().endswith((".md", ".txt")):
        pages = [(1, raw.decode("utf-8-sig"))]
        extent = "uploaded UTF-8 text; not independently verified"
    else:
        raise ValueError("Chỉ nhận .pdf, .md, .txt, .csv, .json")
    count = 0
    for page_no, text in pages:
        text = text.replace("\x00", "")
        for start in range(0, len(text), 1600):
            content = text[start : start + 1800]
            chunks.append(
                {
                    "id": f"{doc_id}:p{page_no}:c{len(chunks)+1}",
                    "document": doc_id,
                    "page": page_no,
                    "text": content,
                }
            )
            count += len(content)
            if count >= 250_000:
                extent += "; truncated at 250k extracted characters"
                break
        if count >= 250_000:
            break
    if not any(c["text"].strip() for c in chunks):
        raise ValueError("Không trích được text. PDF scan cần OCR trước khi import.")
    title = name[:180]
    document = {
        "id": doc_id,
        "title": title,
        "sha256": digest,
        "bytes": len(raw),
        "chunks": len(chunks),
        "evidence": extent,
        "artifact": doc_id + ".json",
    }
    store.write(
        run_id,
        doc_id + ".json",
        json.dumps({"document": document, "chunks": chunks}, ensure_ascii=False, indent=2),
    )
    run = store.get(run_id)
    documents = {d["id"]: d for d in run.get("documents", [])}
    documents[doc_id] = document
    store.update(run_id, documents=list(documents.values()))
    store.event(run_id, "document", id=doc_id, name=title, sha256=digest, chunks=len(chunks))
    return document


def search_documents(store, run_id, query):
    terms = set(re.findall(r"\w+", query.lower()))
    if not terms or len(query) > 500:
        raise ValueError("Query must be 2–500 characters")
    scored = []
    for doc in store.get(run_id).get("documents", []):
        data = json.loads(store.artifact_path(run_id, doc["artifact"]).read_text(encoding="utf-8"))
        for chunk in data["chunks"]:
            words = re.findall(r"\w+", chunk["text"].lower())
            score = sum(min(words.count(t), 4) for t in terms) / max(len(words), 50) ** 0.5
            if score:
                scored.append(
                    (score, {**chunk, "title": doc["title"], "evidence": doc["evidence"]})
                )
    return {
        "chunks": [c for _, c in sorted(scored, key=lambda x: -x[0])[:6]],
        "method": "local lexical chunk search; not semantic embeddings; quote exact chunk IDs when citing",
    }
