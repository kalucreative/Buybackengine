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
    "Strategy", "Team building", "Sales", "Client Success",
    "Marketing", "Operations", "Finance", "HR",
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

DEPARTMENTS — classify by the task's FUNCTION (what area it belongs to), NOT by how
valuable it is (value is captured separately in business_value). Pick exactly one:
- "Strategy": vision, planning, major decisions, partnerships, fundraising, company
  direction and growth — founder-level strategic thinking.
- "Team building": leading and managing the existing team — 1:1s, coaching, motivation,
  internal team meetings, organizational/people decisions (NOT recruiting paperwork).
- "Sales": new business — sales calls, offers, follow-ups, new leads, pitches, deals.
- "Client Success": existing clients — client calls, reports, statistics, feedback,
  project status, retention, handling client issues and relationships.
- "Marketing": KALU's OWN marketing — content the company makes for itself (recordings,
  videos, blog posts), social media, brand, ads for KALU.
- "Operations": day-to-day execution and coordination — internal organization, Slack,
  calendar, scheduling, access/permissions, admin, files, problem-solving, and
  production/editing execution. This is the default for low-value operational work.
- "Finance": invoices, payments, subscriptions, banking, accounting.
- "HR": recruiting, applicants, interviews, contracts, vacations, onboarding.

KALU TEAM — use this to resolve names mentioned in tasks and route them correctly:
Owners/leads: Katona Zsombor ("Zsombi") = co-owner / Operatív igazgató, also runs Finance;
Luczy Martin ("Martin") = co-owner / Kreatív igazgató, also runs Marketing/PR and HR;
Körmendi Lili ("Lili") = Operatív vezető (ops lead).
- Sales: Fodor Évi.
- HR: Mészáros Fanni.
- Finance: Katona Zsombor.
- Strategy: Nagyváti Bogi (strategist).
- Marketing: Luczy Martin. Social media: Katona Tamás — route to Marketing if it's KALU's
  own content, or Client Success if it's a client's; decide from the task wording.
- Client Success (existing clients): Account Director Kocsis Dávid; Accounts: Farkas Dorka,
  Farkas Szandra, Lestyán Bogi, Simon Panni, Kovács Rebeka, Mucsi Dominika. Ad managers
  (they manage CLIENTS' ads): Nikolics Daniella, Kiss Dániel, Csáfordi Dávid.
- Operations (production / "Gyártás" — content execution): Head of Content Sóvári Robi &
  Szabó Levi; editing/camera lead Encsi Gabi; Copywriters Gladity Alexandra, Peti Koltai,
  Klotz Erik, Kardos Luca; Camera Kis Norbert; Editors Pósa András, Szabó Bence,
  Kovács Richárd, Németh Dominik, Papp Zsombor; Camera+editor Molnár Peti, Pétervári Olivér,
  Szabó Márk, Somay Áron, Bene Márk; Graphic designer Luczy Júlia; Newsletter Kiss Dániel.
Notes: some names appear twice (Kiss Dániel, Encsi Gabi, Bene Márk) — use task context.
The company also works with ~200 VIDEO TALENT ("szereplő") NOT listed here — if a task is
about PAYING or TRANSFERRING money to a person who is NOT in the team list, treat it as a
video-talent payment → department "Finance".

Return ONLY a JSON object (no prose, no markdown) with EXACTLY these keys:
{
  "department": one of ["Strategy","Team building","Sales","Client Success","Marketing","Operations","Finance","HR"],
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
  "recommendations": [string, ...],                    // 2-4 concrete, practical buy-back moves (tools, SOPs, hires, systems)
  "needs_clarification": true|false,                   // true ONLY if the task is genuinely too vague/cryptic to classify confidently, even with the team list
  "clarification_question": string                     // if needs_clarification: ONE short, specific Hungarian question (e.g. "Ki az a Fanni, és pontosan mi a feladat?"); otherwise ""
}

Be decisive. Low-value reactive admin (TikTok codes, permissions, status chasing, \
Slack) -> red energy, interrupt true, $ or $$, Delegate/Automate. \
Strategy, sales, partnerships, key hires -> green, $$$$, Keep.

Clarification: keep it RARE. If the team list resolves the name or the task is reasonably \
clear, set needs_clarification=false. Only flag genuinely cryptic tasks (unknown names, no \
clear action). EVEN WHEN you flag it, still fill in your best-guess for every other field."""


def _corrections_block(corrections):
    """Build a 'learned corrections' section the AI applies to similar tasks."""
    if not corrections:
        return ""
    lines = []
    for c in corrections:
        lines.append(f'- "{c["task_name"]}" → {c["field"]}: {c["value"]}')
    return ("\n\nLEARNED CORRECTIONS — the team manually corrected these classifications. "
            "Apply the SAME logic to similar tasks going forward:\n" + "\n".join(lines))


def _call_anthropic(task_name, minutes, person, corrections=None):
    user = (
        f"Person: {person}\n"
        f"Task: {task_name}\n"
        f"Minutes spent: {minutes}\n\n"
        "Classify this task. Return only the JSON object."
    )
    payload = {
        "model": MODEL,
        "max_tokens": 700,
        "system": SYSTEM_PROMPT + _corrections_block(corrections),
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
            "felvétel", "felvetel", "toborz", "állás", "allas"],
    "Sales": ["sales", "ajánlat", "ajanlat", "offer", "lead", "follow-up", "followup",
               "értékesít", "ertekesit", "deal", "pitch", "upsell", "új ügyfél",
               "uj ugyfel", "prospect", "partnership", "partner"],
    "Marketing": ["marketing", "blog", "blogcikk", "cikk", "social", "közösségi",
                   "kozossegi", "brand", "márka", "marka", "podcast", "reklám",
                   "reklam", "kampány", "kampany", "saját tartalom", "sajat tartalom",
                   "céges videó", "ceges video"],
    "Client Success": ["ügyfél", "ugyfel", "client", "statisztik", "statistic",
                        "metricool", "report", "riport", "feedback", "visszajelz",
                        "státusz", "statusz", "status", "kpmg", "biohair", "kgyd"],
    "Team building": ["csapat", "csapatépít", "csapatepit", "csapatvezet", "vezetői",
                       "vezetoi", "leadership", "motivác", "motivac", "coaching",
                       "1:1", "egy az egyben", "team"],
    "Strategy": ["stratég", "strateg", "strategy", "vízió", "vizio", "vision",
                  "döntés", "dontes", "decision", "roadmap", "tervezés", "tervezes",
                  "növekedés", "novekedes", "growth"],
    "Operations": ["slack", "koordin", "calendar", "naptár", "naptar", "meeting",
                    "ütemez", "utemez", "schedul", "átrak", "atrak", "egyeztet",
                    "szervez", "blokk", "block", "problem", "fennakad", "email",
                    "e-mail", "jogosultság", "jogosultsag", "permission", "access",
                    "hozzáfér", "hozzafer", "drive", "tiktok kód", "tiktok kod",
                    "kód", "kod", "letölt", "letolt", "download", "feltölt", "feltolt",
                    "admin", "fájl", "fajl", "file", "vágás", "vagas", "edit",
                    "forgatás", "forgatas", "render", "thumbnail", "grafik", "anyag"],
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

    # Department: score by keyword hits, default Operations
    dept = "Operations"
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

    # Business value by department
    if dept in ("Strategy", "Team building") or (dept == "Sales" and minutes >= 20):
        value = "$$$$"
    elif dept in ("Client Success", "Sales"):
        value = "$$$"
    elif dept in ("Marketing", "Finance", "HR"):
        value = "$$"
    elif dept == "Operations":
        # trivial reactive ops are $; coordination is $$
        value = "$" if (interrupt and minutes <= 10) else "$$"
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
    elif dept == "Operations":
        owner, role = "Founder Assistant", "Founder / Operations Assistant"
    elif dept == "Client Success":
        owner, role = "Delivery Manager", "Delivery / PM Lead"
    elif dept == "Marketing":
        owner, role = "Content / Marketing Assistant", "Content / Marketing Assistant"
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
        "needs_clarification": False,
        "clarification_question": "",
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
    if isinstance(result.get("needs_clarification"), bool):
        out["needs_clarification"] = result["needs_clarification"]
    if isinstance(result.get("clarification_question"), str):
        out["clarification_question"] = result["clarification_question"].strip()
    # only keep a question if we actually flagged clarification
    if not out.get("needs_clarification"):
        out["clarification_question"] = ""
    return out


def analyze(task_name, minutes, person, corrections=None):
    """Classify a task. Uses Claude if a key is present, else heuristics.
    `corrections` is a list of past manual fixes fed to the AI as examples."""
    if API_KEY:
        try:
            raw = _call_anthropic(task_name, minutes, person, corrections)
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
