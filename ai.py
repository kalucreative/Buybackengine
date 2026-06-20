"""
KALU Founder Buyback Engine — AI classification pipeline.

Two modes, auto-detected:
  1. If ANTHROPIC_API_KEY is set -> real Claude analysis (rich, nuanced).
  2. Otherwise -> built-in heuristic engine (Hungarian + English aware).

Every task gets classified across the full buyback schema. The single
question behind every field: "How can KALU buy back founder time?"
"""

import json
import os
import re
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Vocabulary / enums
# ---------------------------------------------------------------------------

DEPARTMENTS = [
    "Leadership", "Sales", "Client Success", "Operations",
    "Production", "Finance", "HR", "Admin",
]
BUSINESS_VALUES = ["$", "$$", "$$$", "$$$$"]
ENERGY = ["green", "yellow", "red"]
DRIP = ["Delegation", "Replacement", "Investment", "Production"]
DECISIONS = [
    "Keep", "Delegate ASAP", "Automate", "Batch",
    "Playbook Needed", "Needs New Hire", "Review Later",
]

MODEL = os.environ.get("BUYBACK_MODEL", "claude-sonnet-4-6")
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()


# ---------------------------------------------------------------------------
# Input parsing  -> (clean task name, minutes)
# ---------------------------------------------------------------------------

# Hungarian/English duration tokens. Order matters (hours before the bare "m").
_DURATION_PATTERNS = [
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:h\b|hr\b|hours?\b|ó[raást]*\b)", re.I), 60.0),
    (re.compile(r"(\d+)\s*(?:p|perc|min|minute|m)\b", re.I), 1.0),
]


def has_duration(text):
    """True if the text contains a recognizable duration (minutes or hours)."""
    text = text or ""
    return any(pattern.search(text) for pattern, _ in _DURATION_PATTERNS)


def parse_task(text):
    """Extract a clean task name and a minute count from free text."""
    text = (text or "").strip()
    minutes = 0
    matched_span = None

    for pattern, mult in _DURATION_PATTERNS:
        m = pattern.search(text)
        if m:
            val = float(m.group(1).replace(",", "."))
            minutes = int(round(val * mult))
            matched_span = m.span()
            break

    name = text
    if matched_span:
        # Drop the duration token plus any trailing/leading separators (- , :)
        name = (text[:matched_span[0]] + " " + text[matched_span[1]:])
    name = re.sub(r"\s*[-–—:,]\s*$", "", name.strip())
    name = re.sub(r"^\s*[-–—:,]\s*", "", name)
    name = re.sub(r"\s{2,}", " ", name).strip(" -–—:,")

    if minutes == 0:
        minutes = 10  # sensible default when no duration is given
    return name or text, minutes


# ---------------------------------------------------------------------------
# Real AI path (Anthropic API via stdlib)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the analytical core of the KALU Founder Buyback Engine.

KALU Creative is a ~30-person short-form content agency (80+ clients, 600+ videos/month). \
The founders (Zsombor, Martin) and ops lead (Lili) are drowning in reactive work. \
Your job: classify each task so the system can show how to BUY BACK founder time \
through delegation, automation, processes (SOPs), and hiring.

Think like a sharp COO / operations consultant / founder's chief of staff.
Tasks arrive in Hungarian or English. Understand both.

Return ONLY a JSON object (no prose, no markdown) with EXACTLY these keys:
{
  "department": one of ["Leadership","Sales","Client Success","Operations","Production","Finance","HR","Admin"],
  "business_value": one of ["$","$$","$$$","$$$$"],   // $ anyone, $$ trained employee, $$$ experienced manager, $$$$ founder-level
  "energy": one of ["green","yellow","red"],          // green=energizing, yellow=neutral, red=draining
  "interrupt": true|false,                             // did this break deep work / context-switch the founder?
  "drip": one of ["Delegation","Replacement","Investment","Production"],  // Dan Martell DRIP
  "decision": one of ["Keep","Delegate ASAP","Automate","Batch","Playbook Needed","Needs New Hire","Review Later"],
  "recommended_owner": short string,                   // e.g. "Lili", "Founder Assistant", "Ops Assistant", "Keep with founder"
  "recommended_role": short string,                    // the role/position that should own this long-term
  "automatable": true|false,
  "playbook_needed": true|false,
  "weekly_time_estimate": number,                      // estimated minutes/week this category likely consumes
  "recommendations": [string, ...]                     // 2-4 concrete, practical buy-back moves (tools, SOPs, hires, systems)
}

Be decisive. Low-value reactive admin (TikTok codes, permissions, status chasing, \
Slack) -> red energy, interrupt true, $ or $$, Delegate/Automate. \
Strategy, sales, partnerships, key hires -> green, $$$$, Keep."""


def _call_anthropic(task_name, minutes, person):
    user = (
        f"Person: {person}\n"
        f"Task: {task_name}\n"
        f"Minutes spent: {minutes}\n\n"
        "Classify this task. Return only the JSON object."
    )
    payload = {
        "model": MODEL,
        "max_tokens": 700,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    text = "".join(
        block.get("text", "") for block in body.get("content", [])
        if block.get("type") == "text"
    ).strip()
    # Strip accidental code fences
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.I).strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# Heuristic fallback engine (Hungarian + English keyword aware)
# ---------------------------------------------------------------------------

_KW = {
    "Finance": ["számla", "szamla", "invoice", "fizet", "payment", "bank", "díj",
                 "dij", "előfizetés", "elofizetes", "subscription", "könyvel",
                 "konyvel", "spar", "adó", "ado", "pénzügy", "penzugy"],
    "HR": ["interjú", "interju", "jelentkez", "applicant", "interview", "szerződés",
            "szerzodes", "contract", "onboard", "szabadság", "szabadsag", "vacation",
            "felvétel", "felvetel", "hr", "toborz"],
    "Sales": ["sales", "ajánlat", "ajanlat", "offer", "lead", "follow-up", "followup",
               "értékesít", "ertekesit", "deal", "pitch", "upsell", "új ügyfél",
               "uj ugyfel", "prospect", "partnership", "partner"],
    "Production": ["videó", "video", "vágás", "vagas", "edit", "forgatás", "forgatas",
                    "shoot", "script", "forgatókönyv", "forgatokonyv", "grafik",
                    "graphic", "thumbnail", "render", "b-roll", "broll", "anyag"],
    "Client Success": ["ügyfél", "ugyfel", "client", "statisztik", "statistic",
                        "metricool", "report", "riport", "feedback", "visszajelz",
                        "státusz", "statusz", "status", "kpmg", "biohair", "kgyd"],
    "Operations": ["slack", "koordin", "calendar", "naptár", "naptar", "meeting",
                    "meeting", "ütemez", "utemez", "schedul", "átrak", "atrak",
                    "egyeztet", "szervez", "blokk", "block", "problem", "fennakad"],
    "Admin": ["email", "e-mail", "jogosultság", "jogosultsag", "permission", "access",
               "hozzáfér", "hozzafer", "drive", "tiktok kód", "tiktok kod", "kód",
               "kod", "letölt", "letolt", "download", "feltölt", "feltolt", "admin",
               "fájl", "fajl", "file"],
    "Leadership": ["stratég", "strateg", "strategy", "hiring terv", "vízió", "vizio",
                    "vision", "döntés", "dontes", "decision", "roadmap", "csapat",
                    "vezetői", "vezetoi", "leadership", "tervezés", "tervezes"],
}

_RED = ["slack", "kód", "kod", "code", "jogosultság", "jogosultsag", "permission",
        "access", "hozzáfér", "hozzafer", "drive", "email", "e-mail", "számla",
        "szamla", "invoice", "letölt", "letolt", "download", "státusz", "statusz",
        "status", "chase", "átrak", "atrak", "fennakad", "block", "fájl", "fajl"]
_GREEN = ["stratég", "strateg", "strategy", "sales", "ajánlat", "ajanlat", "vízió",
          "vizio", "partner", "döntés", "dontes", "decision", "tervezés", "tervezes",
          "építés", "epites", "hiring", "felvétel", "felvetel"]
_INTERRUPT = ["slack", "kód", "kod", "code", "jogosultság", "jogosultsag",
              "permission", "access", "hozzáfér", "hozzafer", "gyors", "quick",
              "felhívott", "felhivott", "called", "üzenet", "uzenet", "message",
              "kérdez", "kerdez", "ping", "fennakad", "block"]
_AUTOMATABLE = ["statisztik", "statistic", "metricool", "report", "riport", "export",
                "számla", "szamla", "invoice", "reminder", "emlékeztet", "emlekeztet",
                "letölt", "letolt", "download", "backup", "kód", "kod"]


def _has(text, words):
    return any(w in text for w in words)


def heuristic_analyze(task_name, minutes, person):
    t = task_name.lower()

    # Department: score by keyword hits, default Admin
    dept = "Admin"
    best = 0
    for d, words in _KW.items():
        score = sum(1 for w in words if w in t)
        if score > best:
            best, dept = score, d

    # Energy
    if _has(t, _GREEN):
        energy = "green"
    elif _has(t, _RED):
        energy = "red"
    else:
        energy = "yellow"

    interrupt = _has(t, _INTERRUPT) or (minutes <= 10 and energy == "red")
    automatable = _has(t, _AUTOMATABLE)

    # Business value by department + energy
    if dept == "Leadership" or (dept == "Sales" and minutes >= 20):
        value = "$$$$"
    elif dept in ("Client Success", "Sales"):
        value = "$$$"
    elif dept in ("Operations", "Finance", "HR", "Production"):
        value = "$$"
    else:
        value = "$"

    # DRIP
    if value == "$$$$":
        drip = "Production"          # founder-level value creation / sales
    elif automatable:
        drip = "Replacement"         # replace with a system
    elif value in ("$", "$$"):
        drip = "Delegation"
    else:
        drip = "Investment"

    # Decision
    if value == "$$$$":
        decision = "Keep"
    elif automatable:
        decision = "Automate"
    elif interrupt and value in ("$", "$$"):
        decision = "Delegate ASAP"
    elif value == "$":
        decision = "Batch" if not interrupt else "Delegate ASAP"
    elif value == "$$":
        decision = "Playbook Needed"
    else:
        decision = "Review Later"

    playbook_needed = decision in ("Playbook Needed", "Delegate ASAP") or (
        value in ("$$", "$$$") and not automatable
    )

    # Owner / role
    if value == "$$$$":
        owner, role = "Keep with founder", "Founder"
    elif dept == "Finance":
        owner, role = "Finance Assistant", "Finance Assistant"
    elif dept in ("Operations", "Admin"):
        owner, role = "Founder Assistant", "Founder / Operations Assistant"
    elif dept == "Client Success":
        owner, role = "Delivery Manager", "Delivery / PM Lead"
    elif dept == "Production":
        owner, role = "Production team", "Producer / Editor"
    elif dept == "HR":
        owner, role = "Ops / HR Assistant", "Operations Assistant"
    else:
        owner, role = "Lili", "Operations Lead"

    recs = _heuristic_recs(dept, decision, automatable, playbook_needed, t)

    # Weekly estimate: assume this kind of task recurs a few times a week.
    freq = 5 if interrupt else (3 if value in ("$", "$$") else 1)
    weekly = minutes * freq

    return {
        "department": dept,
        "business_value": value,
        "energy": energy,
        "interrupt": interrupt,
        "drip": drip,
        "decision": decision,
        "recommended_owner": owner,
        "recommended_role": role,
        "automatable": automatable,
        "playbook_needed": playbook_needed,
        "weekly_time_estimate": weekly,
        "recommendations": recs,
    }


def _heuristic_recs(dept, decision, automatable, playbook, t):
    recs = []
    if "tiktok" in t or "kód" in t or "kod" in t or "jelszó" in t or "jelszo" in t:
        recs += ["Shared password manager (1Password/Bitwarden)",
                 "Shared team accounts instead of personal logins",
                 "Founder assistant owns access requests"]
    if "metricool" in t or "statisztik" in t or "statistic" in t or "report" in t:
        recs += ["Reporting SOP with fixed cadence",
                 "Automated dashboard / scheduled exports",
                 "PM owns client reporting"]
    if "slack" in t or "üzenet" in t or "uzenet" in t:
        recs += ["Async communication rules",
                 "Founder office hours / batching windows",
                 "Escalation framework so not everything reaches founders"]
    if "jogosultság" in t or "jogosultsag" in t or "access" in t or "drive" in t or "permission" in t:
        recs += ["Standardized access/permission template per role",
                 "Onboarding checklist that grants access up front",
                 "Ops owns access management"]
    if "számla" in t or "szamla" in t or "invoice" in t or "fizet" in t:
        recs += ["Invoicing automation / accounting tool",
                 "Finance assistant owns billing",
                 "Recurring invoice templates"]
    if "meeting" in t or "naptár" in t or "naptar" in t or "egyeztet" in t or "átrak" in t or "atrak" in t:
        recs += ["Self-serve scheduling link (Calendly/Cal.com)",
                 "Assistant owns calendar management"]
    if not recs:
        if automatable:
            recs = ["Automate with a tool or script", "Define a repeatable workflow"]
        elif decision == "Keep":
            recs = ["Protect focus time for this", "Keep founder-owned"]
        else:
            recs = ["Write an SOP and delegate", "Assign a clear owner"]
    # de-dupe, cap at 4
    seen, out = set(), []
    for r in recs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out[:4]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _coerce(result, task_name, minutes, person):
    """Validate / clamp an analysis dict to the schema, filling gaps."""
    base = heuristic_analyze(task_name, minutes, person)
    if not isinstance(result, dict):
        return base
    out = dict(base)
    if result.get("department") in DEPARTMENTS:
        out["department"] = result["department"]
    if result.get("business_value") in BUSINESS_VALUES:
        out["business_value"] = result["business_value"]
    if result.get("energy") in ENERGY:
        out["energy"] = result["energy"]
    if result.get("drip") in DRIP:
        out["drip"] = result["drip"]
    if result.get("decision") in DECISIONS:
        out["decision"] = result["decision"]
    for k in ("interrupt", "automatable", "playbook_needed"):
        if isinstance(result.get(k), bool):
            out[k] = result[k]
    for k in ("recommended_owner", "recommended_role"):
        if isinstance(result.get(k), str) and result[k].strip():
            out[k] = result[k].strip()
    if isinstance(result.get("weekly_time_estimate"), (int, float)):
        out["weekly_time_estimate"] = max(0, round(result["weekly_time_estimate"]))
    recs = result.get("recommendations")
    if isinstance(recs, list):
        clean = [str(r).strip() for r in recs if str(r).strip()]
        if clean:
            out["recommendations"] = clean[:4]
    return out


def analyze(task_name, minutes, person):
    """Classify a task. Uses Claude if a key is present, else heuristics."""
    if API_KEY:
        try:
            raw = _call_anthropic(task_name, minutes, person)
            res = _coerce(raw, task_name, minutes, person)
            res["engine"] = "ai"
            return res
        except Exception as e:  # network/api/parse failure -> graceful fallback
            res = heuristic_analyze(task_name, minutes, person)
            res["engine"] = "heuristic"
            res["engine_error"] = str(e)[:200]
            return res
    res = heuristic_analyze(task_name, minutes, person)
    res["engine"] = "heuristic"
    return res
