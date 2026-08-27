from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TextIO

from app.core.config import Settings

MANAGED_HANDLER_ATTR = "_sdr_pipefacil_managed_handler"
SUPPORTED_LOG_FORMATS = {"json", "text"}

EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d(). -]{8,}\d(?!\w)")
SENSITIVE_FIELD_HINTS = (
    "authorization",
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "private_key",
    "public_key",
)
STANDARD_RECORD_ATTRIBUTES = set(logging.makeLogRecord({}).__dict__) | {
    "asctime",
    "message",
}
TEXT_FIELD_ALIASES = {
    "agent_status": "agent",
    "app_env": "env",
    "app_version": "version",
    "content_length": "content_length",
    "content_encoding": "encoding",
    "content_type": "content_type",
    "delivery_status": "delivery",
    "duration_ms": "ms",
    "error_code": "error",
    "event_type": "event",
    "external_message_id": "external",
    "http_method": "method",
    "http_path": "path",
    "message_id": "msg",
    "message_type": "type",
    "has_media": "media",
    "media_duration": "duration",
    "media_id": "media_id",
    "media_keys": "media_keys",
    "media_mime_type": "mime",
    "media_size": "size",
    "media_type": "media_type",
    "message_body_length": "body_length",
    "pipeline_run_id": "run",
    "request_header_names": "headers",
    "request_id": "request",
    "specialist_confidence": "confidence",
    "specialist_error_code": "specialist_error",
    "specialist_name": "specialist",
    "specialist_status": "specialist_status",
    "status_code": "status",
    "thread_id": "thread",
    "transcription_length": "transcription_length",
    "user_agent": "ua",
    "user_id": "user",
    "validation_error_count": "validation_errors",
    "validation_error_locations": "locations",
    "validation_error_types": "types",
}
TEXT_FIELD_ORDER = (
    "thread_id",
    "user_id",
    "message_type",
    "has_media",
    "media_type",
    "media_mime_type",
    "media_size",
    "media_duration",
    "transcription_length",
    "intent",
    "specialist_name",
    "specialist_status",
    "specialist_confidence",
    "specialist_error_code",
    "agent_status",
    "delivery_status",
    "status_code",
    "error_code",
    "request_id",
    "message_id",
    "pipeline_run_id",
    "external_message_id",
    "event_type",
    "media_id",
    "media_keys",
    "message_body_length",
    "http_method",
    "http_path",
    "duration_ms",
    "content_type",
    "content_encoding",
    "content_length",
    "user_agent",
    "request_header_names",
    "validation_error_count",
    "validation_error_locations",
    "validation_error_types",
    "app_env",
    "app_version",
    "checkpointer",
)
TEXT_VALUE_MAX_LENGTH = 48
TEXT_VALUE_HEAD_LENGTH = 24
TEXT_VALUE_TAIL_LENGTH = 12
PLAIN_TEXT_VALUE_PATTERN = re.compile(r"^[^\s\"'=]+$")
TEXT_LEVEL_NAMES = {
    logging.DEBUG: "DBG",
    logging.INFO: "INF",
    logging.WARNING: "WRN",
    logging.ERROR: "ERR",
    logging.CRITICAL: "CRT",
}
TEXT_MESSAGE_ALIASES = {
    "Application startup started.": "startup.started",
    "Application startup completed.": "startup.completed",
    "Application shutdown completed.": "shutdown.completed",
}
TEXT_EVENT_PREFIXES = (
    ("pipefacil.webhook.", "webhook"),
    ("pipefacil.inbound.", "inbound"),
    ("pipefacil.outbound.", "outbound"),
    ("agent.run.", "agent"),
    ("specialist.run.", "specialist"),
)
ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_DIM = "\033[2m"
ANSI_CYAN = "\033[36m"
TEXT_LEVEL_COLORS = {
    logging.DEBUG: ANSI_DIM,
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[1;31m",
}
TEXT_SOURCE_COLORS = {
    "main": ANSI_CYAN,
    "webhook": ANSI_CYAN,
    "inbound": "\033[34m",
    "agent": "\033[35m",
    "specialist": "\033[35m",
    "outbound": "\033[32m",
}


@dataclass(frozen=True)
class RawLogValue:
    value: Any


def raw_log_value(value: Any) -> RawLogValue:
    return RawLogValue(value=value)


def _mask_string(value: str) -> str:
    masked = EMAIL_PATTERN.sub("[EMAIL_REDACTED]", value)

    def replace_phone(match: re.Match[str]) -> str:
        candidate = match.group(0)
        digits = re.sub(r"\D", "", candidate)
        if 10 <= len(digits) <= 15:
            return "[PHONE_REDACTED]"
        return candidate

    return PHONE_PATTERN.sub(replace_phone, masked)


def _is_sensitive_field(key: str) -> bool:
    normalized_key = key.lower()
    return any(hint in normalized_key for hint in SENSITIVE_FIELD_HINTS)


def _json_safe(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if isinstance(value, RawLogValue):
        return _raw_json_safe(value.value, depth=depth)

    if _is_sensitive_field(key):
        return "[REDACTED]"

    if depth > 3:
        return str(value)

    if isinstance(value, str):
        return _mask_string(value)
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, dict):
        return {
            str(item_key): _json_safe(item_value, key=str(item_key), depth=depth + 1)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list | tuple | set):
        return [_json_safe(item, depth=depth + 1) for item in value]

    return str(value)


def _raw_json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return str(value)

    if isinstance(value, str | bool | int | float) or value is None:
        return value
    if isinstance(value, dict):
        return {
            str(item_key): _raw_json_safe(item_value, depth=depth + 1)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list | tuple | set):
        return [_raw_json_safe(item, depth=depth + 1) for item in value]

    return str(value)


def _record_extra(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: _json_safe(value, key=key)
        for key, value in record.__dict__.items()
        if key not in STANDARD_RECORD_ATTRIBUTES and not key.startswith("_")
    }


def _timestamp(record: logging.LogRecord) -> str:
    return datetime.fromtimestamp(record.created, tz=UTC).isoformat().replace("+00:00", "Z")


def _text_timestamp(record: logging.LogRecord) -> str:
    return datetime.fromtimestamp(record.created, tz=UTC).strftime("%H:%M:%S.%f")[:12] + "Z"


def _short_logger_name(logger_name: str) -> str:
    if logger_name == "app":
        return "app"
    if logger_name.startswith("app."):
        return logger_name.removeprefix("app.")
    return logger_name


def _text_level_name(levelno: int) -> str:
    return TEXT_LEVEL_NAMES.get(levelno, logging.getLevelName(levelno)[:3])


def _text_source_and_event(logger_name: str, message: str) -> tuple[str, str]:
    aliased_message = TEXT_MESSAGE_ALIASES.get(message, message)
    for prefix, source in TEXT_EVENT_PREFIXES:
        if aliased_message.startswith(prefix):
            return source, aliased_message.removeprefix(prefix)

    return _short_logger_name(logger_name), aliased_message


def _style_text(value: str, ansi_code: str) -> str:
    return f"{ansi_code}{value}{ANSI_RESET}"


def _shorten_text_string(value: str) -> str:
    if len(value) <= TEXT_VALUE_MAX_LENGTH:
        return value
    return f"{value[:TEXT_VALUE_HEAD_LENGTH]}...{value[-TEXT_VALUE_TAIL_LENGTH:]}"


def _format_text_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        shortened_value = _shorten_text_string(value)
        if PLAIN_TEXT_VALUE_PATTERN.fullmatch(shortened_value):
            return shortened_value
        return json.dumps(shortened_value, ensure_ascii=False)
    if isinstance(value, list | tuple | set):
        sequence_items: list[str] = []
        for item in value:
            formatted_item = _format_text_sequence_item(item)
            if formatted_item is None:
                break
            sequence_items.append(formatted_item)
        else:
            return _shorten_text_string(f"[{','.join(sequence_items)}]")

    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(_shorten_text_string(serialized), ensure_ascii=False)


def _format_text_sequence_item(value: Any) -> str | None:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        shortened_value = _shorten_text_string(value)
        if PLAIN_TEXT_VALUE_PATTERN.fullmatch(shortened_value):
            return shortened_value
        return json.dumps(shortened_value, ensure_ascii=False)

    return None


def _text_record_extra(record: logging.LogRecord) -> dict[str, Any]:
    payload = _record_extra(record)
    message = record.getMessage()

    if payload.get("pipeline_step") == message:
        payload.pop("pipeline_step")
    if "external_message_id" in payload and payload.get("external_message_id") == payload.get(
        "pipeline_run_id"
    ):
        payload.pop("external_message_id")
    if payload.get("event_type") == "message.received":
        payload.pop("event_type")
    if "thread_id" in payload:
        payload.pop("message_id", None)
    if payload.get("user_id") == "[PHONE_REDACTED]":
        payload.pop("user_id")

    return {key: value for key, value in payload.items() if value is not None}


def _format_text_details(payload: dict[str, Any]) -> str:
    ordered_keys = [key for key in TEXT_FIELD_ORDER if key in payload]
    ordered_keys.extend(sorted(key for key in payload if key not in TEXT_FIELD_ORDER))
    details: list[str] = []

    for key in ordered_keys:
        formatted_value = _format_text_value(payload[key])
        if formatted_value is None:
            continue
        display_key = TEXT_FIELD_ALIASES.get(key, key)
        display_key = _style_text(display_key, ANSI_DIM)
        details.append(f"{display_key}={formatted_value}")

    return " ".join(details)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(_record_extra(record))

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        payload = _text_record_extra(record)
        details = _format_text_details(payload)
        source, event = _text_source_and_event(record.name, message)
        timestamp = _style_text(_text_timestamp(record), ANSI_DIM)
        level = _style_text(
            f"{_text_level_name(record.levelno):<3}",
            TEXT_LEVEL_COLORS.get(record.levelno, ANSI_DIM),
        )
        source_column = _style_text(
            f"{source[:9]:<9}",
            TEXT_SOURCE_COLORS.get(source, ANSI_CYAN),
        )
        event = _style_text(event, ANSI_BOLD)
        base = f"{timestamp} {level} {source_column} {event}"
        if details:
            base = f"{base} | {details}"
        if record.exc_info:
            base = f"{base}\n{self.formatException(record.exc_info)}"
        if record.stack_info:
            base = f"{base}\n{self.formatStack(record.stack_info)}"

        return base


def _resolve_log_level(value: str | None) -> int:
    normalized_value = (value or "INFO").strip().upper()
    resolved_level = getattr(logging, normalized_value, logging.INFO)
    if isinstance(resolved_level, int):
        return resolved_level

    return logging.INFO


def _resolve_log_format(settings: Settings) -> str:
    configured_format = (settings.log_format or "").strip().lower()
    if configured_format in SUPPORTED_LOG_FORMATS:
        return configured_format

    if settings.app_env.strip().lower() == "production":
        return "json"

    return "text"


def _build_formatter(settings: Settings) -> logging.Formatter:
    resolved_format = _resolve_log_format(settings)
    if resolved_format == "json":
        return JsonFormatter()

    return TextFormatter()


def configure_logging(settings: Settings, *, stream: TextIO | None = None) -> None:
    logger = logging.getLogger("app")
    level = _resolve_log_level(settings.log_level)

    for handler in list(logger.handlers):
        if getattr(handler, MANAGED_HANDLER_ATTR, False):
            logger.removeHandler(handler)
            handler.close()

    resolved_stream = stream or sys.stderr
    handler = logging.StreamHandler(resolved_stream)
    handler.setLevel(level)
    handler.setFormatter(_build_formatter(settings))
    setattr(handler, MANAGED_HANDLER_ATTR, True)

    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False

    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(level)
