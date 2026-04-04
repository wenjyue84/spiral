# SPIRAL Troubleshooting

Top 10 first-run failures and how to fix them.

## Error Reference

| Error | Cause | Fix |
|-------|-------|-----|
| `jq: not found` | jq not in PATH | Windows: it's at `ralph/jq.exe` (auto-used). Mac/Linux: `brew install jq` or `apt install jq` |
| `validate_env: SPIRAL_VALIDATE_CMD is empty` | Missing in config | Set `SPIRAL_VALIDATE_CMD="uv run pytest tests/ -v"` in `spiral.config.sh` |
| `uv: command not found` | uv not installed | `pip install uv` or see [uv install docs](https://docs.astral.sh/uv/getting-started/installation/) |
| `python3: command not found` | Wrong SPIRAL_PYTHON | Set `SPIRAL_PYTHON` to the full Python path in `spiral.config.sh` |
| `bats: command not found` | Submodules not initialized | `git submodule update --init --recursive` |
| `claude: not found` | Claude CLI not installed | `npm install -g @anthropic-ai/claude-code` |
| prd.json schema errors | Invalid edits or corruption | Run `uv run python lib/prd_schema.py prd.json` to diagnose |
| Zero progress after 3 iterations | Test command not working | Check `SPIRAL_VALIDATE_CMD` — it must exit 0 when tests pass |
| Node OOM crash | Too many workers × memory | Reduce `SPIRAL_RALPH_WORKERS` or set `SPIRAL_MEMORY_LIMIT=512` |

---

## Detailed Fixes

### uv not installed

`uv` is required for `uv run pytest`, `uv sync`, and `uv add`. Install it:

```bash
pip install uv
# or (macOS/Linux):
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### bats tests fail with "command not found"

The bats test framework is vendored as a git submodule. Initialize it:

```bash
git submodule update --init --recursive
```

### Python version too old

SPIRAL requires Python 3.13+. Check your version:

```bash
python3 --version
```

If you have multiple Python versions, set the path explicitly in `spiral.config.sh`:

```bash
SPIRAL_PYTHON="/usr/local/bin/python3.13"
```

### prd.json schema validation errors

Run the schema validator to get a clear error message:

```bash
uv run python lib/prd_schema.py prd.json
```

### Zero progress after several iterations

If SPIRAL runs but nothing gets implemented, check:

1. `SPIRAL_VALIDATE_CMD` is set and runs without error:
   ```bash
   eval "$SPIRAL_VALIDATE_CMD"
   ```
2. At least one test passes — SPIRAL needs a passing baseline to track progress.
3. Run `bash spiral.sh --doctor` to check all prerequisites.

### Node out-of-memory crash

If you see `JavaScript heap out of memory`:

```bash
# In spiral.config.sh:
SPIRAL_RALPH_WORKERS=1          # reduce parallel workers
SPIRAL_MEMORY_LIMIT=512         # cap per-worker V8 heap (MB)
```

---

## Pre-flight check

Run the built-in doctor to verify all dependencies in one shot:

```bash
bash spiral.sh --doctor
```

This checks bash, python, uv, node, jq, claude CLI, ANTHROPIC_API_KEY, prd.json, spiral.config.sh, and more.
