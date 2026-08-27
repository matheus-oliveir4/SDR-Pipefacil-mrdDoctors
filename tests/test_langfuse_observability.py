from langfuse.types import MaskOtelSpansParams, OtelSpanData, OtelSpanIdentifier

from app.observability.langfuse import _mask_otel_spans, _mask_string


def test_mask_string_redacts_sensitive_values() -> None:
    value = (
        "Contato joao@example.com telefone +55 (11) 91234-5678 "
        "token Bearer abc123 sk-lf-secret pk-lf-public sk-openai"
    )

    masked = _mask_string(value)

    assert "[EMAIL_REDACTED]" in masked
    assert "[PHONE_REDACTED]" in masked
    assert "Bearer [TOKEN_REDACTED]" in masked
    assert "[LANGFUSE_KEY_REDACTED]" in masked
    assert "[OPENAI_KEY_REDACTED]" in masked


def test_mask_string_keeps_dates_and_session_ids_readable() -> None:
    value = "codex-smoke-2026-07-17 verified_on=2026-07-17"

    assert _mask_string(value) == value


def test_mask_string_redacts_multimodal_base64_fields() -> None:
    value = (
        '{"type":"file","base64":"very-sensitive-base64","mime_type":"application/pdf"} '
        "{'type':'file','file_data':'data:application/pdf;base64,secret-pdf'}"
    )

    masked = _mask_string(value)

    assert "very-sensitive-base64" not in masked
    assert "secret-pdf" not in masked
    assert '"base64":"[BASE64_REDACTED]"' in masked
    assert "'file_data':'[BASE64_REDACTED]'" in masked


def test_mask_string_redacts_data_url_base64() -> None:
    value = "url=data:application/pdf;base64,AAAAIGZ0eXBtcDQyAAAAAGlz"

    masked = _mask_string(value)

    assert "AAAAIGZ0eXBtcDQyAAAAAGlz" not in masked
    assert masked == "url=data:application/pdf;base64,[BASE64_REDACTED]"


def _mask_params() -> tuple[MaskOtelSpansParams, OtelSpanIdentifier]:
    identifier = OtelSpanIdentifier(trace_id="trace-1", span_id="span-1")
    params = MaskOtelSpansParams(
        spans={
            identifier: OtelSpanData(
                trace_id="trace-1",
                span_id="span-1",
                parent_span_id=None,
                name="agent",
                instrumentation_scope_name="test",
                instrumentation_scope_version="1",
                attributes={
                    "user.id": "Pessoa Exemplo | +55 (11) 91234-5678 | contact:123",
                    "session.id": "lead-123",
                    "metadata": "joao@example.com Bearer secret-token",
                },
                resource_attributes={},
            )
        }
    )
    return params, identifier


def test_mask_otel_spans_masks_user_id_in_safe_mode() -> None:
    params, identifier = _mask_params()

    result = _mask_otel_spans(params=params)

    assert result is not None
    replacements = result.span_patches[identifier].set_attributes
    assert replacements["user.id"] == "Pessoa Exemplo | [PHONE_REDACTED] | contact:123"
    assert replacements["metadata"] == "[EMAIL_REDACTED] Bearer [TOKEN_REDACTED]"
    assert "session.id" not in replacements


def test_mask_otel_spans_preserves_user_id_only_in_explicit_pii_mode() -> None:
    params, identifier = _mask_params()

    result = _mask_otel_spans(params=params, preserve_user_id=True)

    assert result is not None
    replacements = result.span_patches[identifier].set_attributes
    assert "user.id" not in replacements
    assert replacements["metadata"] == "[EMAIL_REDACTED] Bearer [TOKEN_REDACTED]"
