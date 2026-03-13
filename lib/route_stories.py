# lib/route_stories.py
import json
import argparse
import os
import subprocess
import tempfile

# Placeholder for the actual API call to Claude.
# In a real scenario, this would use the 'claude' or a similar library.
def call_claude(prompt, model="haiku"):
    """
    A placeholder function to simulate calling the Claude API.
    For this implementation, it uses simple heuristics to classify a story.
    """
    print(f"  [router] Simulating '{model}' call to classify story...")
    if "refactor" in prompt.lower() or "architecture" in prompt.lower() or "design" in prompt.lower():
        return "complex"
    return "simple"

def get_router_prompt(story):
    """
    Creates a token-efficient prompt for the router model to classify a story's complexity.
    """
    # Exclude fields that might be very long and not relevant for complexity assessment
    story_for_prompt = {k: v for k, v in story.items() if k not in ['acceptanceCriteria', 'technicalNotes']}
    return f"""
<task>Classify the complexity of the following user story.</task>
<story_json>
{json.dumps(story_for_prompt, indent=2)}
</story_json>
<rules>
- Respond with only a single word: 'simple' or 'complex'.
- 'simple': Can be solved by editing 1-2 files, has no major dependencies.
- 'complex': Involves multiple files, architectural changes, or deep logic.
</rules>
Complexity:"""

def route_stories(prd_path, profile):
    """
    Analyzes each pending story in the PRD file and annotates it with a recommended model.
    """
    if not os.path.exists(prd_path):
        raise FileNotFoundError(f"[router] ERROR: PRD file not found at {prd_path}")

    try:
        with open(prd_path, 'r', encoding='utf-8') as f:
            prd = json.load(f)
    except json.JSONDecodeError:
        print(f"[router] ERROR: Could not decode JSON from {prd_path}")
        return

    stories_to_update = 0
    for story in prd.get("userStories", []):
        # Only route stories that are not yet done
        if story.get("passes") is not True:
            assigned_model = None
            if profile == "auto":
                prompt = get_router_prompt(story)
                complexity = call_claude(prompt, model="haiku").strip().lower()
                if complexity == "complex":
                    assigned_model = "sonnet"
                else:
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
            # Replace the original file with the new one
            os.replace(temp_path, prd_path)
        except Exception as e:
            print(f"[router] ERROR: Failed to write updated PRD file: {e}")
            # Clean up temp file on error
            os.remove(temp_path)
        finally:
            # Ensure temp file is removed if it still exists
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
