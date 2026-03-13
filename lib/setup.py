# lib/setup.py
import questionary
import os
import shutil


def ask_advanced_options():
    """Ask advanced lifecycle tuning questions. Returns a dict of config values."""
    print("\n--- Advanced Options (Optional) ---")

    max_retries = questionary.text(
        "Max retries per failing story? "
        "(after N failures, story is skipped and marked for decomposition)",
        default="3",
        instruction=" Lower = faster (fail-fast), higher = more persistent."
    ).ask()

    # Validate max_retries is an integer
    try:
        max_retries = str(int(max_retries))
    except (ValueError, TypeError):
        max_retries = "3"

    gitnexus_repo = ""
    if shutil.which("gitnexus"):
        gitnexus_repo = questionary.text(
            "GitNexus repo name for semantic file hints? "
            "(improves parallel worker partitioning for new stories)",
            default="",
            instruction=" Leave blank to disable."
        ).ask() or ""
    else:
        print("  GitNexus CLI not detected — skipping. "
              "Install it to enable semantic file hints.")

    deploy_cmd = questionary.text(
        "Post-merge deploy command? "
        "(runs after each successful merge, e.g. npm run build)",
        default="",
        instruction=" Enables CI-style loop. Leave blank to skip."
    ).ask() or ""

    return {
        "max_retries": max_retries,
        "gitnexus_repo": gitnexus_repo,
        "deploy_cmd": deploy_cmd,
    }


def build_config(profile, research_model, advanced):
    """Build the spiral.config.sh content string."""
    lines = [
        '#!/bin/bash',
        '# Spiral Configuration',
        '',
        '# -- Model profile for implementation workers --',
        '# auto  = Per-story routing (haiku for simple, sonnet for complex)',
        '# sonnet/opus/haiku = Force all workers to use a specific model',
        f'SPIRAL_MODEL_ROUTING="{profile}"',
        '',
        '# -- Model for the Research (R) and Test Synthesis (T) phases --',
        f'SPIRAL_RESEARCH_MODEL="{research_model}"',
        '',
        '# -- Python interpreter command --',
        'SPIRAL_PYTHON="uv run python"',
        '',
        '# -- Test / validation command --',
        'SPIRAL_VALIDATE_CMD="uv run pytest tests/ -v --tb=short"',
        '',
        '# --- Advanced Lifecycle Tuning ---',
        '',
        '# Max retries per failing story before skip + decomposition',
        '# Lower = faster iteration (fail-fast), higher = more persistent',
        f'SPIRAL_MAX_RETRIES={advanced["max_retries"]}',
    ]

    if advanced["gitnexus_repo"]:
        lines += [
            '',
            '# GitNexus repo name for semantic file hints',
            '# Improves parallel worker partitioning for new stories',
            f'SPIRAL_GITNEXUS_REPO="{advanced["gitnexus_repo"]}"',
        ]

    if advanced["deploy_cmd"]:
        lines += [
            '',
            '# Post-merge deploy command (CI-style loop)',
            '# Runs after each successful story merge',
            f'SPIRAL_DEPLOY_CMD="{advanced["deploy_cmd"]}"',
        ]

    lines.append('')
    return '\n'.join(lines)


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

    advanced = ask_advanced_options()

    config_content = build_config(profile, research_model, advanced)

    with open("spiral.config.sh", "w") as f:
        f.write(config_content)

    print("\n'spiral.config.sh' created successfully.")
    print("You can now run 'bash spiral.sh'")

if __name__ == "__main__":
    main()
