# SPIRAL

**Self-iterating PRD Research & Implementation Autonomous Loop**

SPIRAL autonomously discovers requirements, generates user stories, and implements them. Given a `prd.json` file, it loops through research, test synthesis, story merging, and implementation until all stories pass.

## How It Works

Each iteration runs 7 phases:

```
R) RESEARCH     — Claude agent searches sources → story candidates
T) TEST SYNTH   — Scan test failures → story candidates
M) MERGE        — Deduplicate + patch prd.json
G) GATE         — Human checkpoint (or auto: --gate proceed/skip/quit)
I) IMPLEMENT    — Ralph autonomous loop (sequential or parallel workers)
V) VALIDATE     — Run project test suite
C) CHECK DONE   — All stories pass? Exit. Otherwise loop.
```

## Install

```bash
git clone https://github.com/wenjyue84/spiral.git ~/.ai/Skills/spiral
```

Requires:
- `bash` (Git Bash / MSYS2 on Windows, native on Mac/Linux)
- `jq` (`choco install jq` / `brew install jq` / `apt install jq`)
- [Ralph](https://github.com/wenjyue84/ralph) at `~/.ai/Skills/ralph/`
- `claude` CLI (Anthropic Claude Code)
- Python 3.10+

## Quickstart

```bash
cd your-project

# 1. Create config (copy and edit)
cp ~/.ai/Skills/spiral/templates/spiral.config.example.sh spiral.config.sh

# 2. Ensure prd.json exists in project root
#    (see prd.json format below)

# 3. Run — research + merge only (no implementation)
bash ~/.ai/Skills/spiral/spiral.sh 1 --gate skip

# 4. Run — fully autonomous
bash ~/.ai/Skills/spiral/spiral.sh 20 --gate proceed

# 5. Run — parallel with 3 workers
bash ~/.ai/Skills/spiral/spiral.sh 5 --gate proceed --ralph-workers 3
```

## CLI Options

```
bash spiral.sh [max_iters] [options]

Options:
  --gate proceed|skip|quit   Auto-answer gate prompts (default: interactive)
  --ralph-iters N            Max inner implementation iterations (default: 120)
  --ralph-workers N          Parallel worktree workers (default: 1)
  --skip-research            Skip Phase R (web research)
  --capacity-limit N         Skip Phase R when pending > N (default: 50)
  --monitor                  Open terminal per worker (default: on)
  --no-monitor               Disable per-worker terminals
  --config PATH              Path to spiral.config.sh (default: $REPO_ROOT/spiral.config.sh)
  --help                     Show help
```

## Configuration

Place `spiral.config.sh` in your project root. All variables have defaults:

| Variable | Purpose | Default |
|----------|---------|---------|
| `SPIRAL_PYTHON` | Python interpreter | `python3` |
| `SPIRAL_RALPH` | Path to ralph.sh | `~/.ai/Skills/ralph/ralph.sh` |
| `SPIRAL_RESEARCH_PROMPT` | Research prompt template | bundled generic |
| `SPIRAL_GEMINI_PROMPT` | Gemini pre-research prompt | _(skip)_ |
| `SPIRAL_GEMINI_ANNOTATE_PROMPT` | Gemini filesTouch prompt | _(skip)_ |
| `SPIRAL_VALIDATE_CMD` | Test suite command | `$SPIRAL_PYTHON tests/run_tests.py --report-dir test-reports` |
| `SPIRAL_REPORTS_DIR` | Test reports directory | `test-reports` |
| `SPIRAL_STORY_PREFIX` | Story ID prefix | `US` |
| `SPIRAL_PATCH_DIRS` | Dirs for git diff patches (parallel) | _(all)_ |
| `SPIRAL_DEPLOY_CMD` | Post-merge deploy command | _(skip)_ |
| `SPIRAL_TERMINAL` | Terminal emulator for --monitor | _(auto-detect)_ |
| `SPIRAL_STREAM_FMT` | Node.js stream formatter | `~/.ai/Skills/ralph/stream-formatter.mjs` |

See [`templates/spiral.config.example.sh`](templates/spiral.config.example.sh) for full documentation.

## Runtime Scratch Directory

SPIRAL writes all temporary files to `.spiral/` in the project root:

```
.spiral/
├── _checkpoint.json         # Crash recovery state
├── _last_run.log            # Full console output
├── _research_output.json    # Phase R output
├── _test_stories_output.json # Phase T output
├── _research_overflow.json  # Unused candidates for next iteration
└── workers/                 # Parallel worker prd files + logs
```

Add `.spiral/` to your `.gitignore`.

## prd.json Format

SPIRAL expects a `prd.json` in the project root with this structure:

```json
{
  "userStories": [
    {
      "id": "US-001",
      "title": "Implement user login",
      "priority": "high",
      "description": "Users should be able to log in with email and password",
      "acceptanceCriteria": ["Login form validates email format", "..."],
      "technicalNotes": ["Use bcrypt for password hashing"],
      "dependencies": [],
      "estimatedComplexity": "medium",
      "passes": false
    }
  ]
}
```

Key fields:
- `id`: Unique identifier (`{SPIRAL_STORY_PREFIX}-NNN`)
- `passes`: `true` when the story is implemented and verified
- `priority`: `critical` | `high` | `medium` | `low`
- `filesTouch`: Optional hint for parallel partitioning

## Crash Recovery

If SPIRAL is interrupted, re-running resumes from the last completed phase via `_checkpoint.json`. No work is lost.

## License

MIT
