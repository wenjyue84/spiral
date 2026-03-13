# lib/route_stories.py
import json
import argparse
import os
import tempfile
from .semantic_router import create_complexity_router

def route_stories(prd_path, profile):
    """
    Analyzes each pending story in the PRD file and annotates it with a recommended model
    using a semantic router for complexity assessment.
    """
    if not os.path.exists(prd_path):
        raise FileNotFoundError(f"[router] ERROR: PRD file not found at {prd_path}")

    try:
        with open(prd_path, 'r', encoding='utf-8') as f:
            prd = json.load(f)
    except json.JSONDecodeError:
        print(f"[router] ERROR: Could not decode JSON from {prd_path}")
        return

    router = create_complexity_router()
    stories_to_update = 0

    for story in prd.get("userStories", []):
        # Only route stories that are not yet done
        if story.get("passes") is not True:
            assigned_model = None
            if profile == "auto":
                story_title = story.get("title", "")
                # Default to 'complex' if routing fails or is uncertain
                complexity = router.route(story_title) or "complex"

                if complexity == "complex":
                    assigned_model = "sonnet"
                else: # simple
                    assigned_model = "haiku"
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
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as tf:
                json.dump(prd, tf, indent=2)
            os.replace(temp_path, prd_path)
        except Exception as e:
            print(f"[router] ERROR: Failed to write updated PRD file: {e}")
            os.remove(temp_path)
        finally:
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

