# Vulture whitelist — intentional unused symbols.
# Each attribute access tells vulture the name is expected to exist.
# See: https://github.com/jendrikseipp/vulture#ignoring-unused-code

from lib import otel_spans  # noqa: F401

# is_root is part of the public API (callers pass is_root=True/False)
# but the function body does not yet branch on it.
otel_spans.emit_span.is_root  # type: ignore[attr-defined]
