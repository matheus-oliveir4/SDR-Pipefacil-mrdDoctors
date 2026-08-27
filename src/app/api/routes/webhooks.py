from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import time
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from starlette.datastructures import Headers

from app.api.dependencies import (
    get_graph,
    get_pipefacil_message_idempotency_store,
    get_settings,
)
from app.api.schemas.chat import ChatResponse
from app.api.schemas.webhooks import MessageReceivedEventRequest
from app.application import (
    MessageIdempotencyStore,
    PipefacilInboundMessageError,
    build_pipefacil_message_received_log_context,
    build_pipefacil_message_received_raw_log_payload,
    handle_pipefacil_message_received,
    validate_pipefacil_message_received,
)
from app.core.config import Settings
from app.core.logging import raw_log_value

webhooks_router = APIRouter()
GraphDep = Annotated[Any, Depends(get_graph)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
IdempotencyStoreDep = Annotated[
    MessageIdempotencyStore,
    Depends(get_pipefacil_message_idempotency_store),
]
LOGGER = logging.getLogger(__name__)
HEX_PATTERN = re.compile(r"^[0-9a-fA-F]+$")
SIGNATURE_HEADER_CANDIDATES = (
    "X-Pipefacil-Signature",
    "X-Pipefacil-Signature-256",
    "X-Webhook-Signature",
    "Webhook-Signature",
    "X-Hub-Signature-256",
    "X-Signature-SHA256",
    "X-Signature",
    "X-Hook-Signature",
)
SHARED_SECRET_HEADER_CANDIDATES = (
    "X-Pipefacil-Webhook-Secret",
    "X-Pipefacil-Secret",
    "X-Webhook-Secret",
    "Webhook-Secret",
    "X-Hook-Secret",
    "Authorization",
)
SIGNATURE_VALUE_PREFIXES = (
    "sha256=",
    "hmac-sha256=",
    "sha256:",
    "v1=",
)
SIGNATURE_VALUE_KEYS = {
    "sha256",
    "sha-256",
    "hmac-sha256",
    "hmac_sha256",
    "signature",
    "sig",
    "v1",
}
TIMESTAMP_HEADER_CANDIDATES = (
    "X-Pipefacil-Timestamp",
    "X-Webhook-Timestamp",
    "Webhook-Timestamp",
    "X-Signature-Timestamp",
    "X-Request-Timestamp",
)
EVENT_HEADER_CANDIDATES = (
    "X-Pipefacil-Event",
    "X-Webhook-Event",
    "Webhook-Event",
    "X-Event-Type",
)
RAW_REQUEST_BODY_SCOPE_KEY = "sdr_pipefacil_raw_request_body"


async def verify_pipefacil_webhook_signature(
    request: Request,
    settings: SettingsDep,
) -> None:
    if not settings.pipefacil_webhook_signature_enabled:
        return

    secret = (settings.pipefacil_webhook_signature_secret or "").strip()
    if not secret:
        return

    configured_header_name = settings.pipefacil_webhook_signature_header
    header_name, received_signature = _extract_webhook_auth_header(
        headers=request.headers,
        configured_header_name=configured_header_name,
    )

    body = await request.body()
    signature_bodies = _signature_body_candidates(request=request, body=body)
    timestamp_values = _signature_timestamp_values(request.headers)
    event_values = _signature_event_values(request.headers)
    if received_signature and _signature_matches(
        bodies=signature_bodies,
        secret=secret,
        received_signature=received_signature,
        timestamp_values=timestamp_values,
        event_values=event_values,
    ):
        return

    fallback_header_name = _find_matching_webhook_auth_header(
        headers=request.headers,
        bodies=signature_bodies,
        secret=secret,
        timestamp_values=timestamp_values,
        event_values=event_values,
        excluded_header_name=header_name,
    )
    if fallback_header_name:
        return

    if not received_signature:
        _reject_invalid_signature(
            reason="signature_missing",
            header_name=configured_header_name,
            request_headers=request.headers,
        )

    if _signature_debug_enabled(settings):
        _log_signature_diagnostics(
            secret=secret,
            received_signature=received_signature,
            bodies=signature_bodies,
            timestamp_values=timestamp_values,
            event_values=event_values,
            request_headers=request.headers,
        )

    _reject_invalid_signature(
        reason="signature_mismatch",
        header_name=header_name,
        request_headers=request.headers,
        received_signature=received_signature,
    )


def _find_matching_webhook_auth_header(
    *,
    headers: Headers,
    bodies: tuple[bytes, ...],
    secret: str,
    timestamp_values: tuple[str, ...],
    event_values: tuple[str, ...],
    excluded_header_name: str | None,
) -> str | None:
    excluded_header_key = excluded_header_name.lower() if excluded_header_name else None
    for header_name, header_value in headers.items():
        if excluded_header_key and header_name.lower() == excluded_header_key:
            continue
        if _signature_matches(
            bodies=bodies,
            secret=secret,
            received_signature=header_value,
            timestamp_values=timestamp_values,
            event_values=event_values,
        ):
            return header_name

    return None


def _extract_webhook_auth_header(
    *,
    headers: Headers,
    configured_header_name: str,
) -> tuple[str, str] | tuple[None, None]:
    for header_name in _ordered_header_candidates(
        configured_header_name,
        SIGNATURE_HEADER_CANDIDATES,
        SHARED_SECRET_HEADER_CANDIDATES,
    ):
        header_value = headers.get(header_name)
        if header_value:
            return header_name, header_value

    return None, None


def _ordered_header_candidates(
    configured_header_name: str,
    *candidate_groups: tuple[str, ...],
) -> tuple[str, ...]:
    candidates: list[str] = []
    for header_name in (
        configured_header_name,
        *[name for group in candidate_groups for name in group],
    ):
        normalized_header_name = header_name.strip()
        if normalized_header_name and normalized_header_name.lower() not in {
            candidate.lower() for candidate in candidates
        }:
            candidates.append(normalized_header_name)

    return tuple(candidates)


def _signature_timestamp_values(headers: Headers) -> tuple[str, ...]:
    values: list[str] = []
    for header_name in TIMESTAMP_HEADER_CANDIDATES:
        header_value = headers.get(header_name)
        if header_value:
            values.append(header_value.strip())

    return tuple(values)


def _signature_event_values(headers: Headers) -> tuple[str, ...]:
    values: list[str] = []
    for header_name in EVENT_HEADER_CANDIDATES:
        header_value = headers.get(header_name)
        if header_value:
            values.append(header_value.strip())

    return tuple(values)


def _signature_body_candidates(*, request: Request, body: bytes) -> tuple[bytes, ...]:
    candidates = [body]
    raw_body = request.scope.get(RAW_REQUEST_BODY_SCOPE_KEY)
    if isinstance(raw_body, bytes) and raw_body != body:
        candidates.insert(0, raw_body)

    return tuple(candidates)


def _reject_invalid_signature(
    *,
    reason: str,
    header_name: str | None,
    request_headers: Headers,
    received_signature: str | None = None,
) -> None:
    extra = {
        "pipeline_step": "pipefacil.webhook.signature_rejected",
        "error_code": "pipefacil_webhook_signature_invalid",
        "reason": reason,
        "signature_header": header_name,
        "request_header_names": sorted(request_headers.keys()),
        "status_code": status.HTTP_401_UNAUTHORIZED,
    }
    if received_signature is not None:
        extra.update(_signature_log_context(received_signature))

    LOGGER.warning(
        "pipefacil.webhook.signature_rejected",
        extra=extra,
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid webhook signature.",
    )


def _signature_log_context(received_signature: str) -> dict[str, object]:
    normalized_signature = received_signature.strip()
    lower_signature = normalized_signature.lower()

    return {
        "signature_value_length": len(normalized_signature),
        "signature_value_has_sha256_prefix": lower_signature.startswith(("sha256=", "sha256:")),
        "signature_value_has_bearer_prefix": lower_signature.startswith("bearer "),
        "signature_value_part_count": len(
            [part for part in re.split(r"[,;]", normalized_signature) if part.strip()]
        ),
    }


def _signature_debug_enabled(settings: Settings) -> bool:
    return settings.app_env.strip().lower() != "production"


def _log_signature_diagnostics(
    *,
    secret: str,
    received_signature: str,
    bodies: tuple[bytes, ...],
    timestamp_values: tuple[str, ...],
    event_values: tuple[str, ...],
    request_headers: Headers,
) -> None:
    normalized_received_candidates = sorted(_signature_candidates(received_signature))
    received_preview = normalized_received_candidates[0] if normalized_received_candidates else ""
    body_lengths = [len(body) for body in bodies]
    body_hashes = [hashlib.sha256(body).hexdigest()[:16] for body in bodies]

    LOGGER.info(
        "pipefacil.webhook.signature_debug",
        extra={
            "pipeline_step": "pipefacil.webhook.signature_debug",
            "signature_secret_length": len(secret),
            "signature_secret_is_hex": bool(HEX_PATTERN.fullmatch(secret)),
            "signature_received_prefix": received_preview[:16],
            "signature_received_suffix": received_preview[-16:] if received_preview else "",
            "signature_body_candidate_count": len(bodies),
            "signature_body_lengths": body_lengths,
            "signature_body_sha256_prefixes": body_hashes,
            "signature_timestamp_values": list(timestamp_values),
            "signature_event_values": list(event_values),
            "request_header_names": sorted(request_headers.keys()),
        },
    )


def _signature_matches(
    *,
    body: bytes | None = None,
    bodies: tuple[bytes, ...] | None = None,
    secret: str,
    received_signature: str,
    timestamp_values: tuple[str, ...] = (),
    event_values: tuple[str, ...] = (),
) -> bool:
    if _shared_secret_matches(secret=secret, received_signature=received_signature):
        return True

    received_candidates = _signature_candidates(received_signature)
    body_candidates = bodies or ((body,) if body is not None else ())
    expected_candidates = {
        expected
        for body_candidate in body_candidates
        for expected in _expected_signatures(
            body=body_candidate,
            secret=secret,
            timestamp_values=timestamp_values,
            event_values=event_values,
        )
    }

    return any(
        hmac.compare_digest(received, expected)
        for received in received_candidates
        for expected in expected_candidates
    )


def _signature_candidates(value: str) -> set[str]:
    candidates = {_normalize_signature_candidate(value)}

    for part in re.split(r"[,;]", value):
        normalized_part = part.strip()
        lower_part = normalized_part.lower()
        for prefix in SIGNATURE_VALUE_PREFIXES:
            if lower_part.startswith(prefix):
                candidates.add(_normalize_signature_candidate(normalized_part[len(prefix) :]))

        if "=" in normalized_part:
            key, candidate = normalized_part.split("=", 1)
            if key.strip().lower() in SIGNATURE_VALUE_KEYS:
                candidates.add(_normalize_signature_candidate(candidate))

        parts = normalized_part.split()
        if len(parts) == 2 and parts[0].strip().lower() in SIGNATURE_VALUE_KEYS:
            candidates.add(_normalize_signature_candidate(parts[1]))

    return {candidate for candidate in candidates if candidate}


def _normalize_signature_candidate(candidate: str) -> str:
    normalized_candidate = candidate.strip().strip('"').strip("'")
    if HEX_PATTERN.fullmatch(normalized_candidate):
        return normalized_candidate.lower()

    return normalized_candidate


def _shared_secret_matches(*, secret: str, received_signature: str) -> bool:
    return any(
        hmac.compare_digest(candidate, secret)
        for candidate in _shared_secret_candidates(received_signature)
    )


def _shared_secret_candidates(value: str) -> set[str]:
    normalized_value = value.strip().strip('"').strip("'")
    lower_value = normalized_value.lower()
    candidates = {normalized_value}

    for prefix in ("bearer ", "token "):
        if lower_value.startswith(prefix):
            candidates.add(normalized_value[len(prefix) :].strip())

    return {candidate for candidate in candidates if candidate}


def _expected_signatures(
    *,
    body: bytes,
    secret: str,
    timestamp_values: tuple[str, ...] = (),
    event_values: tuple[str, ...] = (),
) -> set[str]:
    signatures: set[str] = set()

    for secret_bytes in _secret_byte_variants(secret):
        for payload_base in _signature_payload_bases(body):
            for signed_payload in _signed_payload_variants(
                payload_base,
                timestamp_values=timestamp_values,
                event_values=event_values,
            ):
                digest = hmac.new(secret_bytes, signed_payload, hashlib.sha256).digest()
                signatures.add(digest.hex())
                signatures.add(base64.b64encode(digest).decode("ascii"))
                signatures.add(base64.b64encode(digest).decode("ascii").rstrip("="))
                signatures.add(base64.urlsafe_b64encode(digest).decode("ascii"))
                signatures.add(base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="))

    return signatures


def _signature_payload_bases(body: bytes) -> tuple[bytes, ...]:
    body_sha256 = hashlib.sha256(body).digest()
    return (
        body,
        body_sha256,
        body_sha256.hex().encode("ascii"),
    )


def _signed_payload_variants(
    body: bytes,
    *,
    timestamp_values: tuple[str, ...],
    event_values: tuple[str, ...],
) -> tuple[bytes, ...]:
    variants = [body]
    for timestamp_value in timestamp_values:
        timestamp_bytes = timestamp_value.encode("utf-8")
        variants.append(timestamp_bytes + b"." + body)
        variants.append(timestamp_bytes + body)

    for event_value in event_values:
        event_bytes = event_value.encode("utf-8")
        variants.append(event_bytes + b"." + body)
        variants.append(event_bytes + body)

        for timestamp_value in timestamp_values:
            timestamp_bytes = timestamp_value.encode("utf-8")
            variants.extend(
                [
                    event_bytes + b"." + timestamp_bytes + b"." + body,
                    event_bytes + timestamp_bytes + body,
                    timestamp_bytes + b"." + event_bytes + b"." + body,
                    timestamp_bytes + event_bytes + body,
                ]
            )

    return tuple(variants)


def _secret_byte_variants(secret: str) -> list[bytes]:
    variants = [secret.encode("utf-8")]

    if len(secret) % 2 == 0 and HEX_PATTERN.fullmatch(secret):
        variants.append(bytes.fromhex(secret))

    return variants


@webhooks_router.post(
    "/events/message-received",
    response_model=ChatResponse,
    dependencies=[Depends(verify_pipefacil_webhook_signature)],
)
def message_received(
    payload: MessageReceivedEventRequest,
    background_tasks: BackgroundTasks,
    graph: GraphDep,
    settings: SettingsDep,
    idempotency_store: IdempotencyStoreDep,
    response: Response,
) -> ChatResponse:
    received_extra = {
        **build_pipefacil_message_received_log_context(payload),
        "pipeline_step": "pipefacil.webhook.received",
    }
    if settings.log_inbound_payloads:
        received_extra["raw_payload"] = raw_log_value(
            build_pipefacil_message_received_raw_log_payload(payload)
        )

    LOGGER.info("pipefacil.webhook.received", extra=received_extra)

    try:
        thread_id = validate_pipefacil_message_received(payload)
    except PipefacilInboundMessageError as exc:
        LOGGER.warning(
            "pipefacil.webhook.rejected",
            extra={
                **build_pipefacil_message_received_log_context(payload),
                "pipeline_step": "pipefacil.webhook.rejected",
                "error_code": "pipefacil_inbound_error",
                "error_detail": str(exc),
                "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    background_tasks.add_task(
        _process_pipefacil_message_received,
        payload,
        thread_id=thread_id,
        graph=graph,
        settings=settings,
        idempotency_store=idempotency_store,
    )
    response.status_code = status.HTTP_200_OK
    LOGGER.info(
        "pipefacil.webhook.accepted",
        extra={
            **build_pipefacil_message_received_log_context(payload, thread_id=thread_id),
            "pipeline_step": "pipefacil.webhook.accepted",
            "status_code": status.HTTP_200_OK,
        },
    )

    return ChatResponse(
        thread_id=thread_id,
        intent=None,
        intent_reason="Pipefacil message accepted for background processing.",
        response_text="",
        status="accepted",
    )


def _process_pipefacil_message_received(
    payload: MessageReceivedEventRequest,
    *,
    thread_id: str,
    graph: Any,
    settings: Settings,
    idempotency_store: MessageIdempotencyStore,
) -> None:
    start = time.perf_counter()
    try:
        result = handle_pipefacil_message_received(
            payload,
            graph=graph,
            settings=settings,
            idempotency_store=idempotency_store,
        )
    except Exception as exc:
        LOGGER.exception(
            "pipefacil.webhook.processing_failed",
            extra={
                **build_pipefacil_message_received_log_context(payload, thread_id=thread_id),
                "pipeline_step": "pipefacil.webhook.processing_failed",
                "error_code": (
                    "pipefacil_inbound_error"
                    if isinstance(exc, PipefacilInboundMessageError)
                    else "unexpected_background_processing_error"
                ),
                "error_detail": str(exc),
                "duration_ms": round((time.perf_counter() - start) * 1000, 2),
            },
        )
        return

    LOGGER.info(
        "pipefacil.webhook.processing_completed",
        extra={
            **build_pipefacil_message_received_log_context(
                payload,
                thread_id=result.thread_id,
                delivery_status=result.delivery_status,
            ),
            "pipeline_step": "pipefacil.webhook.processing_completed",
            "error_code": result.delivery_error,
            "duration_ms": round((time.perf_counter() - start) * 1000, 2),
        },
    )
