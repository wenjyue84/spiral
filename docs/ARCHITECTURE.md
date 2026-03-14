# SPIRAL Architecture

## Design Principles

1. **Story-first** — no code is written until the story backlog is clean, validated, and aligned with stated goals
2. **Modular phases** — each phase lives in its own file under `lib/phases/`; `spiral.sh` is a thin orchestrator
3. **Human in the loop up-front** — interactive clarification happens ONCE at startup, not mid-loop
4. **Monotonic phase ordering** — phases never run out of order; crash recovery resumes from last checkpoint
5. **Autonomous in the loop** — after startup, the loop runs unattended until all stories pass or the iteration limit is hit

---

## Phase Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  STARTUP  (one-time, before the loop)                           │
│                                                                 │
│  Phase 0: CLARIFY                                               │
│  ● Set / confirm focus area                                     │
│  ● Clarifying questions → refine goals & constraints            │
│  ● User elaborates initial stories → added to prd.json          │
│  ● Constitution check on elaborated stories                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  STORY PREPARATION LOOP  (repeats until backlog is stable)      │
│                                                                 │
│  Phase R: RESEARCH                                              │
│  ● Gemini web pre-fetch → Claude agent synthesises stories      │
│  ● Guided by prd.json goals[], constitution, and focus          │
│                          │                                      │
│  Phase T: TEST SYNTHESIS                                        │
│  ● Scan test-reports/ → convert failures to regression stories  │
│                          │                                      │
│  Phase S: STORY VALIDATE  (NEW)                                 │
│  ● Constitution check — reject out-of-scope stories             │
│  ● Goal alignment check — reject stories with no clear link     │
│  ● Quality check — reject vague/untestable acceptance criteria  │
│  ● Dedup check — reject 60%+ overlap with existing stories      │
│                          │                                      │
│  Phase M: MERGE                                                 │
│  ● Patch prd.json with validated candidates                     │
│  ● Overflow → _research_overflow.json (next iteration)          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  IMPLEMENTATION LOOP  (repeats until story passes or skipped)   │
│                                                                 │
│  Phase I: IMPLEMENT                                             │
│  ┌─ Sub-stage 1: DECOMPOSE ──────────────────────────────────┐  │
│  │  Split oversized stories into sub-stories before attempt  │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌─ Sub-stage 2: EXECUTE ────────────────────────────────────┐  │
│  │  Ralph workers (sequential or parallel via git worktrees) │  │
│  │  Each worker: pick story → implement → quality checks     │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌─ Sub-stage 3: RETRY ──────────────────────────────────────┐  │
│  │  failure → increment counter → escalate model             │  │
│  │  3 failures → decompose or skip                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌─ Sub-stage 4: COMMIT / REVERT ────────────────────────────┐  │
│  │  passes: true  → merge branch + quality gate assertion    │  │
│  │  passes: false → drop branch, revert, log reason          │  │
│  └───────────────────────────────────────────────────────────┘  │
│                          │                                      │
│  Phase V: VALIDATE (code)                                       │
│  ● Run $SPIRAL_VALIDATE_CMD (full or incremental)               │
│  ● Optional: Lighthouse audit, Chrome DevTools screenshot       │
│                          │                                      │
│  Phase C: CHECK DONE                                            │
│  ● All stories pass + tests green → EXIT 0                      │
│  ● Remaining stories → loop back to Phase R                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase Reference

### Phase 0 — CLARIFY (startup only)
| | |
|---|---|
| **File** | `lib/phases/phase_0_clarify.sh` |
| **When** | Once at launch, before the loop |
| **Skipped when** | `--gate proceed` or `--gate skip` (non-interactive mode) |
| **Replaces** | Old Phase G (Gate) interactive checkpoint |
| **New capability** | Clarifying questions + user story elaboration (not in old Gate) |
| **Output** | `.spiral/_clarify_output.json`, initial stories added to `prd.json` |

### Phase R — RESEARCH
| | |
|---|---|
| **File** | `lib/phases/phase_r_research.sh` |
| **Config** | `SPIRAL_RESEARCH_MODEL`, `SPIRAL_RESEARCH_TIMEOUT`, `SKIP_RESEARCH` |
| **Output** | `.spiral/_research_output.json` |

### Phase T — TEST SYNTHESIS
| | |
|---|---|
| **File** | `lib/phases/phase_t_test_synth.sh` |
| **Config** | `SPIRAL_TEST_SYNTH_TIMEOUT` |
| **Output** | `.spiral/_test_stories_output.json` |

### Phase S — STORY VALIDATE *(new)*
| | |
|---|---|
| **File** | `lib/phases/phase_s_story_validate.sh` |
| **Reads** | Phase R + T outputs, `prd.json`, constitution |
| **Output** | `.spiral/_validated_stories.json`, `.spiral/_story_rejected.json` |
| **Note** | Replaces human-review component of old Gate phase |

### Phase M — MERGE
| | |
|---|---|
| **File** | `lib/phases/phase_m_merge.sh` |
| **Reads** | `.spiral/_validated_stories.json` |
| **Config** | `SPIRAL_MAX_PENDING` |
| **Output** | `prd.json` (patched), `.spiral/_research_overflow.json` |

### Phase I — IMPLEMENT
| | |
|---|---|
| **File** | `lib/phases/phase_i_implement.sh` (orchestrator) |
| **Sub-stages** | `lib/impl/decompose.sh`, `lib/impl/retry.sh`, `lib/impl/commit_revert.sh` |
| **Config** | `RALPH_WORKERS`, `SPIRAL_IMPL_TIMEOUT`, `SPIRAL_STORY_BATCH_SIZE` |

#### Phase I Sub-stages

| Sub-stage | File | Purpose |
|-----------|------|---------|
| **Decompose** | `lib/impl/decompose.sh` | Split oversized stories into sub-stories via `lib/decompose_story.py` |
| **Execute** | _(ralph workers)_ | Each worker picks one story, implements, runs quality checks |
| **Retry** | `lib/impl/retry.sh` | Track attempt count per story; escalate model; skip at attempt 3 |
| **Commit/Revert** | `lib/impl/commit_revert.sh` | Merge worktree branch (pass) or drop it (fail) |

### Phase V — VALIDATE (code)
| | |
|---|---|
| **File** | `lib/phases/phase_v_validate.sh` |
| **Config** | `SPIRAL_VALIDATE_CMD`, `SPIRAL_VALIDATE_TIMEOUT`, `SPIRAL_INCREMENTAL_VALIDATE` |
| **Output** | `.spiral/report.json`, `.spiral/dashboard.html` |

### Phase C — CHECK DONE
| | |
|---|---|
| **File** | `lib/phases/phase_c_check_done.sh` |
| **Config** | `SPIRAL_ON_COMPLETE` |
| **Output** | Exit 0 (done) or loop to Phase R |

---

## Modular File Structure

```
spiral/
├── spiral.sh                        # Thin orchestrator — sources phase modules
├── lib/
│   ├── phases/                      # One file per phase
│   │   ├── phase_0_clarify.sh       # Phase 0: Startup clarification (NEW)
│   │   ├── phase_r_research.sh      # Phase R: Web research
│   │   ├── phase_t_test_synth.sh    # Phase T: Test failure synthesis
│   │   ├── phase_s_story_validate.sh# Phase S: Story validation (NEW)
│   │   ├── phase_m_merge.sh         # Phase M: Merge into prd.json
│   │   ├── phase_i_implement.sh     # Phase I: Implementation orchestrator
│   │   ├── phase_v_validate.sh      # Phase V: Code validation
│   │   └── phase_c_check_done.sh    # Phase C: Completion check
│   ├── impl/                        # Phase I sub-stage modules
│   │   ├── decompose.sh             # Story decomposition
│   │   ├── retry.sh                 # Retry + model escalation logic
│   │   └── commit_revert.sh         # Commit on pass, revert on fail
│   ├── merge_stories.py             # Phase M: dedup + prd.json patcher
│   ├── check_done.py                # Phase C: completion evaluator
│   ├── decompose_story.py           # Phase I/decompose: story splitter
│   ├── route_stories.py             # Phase I: model routing per story
│   ├── check_dag.py                 # Phase I: dependency cycle detector
│   ├── synthesize_tests.py          # Phase T: test failure → stories
│   └── ...                          # Other helpers
├── ralph/                           # Implementation engine
│   ├── ralph.sh                     # Inner loop (one story per invocation)
│   └── CLAUDE.md                    # Agent instructions
└── specs/                           # TLA+ formal models
    ├── SpiralPhases.tla             # Phase ordering invariants (needs update)
    └── SpiralWorkers.tla            # Parallel worker protocol
```

---

## Migration Status

The phase modules in `lib/phases/` and `lib/impl/` are **stubs** — the actual logic
still lives in `spiral.sh`. Migration stories have been added to `prd.json` to track
the code-split work per phase.

| Phase | Stub created | Code migrated |
|-------|-------------|---------------|
| Phase 0 (Clarify) | ✅ | ⬜ |
| Phase R | ✅ | ⬜ |
| Phase T | ✅ | ⬜ |
| Phase S (Story Validate) | ✅ NEW | ⬜ |
| Phase M | ✅ | ⬜ |
| Phase I (orchestrator) | ✅ | ⬜ |
| Phase I / decompose | ✅ | ⬜ |
| Phase I / retry | ✅ | ⬜ |
| Phase I / commit-revert | ✅ | ⬜ |
| Phase V | ✅ | ⬜ |
| Phase C | ✅ | ⬜ |

---

## Formal Verification

TLA+ specs in `specs/` model two critical properties:

- **`SpiralPhases.tla`** — phase ordering is monotonic; no phase runs before its predecessor; crash recovery resumes correctly. *Needs update to include Phase 0 and Phase S.*
- **`SpiralWorkers.tla`** — parallel workers never double-assign a story; merges are atomic; stories are never lost.

See [`specs/README.md`](../specs/README.md) for how to run the model checker.
