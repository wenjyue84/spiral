# lib/setup.py
import questionary
import os

def main():
    if os.path.exists("spiral.config.sh"):
        if not questionary.confirm("A 'spiral.config.sh' already exists. Overwrite?").ask():
            print("Setup cancelled.")
            return

    print("--- Configuring Spiral ---")

    profile = questionary.select(
        "What is your priority for this project?",
        choices=[
            questionary.Choice(
                "Balanced (Recommended)",
                value="auto",
                checked=True
            ),
            questionary.Choice(
                "Maximum Quality",
                value="opus" # Use a high-end model for all tasks
            ),
            questionary.Choice(
                "Maximum Speed & Cost-Savings",
                value="haiku" # Use the cheapest model for all tasks
            ),
        ],
        instruction=" 'Balanced' uses a mix of models based on task complexity."
    ).ask()

    research_model = questionary.select(
        "Which model should be used for the Research phase?",
        choices=["sonnet", "haiku", "opus"],
        default="sonnet",
        instruction=" Sonnet is recommended for its strong synthesis capabilities."
    ).ask()

    config_content = f"""#!/bin/bash
# Spiral Configuration

# -- Model profile for implementation workers --
# auto  = Per-story routing (haiku for simple, sonnet for complex)
# sonnet/opus/haiku = Force all workers to use a specific model
SPIRAL_MODEL_ROUTING="{profile}"

# -- Model for the Research (R) and Test Synthesis (T) phases --
SPIRAL_RESEARCH_MODEL="{research_model}"

# -- Python interpreter command --
SPIRAL_PYTHON="uv run python"

# -- Test / validation command --
SPIRAL_VALIDATE_CMD="uv run pytest tests/ -v --tb=short"
"""

    with open("spiral.config.sh", "w") as f:
        f.write(config_content)

    print("
'spiral.config.sh' created successfully.")
    print("You can now run 'bash spiral.sh'")

if __name__ == "__main__":
    main()
