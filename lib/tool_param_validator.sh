#!/bin/bash
# lib/tool_param_validator.sh — Tool parameter semantic validation (US-249)
#
# Validates tool call parameters against .spiral/tool-schema.json before execution.
# Logs invalid parameters to spiral_events.jsonl and checkpoint _toolErrors.
#
# Public API:
#   tool_schema_init                              → ensures .spiral/tool-schema.json exists; echoes path
#   validate_tool_params <tool> <args...>         → 0 (valid) / 1 (invalid); sets _tool_param_last_error
#   log_tool_error <tool> <param> <expected> <received> [story_id]
#   scan_stream_json_tool_params <stream_file> [story_id] → validates LLM bash tool_use calls; echoes error count

# ── Built-in schema defaults ──────────────────────────────────────────────────
_TOOL_SCHEMA_DEFAULTS='{
  "_comment": "SPIRAL tool parameter schema — defines valid parameters for worker-invoked tools.",
  "git": {
    "validSubcommands": ["add","commit","checkout","branch","merge","diff","log","status","fetch","pull","push","show","stash","worktree","reset","clean","tag","remote","config","init","clone","rebase","describe","apply","cherry-pick","revert","bisect","submodule"],
    "description": "Git version control system"
  },
  "python": {
    "validFlags": ["-m","-c","-u","-v","-W","-x","-O","-B","-d"],
    "validExtensions": [".py"],
    "description": "Python interpreter"
  },
  "python3": {
    "validFlags": ["-m","-c","-u","-v","-W","-x","-O","-B","-d"],
    "validExtensions": [".py"],
    "description": "Python 3 interpreter"
  },
  "bats": {
    "requireFileExists": false,
    "validExtensions": [".bats"],
    "description": "Bash Automated Testing System"
  },
  "jq": {
    "requireFilter": true,
    "description": "Command-line JSON processor"
  },
  "curl": {
    "validSchemes": ["http","https","ftp","ftps"],
    "requireUrl": true,
    "description": "URL data transfer tool"
  },
  "uv": {
    "validSubcommands": ["run","add","remove","sync","lock","pip","venv","tool","python","init","build","publish","export","tree","self"],
    "description": "Python package manager"
  },
  "npm": {
    "validSubcommands": ["run","install","test","build","start","ci","update","list","pack","publish","uninstall","exec","init","audit"],
    "description": "Node package manager"
  },
  "npx": {
    "description": "Node package executor (any package name allowed)"
  },
  "cargo": {
    "validSubcommands": ["build","test","check","clippy","run","clean","doc","fmt","bench","publish","install","update","init","new"],
    "description": "Rust package manager"
  }
}'

# ── tool_schema_init ──────────────────────────────────────────────────────────
# Ensures .spiral/tool-schema.json exists with built-in defaults.
# Echoes the resolved schema file path.
tool_schema_init() {
  local schema_file="${SPIRAL_SCRATCH_DIR:-.spiral}/tool-schema.json"
  if [[ ! -f "$schema_file" ]]; then
    mkdir -p "$(dirname "$schema_file")" 2>/dev/null || true
    printf '%s\n' "$_TOOL_SCHEMA_DEFAULTS" > "$schema_file" 2>/dev/null || true
  fi
  echo "$schema_file"
}

# ── validate_tool_params ──────────────────────────────────────────────────────
# validate_tool_params <tool> [args...]
# Pure-bash semantic validation. No subprocess, sub-millisecond execution.
# Returns 0 if valid, 1 if invalid.
# Sets global _tool_param_last_error="<param>|<expected>|<received>" on failure.
validate_tool_params() {
  local tool="$1"; shift
  _tool_param_last_error=""

  case "$tool" in
    git)
      # Find first non-flag argument (the subcommand)
      local subcmd=""
      for arg in "$@"; do
        [[ "$arg" == -* ]] && continue
        subcmd="$arg"
        break
      done
      if [[ -n "$subcmd" ]]; then
        local valid="add commit checkout branch merge diff log status fetch pull push show stash worktree reset clean tag remote config init clone rebase describe apply cherry-pick revert bisect submodule"
        if [[ " $valid " != *" $subcmd "* ]]; then
          _tool_param_last_error="subcommand|valid git subcommand (add,commit,checkout,...)|$subcmd"
          return 1
        fi
      fi
      ;;

    python|python3)
      # First positional argument must be -m/-c flag OR a .py file
      local first_pos=""
      for arg in "$@"; do
        [[ "$arg" == -* ]] && { first_pos="$arg"; break; }
        first_pos="$arg"
        break
      done
      if [[ -n "$first_pos" && "$first_pos" != -* ]]; then
        # It's a file path — must have .py extension
        if [[ "$first_pos" == *.* ]]; then
          local ext="${first_pos##*.}"
          if [[ "$ext" != "py" ]]; then
            _tool_param_last_error="file_path|*.py file|$first_pos"
            return 1
          fi
        fi
      fi
      ;;

    bats)
      # All non-flag arguments must have .bats extension
      for arg in "$@"; do
        [[ "$arg" == -* ]] && continue
        # Allow directories (no extension) and glob patterns
        if [[ "$arg" == *.* ]]; then
          local ext="${arg##*.}"
          if [[ "$ext" != "bats" ]]; then
            _tool_param_last_error="test_file|*.bats file|$arg"
            return 1
          fi
        fi
      done
      ;;

    jq)
      # Must have at least one positional argument (the filter)
      # Skip --arg NAME VALUE, --argjson NAME VAL, --rawfile, --slurpfile pairs
      local skip_count=0
      local has_filter=false
      for arg in "$@"; do
        if [[ $skip_count -gt 0 ]]; then
          skip_count=$((skip_count - 1))
          continue
        fi
        case "$arg" in
          --arg|--argjson|--rawfile|--slurpfile|--args|--jsonargs)
            skip_count=2
            continue
            ;;
          -*) continue ;;
          *)
            has_filter=true
            break
            ;;
        esac
      done
      if ! $has_filter; then
        _tool_param_last_error="filter|<jq filter expression>|<empty>"
        return 1
      fi
      ;;

    curl)
      # Validate URL scheme for any argument containing "://"
      local valid_schemes="http https ftp ftps"
      for arg in "$@"; do
        if [[ "$arg" == *"://"* ]]; then
          local scheme="${arg%%://*}"
          scheme="${scheme,,}"  # lowercase
          if [[ " $valid_schemes " != *" $scheme "* ]]; then
            _tool_param_last_error="url|http|https|ftp scheme|${scheme}://"
            return 1
          fi
        fi
      done
      ;;

    uv)
      if [[ $# -gt 0 ]]; then
        local subcmd="$1"
        local valid="run add remove sync lock pip venv tool python init build publish export tree self"
        if [[ "$subcmd" != -* && " $valid " != *" $subcmd "* ]]; then
          _tool_param_last_error="subcommand|valid uv subcommand (run,add,sync,...)|$subcmd"
          return 1
        fi
      fi
      ;;

    npm)
      if [[ $# -gt 0 ]]; then
        local subcmd="$1"
        local valid="run install test build start ci update list pack publish uninstall exec init audit"
        if [[ "$subcmd" != -* && " $valid " != *" $subcmd "* ]]; then
          _tool_param_last_error="subcommand|valid npm subcommand (run,install,test,...)|$subcmd"
          return 1
        fi
      fi
      ;;

    cargo)
      if [[ $# -gt 0 ]]; then
        local subcmd="$1"
        local valid="build test check clippy run clean doc fmt bench publish install update init new"
        if [[ "$subcmd" != -* && " $valid " != *" $subcmd "* ]]; then
          _tool_param_last_error="subcommand|valid cargo subcommand (build,test,check,...)|$subcmd"
          return 1
        fi
      fi
      ;;
  esac

  return 0
}

# ── log_tool_error ────────────────────────────────────────────────────────────
# log_tool_error <tool> <parameter> <expected> <received> [story_id]
# Appends to spiral_events.jsonl AND checkpoint _toolErrors array.
log_tool_error() {
  local tool="$1"
  local parameter="$2"
  local expected="$3"
  local received="$4"
  local story_id="${5:-${NEXT_STORY:-unknown}}"
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "unknown")"

  # Append to spiral_events.jsonl (non-blocking)
  local log_file="${SPIRAL_SCRATCH_DIR:-.spiral}/spiral_events.jsonl"
  printf '{"ts":"%s","event":"tool_param_error","tool":"%s","parameter":"%s","expected":"%s","received":"%s","storyId":"%s"}\n' \
    "$ts" "$tool" "$parameter" "$expected" "$received" "$story_id" \
    >> "$log_file" 2>/dev/null || true

  # Append to checkpoint _toolErrors (non-blocking)
  local ckpt="${SPIRAL_SCRATCH_DIR:-.spiral}/_checkpoint.json"
  python3 - "$ckpt" "$tool" "$parameter" "$expected" "$received" "$story_id" "$ts" 2>/dev/null <<'CKPT_PY' || true
import sys, json, os

ckpt_file, tool, param, expected, received, story_id, ts = sys.argv[1:]

try:
    with open(ckpt_file, encoding='utf-8') as f:
        ckpt = json.load(f)
except Exception:
    ckpt = {}

errors = ckpt.setdefault('_toolErrors', [])
errors.append({
    'tool': tool,
    'parameter': param,
    'expected': expected,
    'received': received,
    'storyId': story_id,
    'timestamp': ts
})

tmp = ckpt_file + '.tmp'
try:
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(ckpt, f, indent=2)
    os.replace(tmp, ckpt_file)
except Exception:
    pass
CKPT_PY
}

# ── scan_stream_json_tool_params ──────────────────────────────────────────────
# scan_stream_json_tool_params <stream_json_file> [story_id]
# Parses LLM stream-json output, extracts Bash tool_use commands, and validates
# tool parameters against the schema.
# Logs any invalid parameters to spiral_events.jsonl and checkpoint.
# Echoes the count of parameter violations found.
scan_stream_json_tool_params() {
  local stream_file="$1"
  local story_id="${2:-${NEXT_STORY:-unknown}}"

  if [[ ! -f "$stream_file" ]]; then
    echo 0
    return 0
  fi

  # Extract bash commands from LLM stream-json
  local commands
  commands=$(python3 - "$stream_file" 2>/dev/null <<'EXTRACT_PY'
import sys, json

stream_file = sys.argv[1]
try:
    with open(stream_file, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get('type') == 'assistant':
                    for block in obj.get('message', {}).get('content', []):
                        if (isinstance(block, dict)
                                and block.get('type') == 'tool_use'
                                and block.get('name') == 'Bash'):
                            cmd = block.get('input', {}).get('command', '')
                            if cmd:
                                # Print first token (the actual command) + full args line
                                print(cmd.split('\n')[0].strip())
            except Exception:
                pass
except Exception:
    pass
EXTRACT_PY
  ) || commands=""

  local error_count=0

  while IFS= read -r cmd; do
    [[ -z "$cmd" ]] && continue

    # Extract tool and arguments from command line
    local -a tokens
    read -ra tokens <<< "$cmd"
    local tool="${tokens[0]}"
    local args=("${tokens[@]:1}")

    # Skip empty or shell builtins
    [[ -z "$tool" || "$tool" == "#" ]] && continue

    if ! validate_tool_params "$tool" "${args[@]}"; then
      # Parse error info from _tool_param_last_error (format: param|expected|received)
      local err_param err_expected err_received
      IFS='|' read -r err_param err_expected err_received <<< "$_tool_param_last_error"
      log_tool_error "$tool" "${err_param:-unknown}" "${err_expected:-unknown}" "${err_received:-unknown}" "$story_id"
      echo "  [tool-validate] WARN $tool: invalid '$err_param' — expected '$err_expected', got '$err_received'" >&2
      error_count=$((error_count + 1))
    fi
  done <<< "$commands"

  echo "$error_count"
}
