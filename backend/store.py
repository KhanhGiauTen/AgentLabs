import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "studio.sqlite"
        with self.db() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, at TEXT, kind TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS usage(id TEXT PRIMARY KEY, run_id TEXT, at TEXT, month TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER, cost REAL, reserved REAL, status TEXT);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
            """)

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def get(self, run_id):
        with self.db() as c:
            row = c.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, data):
        data["updated_at"] = now()
        with self.db() as c:
            c.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?)",
                (data["id"], json.dumps(data, ensure_ascii=False)),
            )

    def update(self, run_id, **kwargs):
        return self.mutate(run_id, lambda data: data.update(kwargs))

    def mutate(self, run_id, transform):
        """Atomic read/modify/write for independently running reviewers."""
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise ValueError("Run missing")
            data = json.loads(row[0])
            transform(data)
            data["updated_at"] = now()
            c.execute(
                "UPDATE runs SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), run_id)
            )
        return data

    def stage_start(self, run_id, role):
        def change(data):
            active = set(data.get("active_roles", []))
            active.add(role)
            data.update(
                active_roles=sorted(active),
                stage="reviewing" if role.startswith("review_") else role,
                status="running",
            )

        self.mutate(run_id, change)

    def stage_complete(self, run_id, role, text):
        def change(data):
            data["outputs"] = {**data.get("outputs", {}), role: text}
            data["active_roles"] = [x for x in data.get("active_roles", []) if x != role]

        self.mutate(run_id, change)

    def save_review(self, run_id, role, review):
        self.mutate(
            run_id, lambda data: data.update(reviews={**data.get("reviews", {}), role: review})
        )

    def list(self):
        with self.db() as c:
            rows = c.execute("SELECT data FROM runs ORDER BY rowid DESC").fetchall()
        return [json.loads(r[0]) for r in rows]

    def event(self, run_id, kind, **data):
        with self.db() as c:
            c.execute(
                "INSERT INTO events(run_id,at,kind,data) VALUES(?,?,?,?)",
                (run_id, now(), kind, json.dumps(data, ensure_ascii=False)),
            )

    def events(self, run_id, after=0):
        with self.db() as c:
            rows = c.execute(
                "SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq", (run_id, after)
            ).fetchall()
        return [{**dict(r), "data": json.loads(r["data"])} for r in rows]

    def settings(self, default_budget):
        with self.db() as c:
            row = c.execute("SELECT value FROM settings WHERE key='budget'").fetchone()
        return {"monthly_budget": float(row[0]) if row else default_budget}

    def set_budget(self, value):
        with self.db() as c:
            c.execute("INSERT OR REPLACE INTO settings VALUES ('budget',?)", (str(value),))

    @staticmethod
    def month():
        # Billing buckets are calendar months in the user's timezone, UTC+7.
        from datetime import timedelta

        return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m")

    def spend(self, run_id=None):
        query = "SELECT COALESCE(SUM(cost+reserved),0) FROM usage WHERE "
        query += "run_id=?" if run_id else "month=?"
        args = [run_id or self.month()]
        with self.db() as c:
            return float(c.execute(query, args).fetchone()[0])

    def reserve(self, run_id, model, amount, monthly_cap, run_cap):
        reservation_id = uuid.uuid4().hex
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            total = c.execute(
                "SELECT COALESCE(SUM(cost+reserved),0) FROM usage WHERE month=?", (self.month(),)
            ).fetchone()[0]
            run_total = c.execute(
                "SELECT COALESCE(SUM(cost+reserved),0) FROM usage WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            if total + amount > monthly_cap or run_total + amount > run_cap:
                raise ValueError(
                    "Budget cap: không đủ ngân sách dự phòng cho API call tiếp theo. Tăng giới hạn hoặc bắt đầu lượt nhỏ hơn."
                )
            c.execute(
                "INSERT INTO usage VALUES(?,?,?,?,?,0,0,0,?,'reserved')",
                (reservation_id, run_id, now(), self.month(), model, amount),
            )
        return reservation_id

    def settle(self, reservation_id, input_tokens, output_tokens, cost):
        with self.db() as c:
            c.execute(
                "UPDATE usage SET input_tokens=?,output_tokens=?,cost=?,reserved=0,status='estimated' WHERE id=?",
                (input_tokens, output_tokens, cost, reservation_id),
            )

    def uncertain(self, reservation_id):
        # A timeout can still be billed upstream; keep the maximum reservation.
        with self.db() as c:
            c.execute("UPDATE usage SET status='uncertain' WHERE id=?", (reservation_id,))

    def usage(self):
        with self.db() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM usage WHERE month=? ORDER BY at DESC", (self.month(),)
                ).fetchall()
            ]

    def artifacts_dir(self, run_id):
        if not run_id or any(x not in "0123456789abcdef" for x in run_id):
            raise ValueError("Invalid run ID")
        path = self.root / "runs" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def artifact_path(self, run_id, name):
        if (
            not name
            or len(name) > 100
            or any(
                c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
                for c in name
            )
            or name.startswith(".")
        ):
            raise ValueError("Invalid artifact name")
        root = self.artifacts_dir(run_id).resolve()
        path = (root / name).resolve()
        if path.parent != root or path.is_symlink():
            raise ValueError("Invalid artifact path")
        return path

    def write(self, run_id, name, content):
        self.artifact_path(run_id, name).write_text(content, encoding="utf-8")
        self.event(run_id, "artifact", name=name)

    def artifacts(self, run_id):
        return [
            {"name": p.name, "bytes": p.stat().st_size}
            for p in sorted(self.artifacts_dir(run_id).iterdir())
            if p.is_file() and not p.is_symlink()
        ]
