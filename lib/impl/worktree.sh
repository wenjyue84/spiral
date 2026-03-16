#!/usr/bin/env bash

set -euo pipefail

sparse_checkout() {
  local paths_to_checkout=("$@")
  if [[ ${#paths_to_checkout[@]} -eq 0 ]]; then
    echo "Error: sparse_checkout() requires at least one path to checkout" >&2
    return 1
  fi

  echo "Configuring sparse-checkout for worker worktree..."
  git -C "$REPO_ROOT" sparse-checkout init --cone
  git -C "$REPO_ROOT" sparse-checkout set "${paths_to_checkout[@]}"
}