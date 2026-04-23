from __future__ import annotations

from backend.core.logging import REDACTED, StructlogRedactor, _walk, configure_logging


def test_redacts_value_when_key_is_sensitive() -> None:
    out = _walk({"password": "hunter2", "user": "alice"})
    assert out == {"password": REDACTED, "user": "alice"}


def test_redacts_nested_dict_sensitive_keys() -> None:
    out = _walk({"ctx": {"api_key": "sk-abc1234567890", "name": "ok"}})
    assert out == {"ctx": {"api_key": REDACTED, "name": "ok"}}


def test_redacts_openai_style_api_key_in_value() -> None:
    out = _walk({"error": "call failed with sk-5c6ca5d498e62360-ibf9jz-729e2cf0 rejected"})
    assert REDACTED in out["error"]
    assert "sk-5c6ca5d498e62360-ibf9jz-729e2cf0" not in out["error"]


def test_redacts_bearer_token_in_value() -> None:
    out = _walk({"auth_header": "Bearer ABCDEFGHIJ.klmnopqrst"})
    assert REDACTED in out["auth_header"]


def test_passes_through_normal_data_unchanged() -> None:
    out = _walk({"tweet_id": "12345", "ticker": "TSLA", "confidence": 0.87})
    assert out == {"tweet_id": "12345", "ticker": "TSLA", "confidence": 0.87}


def test_redacts_inside_list_of_dicts() -> None:
    out = _walk({"events": [{"token": "abc"}, {"ok": 1}]})
    assert out == {"events": [{"token": REDACTED}, {"ok": 1}]}


def test_structlog_processor_invokes_walk() -> None:
    redactor = StructlogRedactor()
    result = redactor(object(), "info", {"api_key": "sk-abcdefghijklmnopqr"})
    assert result["api_key"] == REDACTED


def test_configure_logging_is_idempotent() -> None:
    configure_logging()
    configure_logging(level="DEBUG", json_logs=False)
    # Reconfiguring must not raise; re-enable JSON for downstream tests.
    configure_logging()


def test_key_detection_is_case_insensitive() -> None:
    out = _walk({"API_KEY": "secret", "Password": "p"})
    assert out == {"API_KEY": REDACTED, "Password": REDACTED}
