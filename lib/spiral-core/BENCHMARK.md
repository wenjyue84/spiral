# spiral-core Benchmark Report

Measured on Windows 11, MSYS2 bash, AMD Ryzen (5 warm runs after 1 cold run).
Input: `templates/prd.example.json` (4 stories), empty research/test story files.

| Script | Python warm (ms) | Rust warm (ms) | Speedup |
|---|---|---|---|
| validate (schema + dag) | ~165 | ~90 | **1.8×** |
| merge_stories | ~365 | ~113 | **3.2×** |
| check_done | ~224 | ~105 | **2.1×** |
| synthesize_tests | ~200* | ~100* | **2.0×** |
| partition_prd | ~200* | ~100* | **2.0×** |
| **Total per iteration** | **~1150** | **~508** | **2.3×** |

*synthesize and partition estimated from similar cold/warm profile.

## Cold-start advantage (first invocation)

Python interpreter startup on Windows is expensive for short-lived scripts.

| Script | Python cold (ms) | Rust cold (ms) | Cold speedup |
|---|---|---|---|
| validate | 546 | 184 | 3.0× |
| merge_stories | 823 | 385 | 2.1× |
| check_done | 672 | 311 | 2.2× |

The cold-start gap is especially relevant when Spiral is run in CI or fresh shells
where Python `.pyc` bytecode cache is absent.

## Per-iteration savings

A full Spiral iteration calls these scripts:
- Phase T: 1× synthesize_tests
- Phase M: 1× merge_stories (includes 1 validate internally)
- Phase C: 1× check_done (includes 1 validate internally)
- Parallel only: 1× partition + 1× merge_workers

Conservative estimate (warm, 5 scripts): **~640ms saved per iteration**.

For a 100-iteration run: **~64 seconds** saved on the CPU-bound path
(LLM call time unchanged — this is purely startup + JSON overhead).

## Notes

- `serde_json` with `preserve_order` keeps exact JSON key order from source
- Atomic writes (`.tmp` → rename) match Python's `shutil.move` pattern
- `SPIRAL_CORE_BIN` env respects `SPIRAL_STORY_PREFIX` env var for ID assignment
- Python fallback is always available; `SPIRAL_CORE_BIN` stays empty if binary not found
