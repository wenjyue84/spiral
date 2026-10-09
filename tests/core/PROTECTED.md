# tests/core — protected seed tests

Seed tests -- human-maintained, Ralph-protected.
These tests verify SPIRAL core infrastructure integrity.
They MUST NOT be modified by Ralph workers (enforced by protect-spiral-files.sh).

Note: this directory intentionally has no __init__.py. With one, pytest imports it as a top-level
package named `core`, shadowing lib/core and breaking `import core.spiral_io` in the full suite.
