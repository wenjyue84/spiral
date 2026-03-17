# Vulture whitelist — intentional unused symbols.
# Each attribute access tells vulture the name is expected to exist.
# See: https://github.com/jendrikseipp/vulture#ignoring-unused-code
#
# Symbols here are required by interface contracts (SpanProcessor, BaseHTTPRequestHandler,
# emit_span public API) but not used in the concrete implementations.

from lib import consistency_check  # noqa: F401
from lib import otel_metrics  # noqa: F401
from lib import otel_spans  # noqa: F401
from lib import otel_worker_inject  # noqa: F401
from lib import privacy_scrubber  # noqa: F401

# consistency_check: _field_similarity(val1, val2, field_name) — field_name kept for API clarity
consistency_check.ConsistencyChecker._field_similarity.field_name  # type: ignore[attr-defined]

# otel_metrics: log_message(*fargs) required by BaseHTTPRequestHandler.log_message signature
otel_metrics.SilentHTTPRequestHandler.log_message.fargs  # type: ignore[attr-defined]

# otel_spans/otel_worker_inject: emit_span(is_root=False) — is_root is public API parameter
otel_spans.emit_span.is_root  # type: ignore[attr-defined]
otel_worker_inject.emit_span.is_root  # type: ignore[attr-defined]

# privacy_scrubber: SpanProcessor.on_start(parent_context) — interface contract
privacy_scrubber.PrivacyScrubberExporter.on_start.parent_context  # type: ignore[attr-defined]

# privacy_scrubber: SpanExporter.force_flush(timeout_millis) — interface contract
privacy_scrubber.PrivacyScrubberExporter.force_flush.timeout_millis  # type: ignore[attr-defined]

# generate_job_summary: generate_lint_summary(py_count=0) — accepted for API compat, body uses py_lint_ok
from lib import generate_job_summary  # noqa: F401
generate_job_summary.generate_lint_summary.py_count  # type: ignore[attr-defined]
