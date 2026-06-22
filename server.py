"""
KALU Founder Buyback Engine — zero-dependency server.

Run:  python3 server.py
Then open http://localhost:8000

No pip install required. Storage is SQLite (buyback.db).
Set ANTHROPIC_API_KEY in the env to enable real Claude analysis.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import ai

HERE = os.path.dirname(os.path.abspath(__file__))
# DB location is configurable so a Render persistent disk can be mounted later
# (set BUYBACK_DB=/data/buyback.db). Defaults to a local file.
DB_PATH = os.environ.get("BUYBACK_DB", os.path.join(HERE, "buyback.db"))
STATIC = os.path.join(HERE, "static")
PEOPLE = ["Zsombor", "Martin", "Lili"]
PORT = int(os.environ.get("PORT", "8000"))

_db_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person TEXT NOT NULL,
                raw_input TEXT NOT NULL,
                task_name TEXT NOT NULL,
                minutes INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                department TEXT,
                business_value TEXT,
                energy TEXT,
                interrupt INTEGER,
                drip TEXT,
                decision TEXT,
                recommended_owner TEXT,
                recommended_role TEXT,
                automatable INTEGER,
                playbook_needed INTEGER,
                weekly_time_estimate REAL,
                recommendations TEXT,
                engine TEXT,
                needs_clarification INTEGER DEFAULT 0,
                clarification_question TEXT DEFAULT ''
            )
        """)
        # migrate existing databases that predate the clarification columns
        for col, ddl in (("needs_clarification", "INTEGER DEFAULT 0"),
                         ("clarification_question", "TEXT DEFAULT ''")):
            try:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass  # column already exists


def row_to_task(r):
    return {
        "id": r["id"],
        "person": r["person"],
        "raw_input": r["raw_input"],
        "task_name": r["task_name"],
        "minutes": r["minutes"],
        "created_at": r["created_at"],
        "department": r["department"],
        "business_value": r["business_value"],
        "energy": r["energy"],
        "interrupt": bool(r["interrupt"]),
        "drip": r["drip"],
        "decision": r["decision"],
        "recommended_owner": r["recommended_owner"],
        "recommended_role": r["recommended_role"],
        "automatable": bool(r["automatable"]),
        "playbook_needed": bool(r["playbook_needed"]),
        "weekly_time_estimate": r["weekly_time_estimate"],
        "recommendations": json.loads(r["recommendations"] or "[]"),
        "engine": r["engine"],
        "needs_clarification": bool(r["needs_clarification"]),
        "clarification_question": r["clarification_question"] or "",
    }


def create_task(person, text):
    name, minutes = ai.parse_task(text)
    a = ai.analyze(name, minutes, person)
    now = datetime.now(timezone.utc).isoformat()
    with _db_lock, db() as conn:
        cur = conn.execute("""
            INSERT INTO tasks (person, raw_input, task_name, minutes, created_at,
                department, business_value, energy, interrupt, drip, decision,
                recommended_owner, recommended_role, automatable, playbook_needed,
                weekly_time_estimate, recommendations, engine,
                needs_clarification, clarification_question)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            person, text, name, minutes, now,
            a["department"], a["business_value"], a["energy"], int(a["interrupt"]),
            a["drip"], a["decision"], a["recommended_owner"], a["recommended_role"],
            int(a["automatable"]), int(a["playbook_needed"]),
            a["weekly_time_estimate"], json.dumps(a["recommendations"]), a["engine"],
            int(a["needs_clarification"]), a["clarification_question"],
        ))
        tid = cur.lastrowid
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    return row_to_task(row)


def list_tasks(person=None):
    with db() as conn:
        if person:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE person=? ORDER BY id DESC", (person,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()
    return [row_to_task(r) for r in rows]


def update_task(tid, text):
    """Re-parse + re-analyze an edited task. Keeps the original created_at."""
    with db() as conn:
        existing = conn.execute("SELECT person FROM tasks WHERE id=?", (tid,)).fetchone()
    if not existing:
        return None
    person = existing["person"]
    name, minutes = ai.parse_task(text)
    a = ai.analyze(name, minutes, person)
    with _db_lock, db() as conn:
        conn.execute("""
            UPDATE tasks SET raw_input=?, task_name=?, minutes=?, department=?,
                business_value=?, energy=?, interrupt=?, drip=?, decision=?,
                recommended_owner=?, recommended_role=?, automatable=?,
                playbook_needed=?, weekly_time_estimate=?, recommendations=?, engine=?,
                needs_clarification=?, clarification_question=?
            WHERE id=?
        """, (
            text, name, minutes, a["department"], a["business_value"], a["energy"],
            int(a["interrupt"]), a["drip"], a["decision"], a["recommended_owner"],
            a["recommended_role"], int(a["automatable"]), int(a["playbook_needed"]),
            a["weekly_time_estimate"], json.dumps(a["recommendations"]), a["engine"],
            int(a["needs_clarification"]), a["clarification_question"], tid,
        ))
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    return row_to_task(row)


def reanalyze_task(tid):
    """Re-run the AI analysis on a task using its stored name/minutes/person.
    Keeps the text, minutes and created_at; only the analysis fields change."""
    with db() as conn:
        row = conn.execute(
            "SELECT task_name, minutes, person FROM tasks WHERE id=?", (tid,)).fetchone()
    if not row:
        return None
    a = ai.analyze(row["task_name"], row["minutes"], row["person"])
    with _db_lock, db() as conn:
        conn.execute("""
            UPDATE tasks SET department=?, business_value=?, energy=?, interrupt=?,
                drip=?, decision=?, recommended_owner=?, recommended_role=?,
                automatable=?, playbook_needed=?, weekly_time_estimate=?,
                recommendations=?, engine=?, needs_clarification=?,
                clarification_question=? WHERE id=?
        """, (
            a["department"], a["business_value"], a["energy"], int(a["interrupt"]),
            a["drip"], a["decision"], a["recommended_owner"], a["recommended_role"],
            int(a["automatable"]), int(a["playbook_needed"]), a["weekly_time_estimate"],
            json.dumps(a["recommendations"]), a["engine"],
            int(a["needs_clarification"]), a["clarification_question"], tid,
        ))
        r = conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    return row_to_task(r)


def delete_task(tid):
    with _db_lock, db() as conn:
        conn.execute("DELETE FROM tasks WHERE id=?", (tid,))


# ---------------------------------------------------------------------------
# Aggregation  -> dashboard + insights
# ---------------------------------------------------------------------------

def _hours(minutes):
    return round(minutes / 60.0, 1)


def _filter_by_date(tasks, date_from, date_to):
    """Keep tasks whose created_at falls within [date_from, date_to] (epoch ms)."""
    if date_from is None and date_to is None:
        return tasks
    out = []
    for t in tasks:
        try:
            ms = datetime.fromisoformat(t["created_at"]).timestamp() * 1000
        except Exception:
            out.append(t)
            continue
        if date_from is not None and ms < date_from:
            continue
        if date_to is not None and ms > date_to:
            continue
        out.append(t)
    return out


def compute_metrics(person=None, date_from=None, date_to=None):
    tasks = _filter_by_date(list_tasks(person), date_from, date_to)
    n = len(tasks)
    total_min = sum(t["minutes"] for t in tasks)

    delegate_min = sum(t["minutes"] for t in tasks
                       if t["decision"] in ("Delegate ASAP",))
    automate_min = sum(t["minutes"] for t in tasks if t["decision"] == "Automate")
    batch_min = sum(t["minutes"] for t in tasks if t["decision"] == "Batch")
    keep_min = sum(t["minutes"] for t in tasks if t["decision"] == "Keep")
    interrupts = [t for t in tasks if t["interrupt"]]
    interrupt_count = len(interrupts)
    # Focus loss: each interrupt costs the task time + ~23 min context-switch cost.
    focus_loss_min = sum(t["minutes"] for t in interrupts) + interrupt_count * 23

    # Buy-back-able = anything not "Keep" and not "Review Later"
    buyback_min = sum(t["minutes"] for t in tasks
                      if t["decision"] not in ("Keep", "Review Later"))

    # ---- breakdowns ----
    def breakdown(key):
        d = {}
        for t in tasks:
            d[t[key]] = d.get(t[key], 0) + t["minutes"]
        return dict(sorted(d.items(), key=lambda kv: -kv[1]))

    by_department = breakdown("department")
    by_energy = breakdown("energy")
    by_decision = breakdown("decision")
    by_drip = breakdown("drip")
    by_value = breakdown("business_value")

    # ---- top time drains (grouped by task name, normalized) ----
    drains = {}
    for t in tasks:
        k = t["task_name"].strip().lower()
        if k not in drains:
            drains[k] = {"name": t["task_name"], "minutes": 0, "count": 0,
                         "decision": t["decision"], "energy": t["energy"]}
        drains[k]["minutes"] += t["minutes"]
        drains[k]["count"] += 1
    top_drains = sorted(drains.values(), key=lambda x: -x["minutes"])[:6]

    top_delegate = sorted(
        [t for t in tasks if t["decision"] in ("Delegate ASAP",)],
        key=lambda t: -t["minutes"])[:5]
    top_automate = sorted(
        [t for t in tasks if t["decision"] == "Automate" or t["automatable"]],
        key=lambda t: -t["minutes"])[:5]

    missing = compute_hiring(tasks)

    # Estimated monthly buy-back: weekly buyback-able time * ~4.3 weeks
    weekly_buyback = sum(t["weekly_time_estimate"] for t in tasks
                         if t["decision"] not in ("Keep", "Review Later"))
    monthly_buyback_hours = _hours(weekly_buyback * 4.3)

    return {
        "task_count": n,
        "total_hours": _hours(total_min),
        "total_minutes": total_min,
        "delegatable_hours": _hours(delegate_min),
        "automatable_hours": _hours(automate_min),
        "batchable_hours": _hours(batch_min),
        "founder_hours": _hours(keep_min),
        "buyback_hours": _hours(buyback_min),
        "interrupt_count": interrupt_count,
        "focus_loss_hours": _hours(focus_loss_min),
        "monthly_buyback_hours": monthly_buyback_hours,
        "by_department": by_department,
        "by_energy": by_energy,
        "by_decision": by_decision,
        "by_drip": by_drip,
        "by_value": by_value,
        "top_drains": top_drains,
        "top_delegate": [_slim(t) for t in top_delegate],
        "top_automate": [_slim(t) for t in top_automate],
        "missing_roles": missing,
        "engine": "ai" if ai.API_KEY else "heuristic",
    }


def _slim(t):
    return {"id": t["id"], "task_name": t["task_name"], "minutes": t["minutes"],
            "person": t["person"], "recommendations": t["recommendations"],
            "recommended_owner": t["recommended_owner"]}


# Map departments to the role that would absorb the work.
ROLE_MAP = {
    "Founder Assistant": {
        "match": lambda t: t["department"] == "Operations"
        and t["business_value"] in ("$", "$$"),
        "covers": "Admin, access, scheduling, Slack triage, coordination, founder support",
    },
    "Finance Assistant": {
        "match": lambda t: t["department"] == "Finance",
        "covers": "Invoices, payments, subscriptions, banking",
    },
    "Delivery / PM Lead": {
        "match": lambda t: t["department"] == "Client Success",
        "covers": "Client reporting, status, statistics, project ownership",
    },
    "Content / Marketing Assistant": {
        "match": lambda t: t["department"] == "Marketing",
        "covers": "Company content, recordings, blog posts, social media",
    },
}


def compute_hiring(tasks):
    out = []
    for role, cfg in ROLE_MAP.items():
        matched = [t for t in tasks if cfg["match"](t)]
        if not matched:
            continue
        weekly = sum(t["weekly_time_estimate"] for t in matched)
        out.append({
            "role": role,
            "covers": cfg["covers"],
            "task_count": len(matched),
            "weekly_hours": _hours(weekly),
            "monthly_hours": _hours(weekly * 4.3),
        })
    out.sort(key=lambda r: -r["weekly_hours"])
    # Mark priority order
    for i, r in enumerate(out):
        r["priority"] = i + 1
    return out


def compute_insights(person=None, date_from=None, date_to=None):
    m = compute_metrics(person, date_from, date_to)
    total = m["total_minutes"] or 1
    # department percentages
    dept_pct = [
        {"label": k, "pct": round(v / total * 100)}
        for k, v in list(m["by_department"].items())[:5]
    ]

    def dedupe(names, limit=4):
        seen, out = set(), []
        for n in names:
            key = n.strip().lower()
            if key not in seen:
                seen.add(key)
                out.append(n)
        return out[:limit]

    return {
        "metrics": m,
        "department_pct": dept_pct,
        "delegatable_hours": m["delegatable_hours"],
        "automatable_hours": m["automatable_hours"],
        "first_hire": m["missing_roles"][0] if m["missing_roles"] else None,
        "second_hire": m["missing_roles"][1] if len(m["missing_roles"]) > 1 else None,
        "sop_opportunities": dedupe([d["name"] for d in m["top_drains"]
                              if d.get("decision") in ("Playbook Needed", "Delegate ASAP")]),
        "automation_opportunities": dedupe([t["task_name"] for t in m["top_automate"]]),
        "top_drains": m["top_drains"],
    }


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

def _qnum(q, key):
    """Parse a numeric query param (epoch ms) to float, or None."""
    val = q.get(key, [None])[0]
    if val in (None, ""):
        return None
    try:
        return float(val)
    except ValueError:
        return None


MIME = {".html": "text/html", ".js": "application/javascript",
        ".css": "text/css", ".json": "application/json",
        ".svg": "image/svg+xml", ".ico": "image/x-icon",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # quieter console
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        full = os.path.join(STATIC, path)
        if not os.path.abspath(full).startswith(os.path.abspath(STATIC)):
            return self._json({"error": "forbidden"}, 403)
        if not os.path.isfile(full):
            return self._json({"error": "not found"}, 404)
        ext = os.path.splitext(full)[1]
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        if p == "/" or p == "/index.html":
            return self._file("index.html")
        if p.startswith("/static/"):
            return self._file(p[len("/static/"):])
        if p == "/api/people":
            return self._json(PEOPLE)
        if p == "/api/tasks":
            person = q.get("person", [None])[0]
            person = person if person in PEOPLE else None
            fr, to = _qnum(q, "from"), _qnum(q, "to")
            return self._json(_filter_by_date(list_tasks(person), fr, to))
        if p == "/api/dashboard":
            person = q.get("person", [None])[0]
            person = person if person in PEOPLE else None
            fr, to = _qnum(q, "from"), _qnum(q, "to")
            return self._json(compute_metrics(person, fr, to))
        if p == "/api/insights":
            person = q.get("person", [None])[0]
            person = person if person in PEOPLE else None
            fr, to = _qnum(q, "from"), _qnum(q, "to")
            return self._json(compute_insights(person, fr, to))
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        parts = u.path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "tasks" and parts[3] == "reanalyze":
            try:
                task = reanalyze_task(int(parts[2]))
                if task is None:
                    return self._json({"error": "not found"}, 404)
                return self._json(task)
            except Exception as e:
                return self._json({"error": str(e)}, 500)
        if u.path == "/api/tasks":
            data = self._body()
            person = (data.get("person") or "").strip()
            text = (data.get("text") or "").strip()
            if person not in PEOPLE:
                return self._json({"error": "unknown person"}, 400)
            if not text:
                return self._json({"error": "empty task"}, 400)
            if not ai.has_duration(text):
                return self._json({
                    "error": "Add meg mennyi időt töltöttél a feladattal! (pl. „- 10p”)",
                    "code": "NO_TIME",
                }, 400)
            try:
                task = create_task(person, text)
                return self._json(task, 201)
            except Exception as e:
                return self._json({"error": str(e)}, 500)
        return self._json({"error": "not found"}, 404)

    def do_PUT(self):
        u = urlparse(self.path)
        parts = u.path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "tasks":
            data = self._body()
            text = (data.get("text") or "").strip()
            if not text:
                return self._json({"error": "empty task"}, 400)
            if not ai.has_duration(text):
                return self._json({
                    "error": "Add meg mennyi időt töltöttél a feladattal! (pl. „- 10p”)",
                    "code": "NO_TIME",
                }, 400)
            try:
                task = update_task(int(parts[2]), text)
                if task is None:
                    return self._json({"error": "not found"}, 404)
                return self._json(task)
            except Exception as e:
                return self._json({"error": str(e)}, 500)
        return self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        u = urlparse(self.path)
        parts = u.path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "tasks":
            try:
                delete_task(int(parts[2]))
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 500)
        return self._json({"error": "not found"}, 404)


def main():
    init_db()
    engine = "Claude AI" if ai.API_KEY else "built-in heuristic (set ANTHROPIC_API_KEY for AI)"
    print("=" * 56)
    print("  KALU Founder Buyback Engine")
    print(f"  http://localhost:{PORT}")
    print(f"  Analysis engine: {engine}")
    print("=" * 56)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
