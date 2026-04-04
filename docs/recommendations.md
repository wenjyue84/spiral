# Recommendations for Balancing Cost and Quality in Spiral

This document analyzes the Spiral agent's architecture for balancing token cost and output quality. It provides actionable recommendations based on existing patterns within the codebase.

## Executive Summary of Spiral's Architecture

The Spiral project employs a multi-faceted strategy that goes beyond simple model selection. It dynamically adjusts its approach based on task complexity, execution success, and pre-configured user preferences. This allows for a nuanced balance between minimizing token consumption and maximizing the quality of the generated code.

The core strategies are:
1.  **Dynamic Model Routing:** Automatically selecting the most cost-effective model for a given task and escalating to more powerful models only when necessary.
2.  **Intelligent Task Decomposition:** Proactively partitioning the entire workload for parallel execution and reactively breaking down complex, failing tasks into simpler sub-tasks.
3.  **Aggressive Token Efficiency:** Utilizing prompt engineering and output summarization to minimize the number of tokens processed in each cycle.

## Key Strategies & Implementation Details

### 1. Dynamic Model Routing & Complexity Assessment

The system uses a three-tiered model routing strategy, primarily orchestrated by `ralph/ralph.sh`.

-   **Mechanism:** The `SPIRAL_MODEL_ROUTING` variable in `spiral.config.sh` can be set to `'auto'`. In this mode, the `classify_model` function in `ralph.sh` scores each task (story) based on its metadata (`priority`, `estimatedComplexity`, `dependencies`). This score maps to a model tier (`haiku`, `sonnet`, `opus`), ensuring complex tasks are assigned to more capable models from the start.
-   **Failure Escalation:** If a task fails, the `escalate_model` function automatically retries with the next-highest model tier (e.g., `haiku` -> `sonnet`). This prevents wasting resources on a cheap model that is not capable of solving the task while still attempting the cheapest option first.
-   **Key Files:**
    -   `spiral.config.sh`: High-level user configuration.
    -   `ralph/ralph.sh`: Contains the core implementation of the routing and escalation logic (`classify_model`, `escalate_model`).

### 2. Proactive & Reactive Decomposition

Spiral intelligently breaks down work to improve efficiency and success rate.

-   **Proactive Partitioning:** Before execution, `lib/partition_prd.py` can split the entire workload into parallelizable 'waves' based on a dependency graph. This allows multiple workers to tackle non-dependent tasks simultaneously, increasing throughput.
-   **Reactive Decomposition:** If a task is too complex and fails multiple retries, `lib/decompose_story.py` is triggered. It uses a high-capability LLM to analyze the failed task and its context, breaking it down into a new sequence of smaller, more manageable sub-tasks. This "divide and conquer" approach turns failure into progress.
-   **Key Files:**
    -   `lib/partition_prd.py`: Implements proactive parallel workload splitting.
    -   `lib/decompose_story.py`: Implements reactive failure analysis and task decomposition.

### 3. Token Efficiency Patterns

The system is designed to be mindful of the context window size.

-   **Prompt Engineering:** The master prompt in `ralph/CLAUDE.md` provides firm directives to the agent, including a "3-RETRY SKIP RULE" and a focus on "Quality > Speed". This constrains the agent's behavior and prevents wasteful exploration.
-   **Output Summarization:** The `ralph.sh` script makes use of a custom `rtk` command (a script or alias that should be in the environment) to filter and shorten the output of shell commands. This dramatically reduces the number of tokens fed back into the context window from tool use.
-   **Key Files:**
    -   `ralph/CLAUDE.md`: The agent's "constitution," defining core behaviors.
    -   `ralph/ralph.sh`: Uses `rtk` to summarize command outputs.

## Actionable Recommendations for a Setup Wizard

To make these powerful features accessible, a setup wizard or configuration UI should be implemented.

### "Simple Mode"

This mode should expose the single most impactful setting to the user, mapping clear outcomes to the underlying configuration in `spiral.config.sh`.

| User Option        | `SPIRAL_MODEL_ROUTING` Setting | Description                                                              |
| ------------------ | ------------------------------ | ------------------------------------------------------------------------ |
| **Balanced**       | `'auto'`                       | (Default) Automatically balances cost and quality. Uses cheap models first and escalates to powerful ones on failure. |
| **Maximum Quality**  | `'opus'`                       | Uses the most powerful model for all tasks. Highest quality, highest cost. |
| **Maximum Savings**  | `'haiku'`                      | Uses the cheapest model for all tasks. Lowest cost, may fail on complex tasks. |

### "Advanced Mode"

For expert users, the wizard could expose finer-grained controls, allowing them to tune the system's heuristics.

-   **Parallelism:** Allow the user to set `SPIRAL_MAX_PENDING` in `spiral.config.sh` to control the number of parallel workers.
-   **Complexity Scoring:** Expose the weighting factors within the `classify_model` function in `ralph.sh` to allow users to define what "complexity" means for their project.
-   **Decomposition Prompt:** Allow advanced users to view and even edit the `DECOMPOSE_PROMPT` used by `lib/decompose_story.py` to customize how failing tasks are broken down.
-   **Tool Routing:** Expose the model choices for specific tools (e.g., use `gpt-4-turbo` for research, `codex` for test synthesis).
