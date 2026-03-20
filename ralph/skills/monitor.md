---
name: monitor
description: >
  Monitor SPIRAL's health over the last N minutes.
  Use when user types "/monitor 30m", "/monitor 15m", "/monitor 1h", or just "/monitor".
  Checks if user stories are progressing, investigates stalls, reports in plain language with timestamps.
---

# /monitor — SPIRAL Health Monitor

## Argument Parsing

- Extract `<N>m` or `<N>h` from the invocation text
- Default to `30` minutes if no argument provided
- Convert `<N>h` to minutes (e.g., `1h` → `60 minutes`)

---

## Step 1 — Gather Current State (run in parallel)

```bash
# 1a. Current story counts
cd "C:/Users/Jyue/Documents/1-projects/Software Projects/Spiral"
uv run python main.py status

# 1b. Last 5 commits with relative timestamps
cd "C:/Users/Jyue/Documents/1-projects/Software Projects/Spiral"
rtk git log --oneline -5

# 1c. Current time (MYT, UTC+8)
powershell -Command "Get-Date -Format 'dd/MM/yyyy, HH:mm:ss'"

# 1d. SPIRAL process check (Windows — use /c: for each pattern)
tasklist | findstr /c:"bash.exe" /c:"node.exe" /c:"python.exe" /c:"uv.exe"

# 1e. Checkpoint state
rtk read .spiral/_checkpoint.json 2>/dev/null || echo "no checkpoint"
```

Read the memory file for `spiral_last_passes`:
- Path: `C:\Users\Jyue\.claude\projects\C--Users-Jyue-Documents-1-projects-Software-Projects-Spiral\memory\project_spiral_passes.md`

---

## Step 2 — Compute Delta

- `delta = current_passes - spiral_last_passes`
- Parse last commit timestamp from `git log` output
- Compute `time_since_last_commit` in minutes

---

## Step 3 — Health Determination

| Condition | Verdict | Emoji |
|-----------|---------|-------|
| `delta > 0` | HEALTHY — stories are passing | ✅ |
| `delta == 0` AND processes detected AND last commit within window | WORKING — mid-implementation (normal) | 🔄 |
| `delta == 0` AND last commit older than window | STALLED — no progress, no recent commit | ⚠️ |
| `delta < 0` | REGRESSION — passes decreased | ❌ |
| No bash/node/python processes AND `delta == 0` | STOPPED — process not running | 🛑 |

**Important:** Presence of `bash.exe`, `node.exe`, or `python.exe` in `tasklist` means SPIRAL is running.
Do NOT conclude "stopped" unless process check returns zero results.

---

## Step 4 — If HEALTHY or WORKING

1. Report with **full datetime and timezone** — format: `DD/MM/YYYY, HH:MM:SS MYT`
2. Show progress: `current_passes / total stories (+delta since last check)`
3. Show current story being implemented (from checkpoint or git log)
4. Show last commit age
5. Include 2–3 contextually relevant suggestions (see pool below)
6. **Update memory file** with new passes count

---

## Step 5 — If STALLED, STOPPED, or REGRESSION

Run diagnostics **in parallel**:

```bash
# Retry counts
rtk read retry-counts.json 2>/dev/null | jq . || echo "no retry-counts.json"

# Worker directories
rtk ls .spiral-workers/ 2>/dev/null || echo "no workers"

# Last 30 lines of events
rtk read -30 spiral_events.jsonl 2>/dev/null || echo "no events file"
```

**Explain root cause in plain language.** Common causes:
- Process crashed vs. intentional stop
- Specific story blocking progress (check retry-counts.json)
- Stuck worker
- All iterations exhausted (normal completion)
- Cost ceiling hit

**Attempt to fix — spawn subagents, do not just report:**
1. Spawn a **Sonnet** subagent with the diagnosis context and a targeted fix task
2. Re-run `uv run python main.py status` after it completes to verify improvement
3. If problem persists, spawn an **Opus** subagent for a deeper fix
4. Report what was found, what was attempted, and the outcome

---

## Step 6 — Always Update Memory

Write the new passes count to:
`C:\Users\Jyue\.claude\projects\C--Users-Jyue-Documents-1-projects-Software-Projects-Spiral\memory\project_spiral_passes.md`

```markdown
---
name: spiral_last_passes
description: Last known SPIRAL passes count for health check delta comparison
type: project
---

spiral_last_passes: <N>

**Why:** Health check compares current passes to this baseline to detect stalls.
**How to apply:** On each health check, compare `main.py status` against this value. Equal or decreased → investigate.
```

---

## Report Format

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPIRAL Health Report — 20/03/2026, 09:18:08 MYT
Window: last 30 minutes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Status: ✅ HEALTHY  (or 🔄 WORKING / ⚠️ STALLED / 🛑 STOPPED / ❌ REGRESSION)

Progress: 62/73 stories passed (+1 since last check)
Current story: US-528 — Cost Predictor CLI: Estimate Pre-Phase I Story
Iteration: #3  |  Phase: I (Implement)
Last commit: 3 minutes ago — "feat(spiral): complete 1 stories (iter 2)"
Process: ✅ running (bash.exe × 14, node.exe × 9, python.exe × 3)

What's happening (plain language):
  SPIRAL is actively implementing US-528. It completed 1 new story since the
  last check and is in the middle of Iteration 3. Everything looks healthy.

💡 Suggested follow-ups:
  - "Show me which stories passed recently"
  - "Check cost estimate: uv run python main.py estimate"
  - "How many stories are still pending?"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPIRAL STATUS: HEALTHY — passes=62 — checked=20/03/2026 09:18:08 MYT
```

---

## Enhancement Suggestions Pool

Pick 2–3 based on context:

- If `delta > 0`: `"Show me which stories passed recently (rtk git log --oneline -10)"`
- If `pending > 10`: `"Ask about capping pending stories (SPIRAL_MAX_PENDING)"`
- If high retries in `retry-counts.json`: `"Ask about stories that keep failing"`
- If STALLED: `"Restart SPIRAL: bash spiral.sh 20 --gate proceed"`
- If STOPPED (all iterations done): `"Start a new run or check if all pending stories are exhausted"`
- If REGRESSION: `"Ask what story caused the regression"`
- General: `"Check cost estimate: uv run python main.py estimate"`
- General: `"Show phase trace at http://localhost:5299/spiral/phase-trace"`
- General: `"Check worker status: rtk ls .spiral-workers/"`
