# lib/setup.py
import questionary
import os
import sys

# Detect stack before prompting — provides smart defaults
sys.path.insert(0, os.path.dirname(__file__))
from detect_stack import load_or_detect, format_summary


def create_config_file(config):
    """Creates the spiral.config.sh file from a dictionary of settings."""
    content = "#!/bin/bash\n\n# Spiral Configuration\n\n"
    for key, value in config.items():
        content += f'export {key}="{value}"\n'

    with open("spiral.config.sh", "w") as f:
        f.write(content)
    print("✅ Created spiral.config.sh")

def setup_wizard():
    """Runs the interactive setup wizard."""
    print("🌀 Welcome to the Spiral setup wizard!")

    # ── Auto-detect tech stack and display summary ──────────────────────────
    _stack = load_or_detect()
    print("\n── Tech Stack Detection ─────────────────────────────────────────────")
    # format_summary uses │ prefix intended for phase_0 display; strip for setup
    summary_lines = format_summary(_stack).replace("  │  ", "  ").replace("  │", "")
    print(summary_lines)
    print("─────────────────────────────────────────────────────────────────────\n")
    _default_validate_cmd = _stack["validate_cmd"]

    if os.path.exists("spiral.config.sh"):
        if not questionary.confirm("A spiral.config.sh file already exists. Do you want to overwrite it?").ask():
            print("Aborting setup.")
            return

    config_profile = questionary.select(
        "Choose a configuration profile:",
        choices=[
            "🚀 Quick Start (recommended)",
            "⚙️ Advanced Configuration",
        ]
    ).ask()

    config = {}

    if config_profile == "🚀 Quick Start (recommended)":
        config = {
            "SPIRAL_MODEL_PROFILE": "auto",
            "SPIRAL_STORY_COST_HARD_USD": "2.00",
            "SPIRAL_VALIDATE_CMD": _default_validate_cmd,
        }
        print("\nUsing default settings for a balanced cost/performance profile.")
        if _stack.get("detected"):
            print(f"  Test command auto-detected: {_default_validate_cmd}")
        print("You can always run `spiral init` again to change these settings.")
    else:
        print("\nLet's configure Spiral to your needs.")

        config["SPIRAL_MODEL_PROFILE"] = questionary.select(
            "Select your preferred model routing profile:",
            choices=[
                {
                    "name": "Cost-Conscious (uses smaller models, may be less accurate)",
                    "value": "haiku"
                },
                {
                    "name": "Balanced (recommended default)",
                    "value": "auto"
                },
                {
                    "name": "Performance-Focused (uses larger models, will be more expensive)",
                    "value": "opus"
                }
            ],
            instruction="The 'auto' profile uses a fast, cheap model to classify tasks and routes them to the appropriate model (haiku, sonnet, or opus)."
        ).ask()

        config["SPIRAL_STORY_COST_HARD_USD"] = questionary.text(
            "Set a hard cost limit per story (in USD). If a story exceeds this, it will be abandoned.",
            default="2.00",
            validate=lambda text: text.replace('.', '', 1).isdigit() or "Please enter a valid number."
        ).ask()

        config["SPIRAL_VALIDATE_CMD"] = questionary.text(
            "Enter the command to run your project's test suite:",
            default=_default_validate_cmd,
        ).ask()

    create_config_file(config)

if __name__ == "__main__":
    setup_wizard()
