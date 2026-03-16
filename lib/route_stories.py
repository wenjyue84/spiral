# lib/route_stories.py
import argparse
import json
import os
import re
import tempfile

# Simple keyword-based fallback complexity classifier (no ML dependencies, instant)
_COMPLEX_PATTERNS = re.compile(
    r"\b(parallel|orchestrat|multi.agent|dag|dependency|migration|refactor|arch|"
    r"integrat|security|auth|oauth|webhook|crawl|scrape|stream|async|concurr|"
    r"distribut|circuit.break|retry|backoff|cache|shard|partition)\b",
    re.IGNORECASE,
)


def _keyword_complexity(title: str) -> str:
    return "complex" if _COMPLEX_PATTERNS.search(title) else "simple"


def _try_load_semantic_router():
    """Load SemanticRouter with a 10-second timeout guard. Returns None on failure."""
    import threading

    result = [None]
    error = [None]

    def _load():
        try:
            try:
                from .semantic_router import create_complexity_router
            except ImportError:
                from semantic_router import create_complexity_router  # type: ignore[no-redef]
            result[0] = create_complexity_router()
        except Exception as exc:
            error[0] = exc

    t = threading.Thread(target=_load, daemon=True)
    t.start()
    t.join(timeout=10)
    if t.is_alive():
        print("[router] WARNING: SemanticRouter load timed out (>10s) — using keyword fallback")
        return None
    if error[0]:
        print(f"[router] WARNING: SemanticRouter unavailable ({error[0]}) — using keyword fallback")
        return None
    return result[0]


def route_stories(prd_path, profile):
    """
    Analyzes each pending story in the PRD file and annotates it with a recommended model.
    Uses a semantic router when available, falls back to keyword-based classification.
    """
    if not os.path.exists(prd_path):
        raise FileNotFoundError(f"[router] ERROR: PRD file not found at {prd_path}")

    try:
        with open(prd_path, "r", encoding="utf-8") as f:
            prd = json.load(f)
    except json.JSONDecodeError:
        print(f"[router] ERROR: Could not decode JSON from {prd_path}")
        return

    # Semantic router disabled: sentence-transformers/OpenBLAS causes OOM in constrained envs.
    # Keyword-based fallback is fast, reliable, and good enough for complexity classification.
    router = None
    stories_to_update = 0

    for story in prd.get("userStories", []):
        # Only route stories that are not yet done
        if story.get("passes") is not True:
            assigned_model = None
            if profile == "auto":
                story_title = story.get("title", "")
                if router is not None:
                    complexity = router.route(story_title) or "complex"
                else:
                    complexity = _keyword_complexity(story_title)

                assigned_model = "sonnet" if complexity == "complex" else "haiku"
                print(f"  [router] Story '{story.get('id')}' -> complexity: {complexity} -> model: {assigned_model}")
            else:
                # User forced a specific model (e.g., "opus", "sonnet", "haiku")
                assigned_model = profile
                print(f"  [router] Story '{story.get('id')}' -> profile: {profile} -> model: {assigned_model}")

            if assigned_model and story.get("model") != assigned_model:
                story["model"] = assigned_model
                stories_to_update += 1

    if stories_to_update > 0:
        print(f"[router] Writing models for {stories_to_update} stories to {prd_path}...")
        # Atomic write to prevent corruption
        temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(prd_path))
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as tf:
                json.dump(prd, tf, indent=2)
            os.replace(temp_path, prd_path)
        except Exception as e:
            print(f"[router] ERROR: Failed to write updated PRD file: {e}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
    else:
        print("[router] No story models needed updating.")


def main():
    parser = argparse.ArgumentParser(description="Route stories in prd.json to optimal models.")
    parser.add_argument("--prd", required=True, help="Path to the prd.json file.")
    parser.add_argument("--profile", required=True, help="The model routing profile (e.g., 'auto', 'opus', 'sonnet').")
    args = parser.parse_args()

    print("[router] Starting story routing...")
    route_stories(args.prd, args.profile)
    print("[router] Story routing complete.")


if __name__ == "__main__":
    main()
