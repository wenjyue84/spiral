# SPIRAL -- TLA+ Formal Specifications

Formal models for verifying SPIRAL's phase transitions and parallel worker protocol.

## Specifications

| File | What it models | Key properties | Status |
|------|---------------|----------------|--------|
| `SpiralPhases.tla` | Phase ordering within iterations | Monotonicity, crash recovery, no backward transitions | ⚠️ Needs update for Phase 0 (Clarify) and Phase S (Story Validate) |
| `SpiralWorkers.tla` | Parallel worker protocol | Partition disjointness, merge correctness, no story loss | ✅ Current |

## Phase Numeric Order (updated)

The current phase sequence and numeric assignments:

| Phase | Label | Number | Notes |
|-------|-------|--------|-------|
| Clarify | 0 | 0 | One-time startup; not part of the loop |
| Research | R | 1 | |
| Test Synthesis | T | 2 | |
| Story Validate | S | 3 | NEW — replaces human Gate review |
| Merge | M | 4 | |
| Implement | I | 5 | |
| Validate | V | 6 | |
| Check Done | C | 7 | |

`SpiralPhases.tla` must be updated to:
- Add Phase 0 (Clarify) as a pre-loop setup state
- Add Phase S (Story Validate) between T and M
- Remove Phase G (Gate) from the loop sequence (it is now Phase 0)

## Requirements

- [TLA+ Toolbox](https://lamport.azurewebsites.net/tla/toolbox.html) or
- [TLC Model Checker CLI](https://github.com/tlaplus/tlaplus/releases)

## Running the Model Checker

### Using TLA+ Toolbox (GUI)
1. Open `.tla` file in TLA+ Toolbox
2. Create new model -> use the `CONSTANTS` and `SPECIFICATION` from the `.cfg` file
3. Add invariants listed in each spec
4. Run TLC

### Using TLC CLI
```bash
# Phase transitions (fast -- small state space)
java -jar tla2tools.jar -config SpiralPhases.cfg SpiralPhases.tla

# Worker protocol (medium -- scales with NumWorkers x NumStories)
java -jar tla2tools.jar -config SpiralWorkers.cfg SpiralWorkers.tla
```

## Model Parameters

### SpiralPhases
- `MaxIterations` -- number of iterations to check (default: 3, increase for deeper checks)

### SpiralWorkers
- `NumWorkers` -- number of parallel workers (default: 3)
- `NumStories` -- number of stories in the PRD (default: 4)
- Reduce if state space is too large; increase for more coverage
