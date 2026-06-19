# KALU Founder Buyback Engine

An AI-powered decision engine that shows the founders (Zsombor, Martin) and ops
lead (Lili) **where their time goes and how to buy it back** — through delegation,
automation, processes (SOPs), and hiring.

> The question behind every screen: _"How can KALU buy back as much founder time as possible?"_

## Run it

No dependencies. No build step. Just Python 3.

```bash
cd "/path/to/Buyback System/V2"
python3 server.py
```

Then open **http://localhost:8000**.

To change the port: `PORT=9000 python3 server.py`

## Turn on real AI analysis

By default it uses a built-in Hungarian/English heuristic engine, so it works
immediately. To use real Claude analysis (richer, more nuanced classification &
recommendations), set an API key before starting:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
python3 server.py
```

Optionally pick the model (default `claude-sonnet-4-6`):

```bash
export BUYBACK_MODEL="claude-haiku-4-5-20251001"   # faster / cheaper
```

The sidebar pill shows which engine is active. If an API call ever fails, it
falls back to the heuristic engine automatically — the app never breaks.

## How it works

1. Open a person (**Zsombor / Martin / Lili**) and dump a task in plain language:
   `Felhívott az XY ügyfél - 10p`. It detects the task name and minutes.
2. The task instantly enters the AI pipeline — no button press. It's classified by:
   department, business value ($–$$$$), energy (green/yellow/red), interrupt,
   DRIP, a single decision (Keep / Delegate ASAP / Automate / Batch / Playbook /
   Needs New Hire / Review Later), recommended owner & role, and concrete
   buy-back recommendations.
3. The **Dashboard** aggregates everything into 5-second cards: delegatable /
   automatable / batchable hours, interruptions, focus loss, top time drains,
   missing positions, and estimated hours bought back per month.
4. **AI Insights** generates the executive summary: where time goes, recommended
   first & second hires, top SOP and automation opportunities, and patterns.

## Files

| File | Purpose |
|------|---------|
| `server.py` | Zero-dependency HTTP server, SQLite storage, dashboard/insights aggregation |
| `ai.py` | Task parsing + classification (Claude API with heuristic fallback) |
| `static/index.html` · `app.js` · `styles.css` | Dark-mode, Linear/Apple-like SPA |
| `buyback.db` | SQLite database (created on first run) |

## Notes

- Three users, no permissions, everyone sees everything — by design.
- Data lives in `buyback.db` next to `server.py`. Delete it to reset.
- The `.claude/launch.json` points at a `/tmp` copy used only for the in-app
  preview sandbox (it can't read iCloud paths); the real app runs from this folder.
