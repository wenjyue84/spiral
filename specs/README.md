# SPIRAL -- TLA+ Formal Specifications

Formal models for verifying SPIRAL's phase transitions and parallel worker protocol.

## Specifications

| File | What it models | Key properties |
|------|---------------|----------------|
| `SpiralPhases.tla` | Phase ordering within iterations | Monotonicity, crash recovery, no backward transitions |
| `SpiralWorkers.tla` | Parallel worker protocol | Partition disjointness, merge correctness, no story loss |

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
