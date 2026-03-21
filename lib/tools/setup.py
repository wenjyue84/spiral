# lib/setup.py
import os
import sys

import questionary

# Detect stack before prompting — provides smart defaults
sys.path.insert(0, os.path.dirname(__file__))
from detect_stack import format_summary, load_or_detect


def _validate_float(text: str) -> bool:
    """Validate that text is a float between 0 and 1."""
    try:
        val = float(text)
        return 0 <= val <= 1
    except ValueError:
        return False


def create_config_file(config: dict[str, object]) -> None:
    """Creates the spiral.config.sh file from a dictionary of settings."""
    content = "#!/bin/bash\n\n# Spiral Configuration\n\n"
    for key, value in config.items():
        content += f'export {key}="{value}"\n'

    with open("spiral.config.sh", "w") as f:
        f.write(content)
    print("✅ Created spiral.config.sh")


def setup_wizard() -> None:
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
        ],
    ).ask()

    config = {}

    if config_profile == "🚀 Quick Start (recommended)":
        config = {
            "SPIRAL_MODEL_ROUTING": "auto",
            "SPIRAL_STORY_COST_HARD_USD": "2.00",
            "SPIRAL_VALIDATE_CMD": _default_validate_cmd,
        }
        print("\nUsing default settings for a balanced cost/performance profile.")
        if _stack.get("detected"):
            print(f"  Test command auto-detected: {_default_validate_cmd}")
        print("You can always run `spiral init` again to change these settings.")
    else:
        print("\nLet's configure Spiral to your needs.\n")

        # ── CORE: Model Routing & Cost ──────────────────────────────────────────
        print("╔═ CORE SETTINGS ════════════════════════════════════════════════════╗")
        print("║ These settings control model selection and spending limits.        ║")
        print("╚════════════════════════════════════════════════════════════════════╝\n")

        config["SPIRAL_MODEL_ROUTING"] = questionary.select(
            "Model routing strategy:",
            choices=[
                {"name": "💰 Cost-Conscious (haiku only, fastest & cheapest)", "value": "haiku"},
                {"name": "⚖️ Balanced (auto-route haiku→sonnet→opus, recommended)", "value": "auto"},
                {"name": "🚀 Performance (opus, slowest & most expensive)", "value": "opus"},
            ],
            instruction=(
                "The 'auto' profile uses a fast, cheap model to classify tasks and routes them "
                "to the appropriate model (haiku, sonnet, or opus) based on complexity."
            ),
        ).ask()

        config["SPIRAL_STORY_COST_HARD_USD"] = questionary.text(
            "Hard cost limit per story (in USD):",
            default="2.00",
            validate=lambda text: text.replace(".", "", 1).isdigit() or "Please enter a valid number.",
            instruction="Stories exceeding this cost are abandoned. Set 0 for unlimited.",
        ).ask()

        config["SPIRAL_VALIDATE_CMD"] = questionary.text(
            "Test command to run your project's validation suite:",
            default=_default_validate_cmd,
        ).ask()

        # ── PERFORMANCE: Thinking & Dispatch ────────────────────────────────────
        print("\n╔═ PERFORMANCE ══════════════════════════════════════════════════════╗")
        print("║ Control thinking budget and parallel execution strategy.          ║")
        print("╚════════════════════════════════════════════════════════════════════╝\n")

        use_advanced_perf = questionary.confirm(
            "Configure advanced performance options? (thinking budget, dispatch mode)",
            default=False,
        ).ask()

        if use_advanced_perf:
            config["SPIRAL_THINKING_BUDGET_TOKENS"] = questionary.text(
                "Thinking budget per story (tokens, 0=disabled):",
                default="10000",
                validate=lambda text: text.isdigit() or "Please enter a number.",
                instruction="Higher = more reasoning = slower & more expensive. Set 0 to disable thinking.",
            ).ask()

            config["SPIRAL_DISPATCH_MODE"] = questionary.select(
                "Worker dispatch strategy:",
                choices=[
                    {"name": "📊 DAG-aware (tier-based parallelism, respects dependencies)", "value": "dag"},
                    {"name": "⚡ Parallel (all workers run simultaneously, legacy mode)", "value": "parallel"},
                ],
                instruction="DAG mode is smarter but parallel mode is simpler.",
            ).ask()

        # ── COST CONTROL: Ceiling & Caching ────────────────────────────────────
        print("\n╔═ COST CONTROL ═════════════════════════════════════════════════════╗")
        print("║ Cap total spending and reuse research across iterations.          ║")
        print("╚════════════════════════════════════════════════════════════════════╝\n")

        use_cost_control = questionary.confirm(
            "Configure cost ceiling & caching?",
            default=False,
        ).ask()

        if use_cost_control:
            cost_ceiling = questionary.text(
                "Total spending ceiling (USD, empty=unlimited):",
                default="",
                instruction="Spiral exits when cumulative API spend exceeds this.",
            ).ask()
            if cost_ceiling.strip():
                config["SPIRAL_COST_CEILING"] = cost_ceiling.strip()

            cache_ttl = questionary.text(
                "Research cache TTL (hours, 0=disabled):",
                default="4",
                validate=lambda text: text.isdigit() or "Please enter a number.",
                instruction="Reuse research results if generated within N hours.",
            ).ask()
            if cache_ttl and int(cache_ttl) > 0:
                config["SPIRAL_RESEARCH_CACHE_TTL_HOURS"] = cache_ttl

        # ── QUALITY: Validation & Dedup ────────────────────────────────────────
        print("\n╔═ QUALITY ══════════════════════════════════════════════════════════╗")
        print("║ Improve story validation and reduce duplicates.                   ║")
        print("╚════════════════════════════════════════════════════════════════════╝\n")

        use_quality = questionary.confirm(
            "Configure validation & dedup options?",
            default=False,
        ).ask()

        if use_quality:
            config["SPIRAL_VALIDATION_VOTES"] = questionary.select(
                "Story validation consensus votes:",
                choices=[
                    {"name": "Fast (single validation, risk of false positives)", "value": "1"},
                    {"name": "Balanced (3 votes, 13.2% error reduction)", "value": "3"},
                    {"name": "Thorough (5 votes, highest quality but 5x more expensive)", "value": "5"},
                ],
                instruction="More votes = higher accuracy but higher cost.",
            ).ask()

            dedup_thresh = questionary.text(
                "Semantic dedup threshold (0-1, 0.85 recommended):",
                default="0.85",
                validate=lambda text: _validate_float(text) or "Enter a decimal 0-1.",
                instruction="Stories with >threshold similarity to existing ones are rejected.",
            ).ask()
            if float(dedup_thresh) > 0:
                config["SPIRAL_SEMANTIC_DEDUP_THRESHOLD"] = dedup_thresh

        # ── DEVELOPER: UX & Windows ────────────────────────────────────────────
        print("\n╔═ DEVELOPER EXPERIENCE ════════════════════════════════════════════╗")
        print("║ Visual validation, screenshots, and Windows-specific options.     ║")
        print("╚════════════════════════════════════════════════════════════════════╝\n")

        dev_url = questionary.text(
            "Dev server URL for visual validation (http://localhost:3000 or empty):",
            default="",
            instruction="If set, Phase V will capture screenshots after tests pass.",
        ).ask()
        if dev_url.strip():
            config["SPIRAL_DEV_URL"] = dev_url.strip()

        if sys.platform == "win32":
            skip_disk = questionary.confirm(
                "Skip disk space preflight check? (recommended on Windows NTFS)",
                default=True,
            ).ask()
            if skip_disk:
                config["SPIRAL_SKIP_DISK_CHECK"] = "1"

        # ── ADVANCED: Failure Handling & Features ──────────────────────────────
        print("\n╔═ ADVANCED STRATEGIES ══════════════════════════════════════════════╗")
        print("║ Failure handling, decomposition, and experimental features.       ║")
        print("╚════════════════════════════════════════════════════════════════════╝\n")

        use_advanced_strategies = questionary.confirm(
            "Configure advanced strategies? (anti-patterns, decomposition, episodic memory)",
            default=False,
        ).ask()

        if use_advanced_strategies:
            config["SPIRAL_ANTI_PATTERN_INJECT"] = questionary.select(
                "Anti-pattern learning on failures:",
                choices=[
                    {"name": "Enabled (log failed approaches, avoid them on retry)", "value": "true"},
                    {"name": "Disabled", "value": "false"},
                ],
            ).ask()

            config["SPIRAL_DECOMPOSE_ON_FIRST_FAIL"] = questionary.select(
                "Aggressive early decomposition:",
                choices=[
                    {"name": "Enabled (split oversized stories on first failure)", "value": "true"},
                    {"name": "Disabled (use retry escalation instead)", "value": "false"},
                ],
            ).ask()

            use_episodic = questionary.confirm(
                "Enable episodic memory? (inject past implementations as examples)",
                default=False,
            ).ask()
            if use_episodic:
                config["SPIRAL_EPISODIC_MEMORY"] = "true"

    create_config_file(config)


if __name__ == "__main__":
    setup_wizard()
