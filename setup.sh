#!/bin/bash
# SPIRAL Setup — Fully automatic bootstrap
#
# One-liner install:
#   bash <(curl -sL https://raw.githubusercontent.com/wenjyue84/spiral/main/setup.sh)
#
# Or after cloning:
#   bash setup.sh
#
# Idempotent: running again skips already-installed tools.

set -euo pipefail

# ── Colors ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
BOLD='\033[1m'
RESET='\033[0m'

ok()   { printf "  ${GREEN}[OK]${RESET} %s\n" "$*"; }
warn() { printf "  ${YELLOW}[!!]${RESET} %s\n" "$*"; }
fail() { printf "  ${RED}[FAIL]${RESET} %s\n" "$*"; }
info() { printf "  ${DIM}%s${RESET}\n" "$*"; }

# ── Platform detection ─────────────────────────────────────────────────────
detect_platform() {
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*|*_NT*)
      PLATFORM="windows"
      PKG_MGR="choco"
      ;;
    Darwin*)
      PLATFORM="macos"
      PKG_MGR="brew"
      ;;
    Linux*)
      PLATFORM="linux"
      if command -v apt-get &>/dev/null; then
        PKG_MGR="apt"
      elif command -v dnf &>/dev/null; then
        PKG_MGR="dnf"
      elif command -v yum &>/dev/null; then
        PKG_MGR="yum"
      elif command -v pacman &>/dev/null; then
        PKG_MGR="pacman"
      else
        PKG_MGR="unknown"
      fi
      ;;
    *)
      PLATFORM="unknown"
      PKG_MGR="unknown"
      ;;
  esac
}

# ── Version check helpers ──────────────────────────────────────────────────
version_gte() {
  # Returns 0 if $1 >= $2 (semver major.minor comparison)
  local v1_major v1_minor v2_major v2_minor
  v1_major=$(echo "$1" | cut -d. -f1)
  v1_minor=$(echo "$1" | cut -d. -f2)
  v2_major=$(echo "$2" | cut -d. -f1)
  v2_minor=$(echo "$2" | cut -d. -f2)
  [[ "$v1_major" -gt "$v2_major" ]] && return 0
  [[ "$v1_major" -eq "$v2_major" && "$v1_minor" -ge "$v2_minor" ]] && return 0
  return 1
}

get_python_version() {
  local cmd="$1"
  "$cmd" --version 2>&1 | grep -oP '\d+\.\d+' | head -1
}

get_node_version() {
  node --version 2>&1 | grep -oP '\d+\.\d+' | head -1
}

# ── Install helpers ────────────────────────────────────────────────────────
install_pkg() {
  local pkg="$1"
  case "$PKG_MGR" in
    choco)   choco install -y "$pkg" 2>/dev/null ;;
    brew)    brew install "$pkg" 2>/dev/null ;;
    apt)     sudo apt-get install -y "$pkg" 2>/dev/null ;;
    dnf)     sudo dnf install -y "$pkg" 2>/dev/null ;;
    yum)     sudo yum install -y "$pkg" 2>/dev/null ;;
    pacman)  sudo pacman -S --noconfirm "$pkg" 2>/dev/null ;;
    *)       return 1 ;;
  esac
}

npm_install_global() {
  local pkg="$1"
  npm install -g "$pkg" 2>/dev/null
}

# ── Tracking ───────────────────────────────────────────────────────────────
RESULTS=()
track() {
  # track "tool_name" "status" "detail"
  RESULTS+=("$1|$2|$3")
}

# ── Banner ─────────────────────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}${CYAN}SPIRAL Setup${RESET}"
echo -e "  ${DIM}Self-iterating PRD Research & Implementation Autonomous Loop${RESET}"
echo ""

detect_platform
echo -e "  Platform:  ${BOLD}$PLATFORM${RESET} (package manager: $PKG_MGR)"
echo ""

# ── 1. Git ─────────────────────────────────────────────────────────────────
echo -e "  ${BOLD}Checking prerequisites...${RESET}"
echo ""

if command -v git &>/dev/null; then
  GIT_VER=$(git --version 2>&1 | grep -oP '\d+\.\d+\.\d+' | head -1)
  ok "git $GIT_VER"
  track "git" "ok" "$GIT_VER"
else
  fail "git — required but not found"
  echo "       Install git first: https://git-scm.com/downloads"
  track "git" "fail" "not found"
  exit 1
fi

# ── 2. Python 3.10+ ───────────────────────────────────────────────────────
PYTHON_CMD=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    ver=$(get_python_version "$cmd")
    if version_gte "$ver" "3.10"; then
      PYTHON_CMD="$cmd"
      break
    fi
  fi
done

if [[ -n "$PYTHON_CMD" ]]; then
  PYTHON_VER=$(get_python_version "$PYTHON_CMD")
  ok "python $PYTHON_VER ($PYTHON_CMD)"
  track "python" "ok" "$PYTHON_VER"
else
  info "Installing Python 3..."
  case "$PKG_MGR" in
    choco)  install_pkg "python3" ;;
    brew)   install_pkg "python3" ;;
    apt)    install_pkg "python3" ;;
    dnf)    install_pkg "python3" ;;
    *)      ;;
  esac
  # Re-check
  for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
      ver=$(get_python_version "$cmd")
      if version_gte "$ver" "3.10"; then
        PYTHON_CMD="$cmd"
        break
      fi
    fi
  done
  if [[ -n "$PYTHON_CMD" ]]; then
    ok "python $(get_python_version "$PYTHON_CMD") (just installed)"
    track "python" "ok" "$(get_python_version "$PYTHON_CMD")"
  else
    fail "python 3.10+ — could not install automatically"
    echo "       Install manually: https://www.python.org/downloads/"
    track "python" "fail" "not found"
  fi
fi

# ── 3. Node.js 16+ ────────────────────────────────────────────────────────
if command -v node &>/dev/null; then
  NODE_VER=$(get_node_version)
  if version_gte "$NODE_VER" "16.0"; then
    ok "node $NODE_VER"
    track "node" "ok" "$NODE_VER"
  else
    warn "node $NODE_VER — version 16+ recommended"
    track "node" "warn" "$NODE_VER (upgrade recommended)"
  fi
else
  info "Installing Node.js..."
  case "$PKG_MGR" in
    choco)  install_pkg "nodejs" ;;
    brew)   install_pkg "node" ;;
    apt)    install_pkg "nodejs" && install_pkg "npm" ;;
    *)      ;;
  esac
  if command -v node &>/dev/null; then
    NODE_VER=$(get_node_version)
    ok "node $NODE_VER (just installed)"
    track "node" "ok" "$NODE_VER"
  else
    fail "node — could not install automatically"
    echo "       Install manually: https://nodejs.org/"
    track "node" "fail" "not found"
  fi
fi

# ── 4. jq ─────────────────────────────────────────────────────────────────
if [[ "$PLATFORM" == "windows" ]]; then
  # Bundled jq.exe for Windows — no install needed
  ok "jq (bundled jq.exe for Windows)"
  track "jq" "ok" "bundled"
elif command -v jq &>/dev/null; then
  JQ_VER=$(jq --version 2>&1 | head -1)
  ok "jq $JQ_VER"
  track "jq" "ok" "$JQ_VER"
else
  info "Installing jq..."
  install_pkg "jq" || true
  if command -v jq &>/dev/null; then
    ok "jq $(jq --version 2>&1 | head -1) (just installed)"
    track "jq" "ok" "$(jq --version 2>&1 | head -1)"
  else
    warn "jq — not found (bundled jq.exe available on Windows only)"
    echo "       Install: https://jqlang.github.io/jq/download/"
    track "jq" "warn" "not found"
  fi
fi

# ── 5. Claude CLI (REQUIRED) ──────────────────────────────────────────────
if command -v claude &>/dev/null; then
  CLAUDE_VER=$(claude --version 2>&1 | head -1 || echo "installed")
  ok "claude CLI ($CLAUDE_VER)"
  track "claude" "ok" "$CLAUDE_VER"
else
  info "Installing Claude CLI..."
  npm_install_global "@anthropic-ai/claude-code" || true
  if command -v claude &>/dev/null; then
    CLAUDE_VER=$(claude --version 2>&1 | head -1 || echo "installed")
    ok "claude CLI ($CLAUDE_VER) (just installed)"
    track "claude" "ok" "$CLAUDE_VER"
  else
    fail "claude CLI — required but could not install"
    echo "       Install: npm install -g @anthropic-ai/claude-code"
    echo "       Docs: https://docs.anthropic.com/en/docs/claude-code"
    track "claude" "fail" "not found"
  fi
fi

# ── 6. Gemini CLI (OPTIONAL — token saver for Phase R web research) ──────
if command -v gemini &>/dev/null; then
  ok "gemini CLI (optional — token saver for Phase R)"
  track "gemini" "ok" "installed"
else
  info "Installing Gemini CLI (optional)..."
  npm_install_global "@google/gemini-cli" 2>/dev/null || true
  if command -v gemini &>/dev/null; then
    ok "gemini CLI (just installed — optional token saver)"
    track "gemini" "ok" "installed"
  else
    warn "gemini CLI — not found (optional, Phase R uses Claude instead)"
    echo "       Install later: npm install -g @google/gemini-cli"
    track "gemini" "warn" "not found (optional)"
  fi
fi

# ── 7. Codex CLI (OPTIONAL — token saver for UT-* test stories) ──────────
if command -v codex &>/dev/null; then
  ok "codex CLI (optional — token saver for UT-* stories)"
  track "codex" "ok" "installed"
else
  info "Installing Codex CLI (optional)..."
  npm_install_global "@openai/codex" 2>/dev/null || true
  if command -v codex &>/dev/null; then
    ok "codex CLI (just installed — optional token saver)"
    track "codex" "ok" "installed"
  else
    warn "codex CLI — not found (optional, Claude handles all stories instead)"
    echo "       Install later: npm install -g @openai/codex"
    track "codex" "warn" "not found (optional)"
  fi
fi

# ── Clone spiral (if running via curl pipe) ────────────────────────────────
echo ""
SPIRAL_DIR="${SPIRAL_INSTALL_DIR:-$HOME/.ai/Skills/spiral}"

# Detect if we're running from inside the spiral repo already
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" 2>/dev/null || echo ".")" && pwd)"
if [[ -f "$SCRIPT_DIR/spiral.sh" ]]; then
  echo -e "  ${DIM}Running from spiral repo: $SCRIPT_DIR${RESET}"
  SPIRAL_DIR="$SCRIPT_DIR"
elif [[ -d "$SPIRAL_DIR" && -f "$SPIRAL_DIR/spiral.sh" ]]; then
  echo -e "  ${DIM}SPIRAL already installed: $SPIRAL_DIR${RESET}"
else
  echo -e "  ${BOLD}Cloning SPIRAL...${RESET}"
  mkdir -p "$(dirname "$SPIRAL_DIR")"
  git clone https://github.com/wenjyue84/spiral.git "$SPIRAL_DIR" 2>&1 | head -5
  if [[ -f "$SPIRAL_DIR/spiral.sh" ]]; then
    ok "spiral cloned to $SPIRAL_DIR"
  else
    fail "spiral clone failed"
    exit 1
  fi
fi

# ── Summary ────────────────────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}${CYAN}Setup Summary${RESET}"
echo -e "  ${DIM}────────────────────────────────────────${RESET}"

REQUIRED_OK=true
for entry in "${RESULTS[@]}"; do
  IFS='|' read -r name status detail <<< "$entry"
  case "$status" in
    ok)   printf "  ${GREEN}[OK]${RESET}   %-12s %s\n" "$name" "$detail" ;;
    warn) printf "  ${YELLOW}[!!]${RESET}   %-12s %s\n" "$name" "$detail" ;;
    fail) printf "  ${RED}[FAIL]${RESET} %-12s %s\n" "$name" "$detail"
          # Check if required
          if [[ "$name" == "git" || "$name" == "python" || "$name" == "claude" ]]; then
            REQUIRED_OK=false
          fi
          ;;
  esac
done

echo -e "  ${DIM}────────────────────────────────────────${RESET}"
echo -e "  SPIRAL:     $SPIRAL_DIR"
echo ""

if [[ "$REQUIRED_OK" == "false" ]]; then
  echo -e "  ${RED}${BOLD}Some required tools are missing. Fix the errors above and re-run setup.sh${RESET}"
  exit 1
fi

# ── Smoke test ─────────────────────────────────────────────────────────────
echo -e "  ${BOLD}Smoke test...${RESET}"
if bash "$SPIRAL_DIR/spiral.sh" --help >/dev/null 2>&1; then
  ok "spiral.sh --help works"
else
  warn "spiral.sh --help returned non-zero (may still work)"
fi

echo ""
echo -e "  ${GREEN}${BOLD}SPIRAL is ready!${RESET}"
echo ""
echo -e "  ${BOLD}Quickstart:${RESET}"
echo "    cd your-project"
echo ""
echo "    # Option A: Setup wizard (recommended — in Claude Code)"
echo "    /spiral-init"
echo ""
echo "    # Option B: Manual setup"
echo "    cp $SPIRAL_DIR/templates/spiral.config.example.sh spiral.config.sh"
echo "    cp $SPIRAL_DIR/templates/prd.example.json prd.json"
echo "    bash $SPIRAL_DIR/spiral.sh 1 --gate skip"
echo ""
