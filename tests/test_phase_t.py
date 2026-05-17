"""tests/test_phase_t.py — Tests for Phase T test failure classifier (US-1337).

Tests classify_test_failure() against all 5 error categories with
realistic snippet strings, verifying both type and hint fields.
"""

from lib.test_classifier import classify_test_failure


def test_classify_import_error() -> None:
    snippet = "ImportError: cannot import name 'foo' from 'bar'"
    result = classify_test_failure(snippet)
    assert result["type"] == "import_error"
    assert "import" in result["hint"].lower()


def test_classify_module_not_found() -> None:
    snippet = "ModuleNotFoundError: No module named 'numpy'"
    result = classify_test_failure(snippet)
    assert result["type"] == "import_error"
    assert "numpy" in result["hint"]


def test_classify_assertion_failure() -> None:
    snippet = "AssertionError: assert 42 == 0"
    result = classify_test_failure(snippet)
    assert result["type"] == "assertion_failure"
    assert "hint" in result


def test_classify_syntax_error() -> None:
    snippet = "SyntaxError: invalid syntax"
    result = classify_test_failure(snippet)
    assert result["type"] == "syntax_error"
    assert "syntax" in result["hint"].lower()


def test_classify_timeout_error() -> None:
    snippet = "TimeoutExpired: Command timed out after 30 seconds"
    result = classify_test_failure(snippet)
    assert result["type"] == "timeout"
    assert "timeout" in result["hint"].lower()


def test_classify_environment_error() -> None:
    snippet = "FileNotFoundError: [Errno 2] No such file or directory: '/tmp/missing'"
    result = classify_test_failure(snippet)
    assert result["type"] == "environment_error"
    assert "hint" in result


def test_classify_returns_dict_with_type_and_hint() -> None:
    result = classify_test_failure("AssertionError: something wrong")
    assert isinstance(result, dict)
    assert "type" in result
    assert "hint" in result
    assert isinstance(result["type"], str)
    assert isinstance(result["hint"], str)
