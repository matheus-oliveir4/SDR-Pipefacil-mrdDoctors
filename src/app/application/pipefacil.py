from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, replace

from app.application.chat import fetch_thread_state, run_chat_turn
from app.application.delivery import build_response_parts
from app.application.dto import ChatTurnResult, ResponsePartResult
from app.application.generated_audio import GeneratedAudioError, prepare_generated_audio
from app.application.idempotency import (
    InMemoryMessageIdempotencyStore,
    MessageIdempotencyStore,
)
from app.application.token_budget import (
    LeadTokenUsage,
    build_lead_token_usage,
    normalize_max_tokens,
)
from app.application.whatsapp import split_whatsapp_messages
from app.core.config import Settings
from app.integrations.pipefacil import (
    CustomFieldValueResult,
    InboundMediaDownload,
    MessageReceivedEventRequest,
    PipefacilDealLookupError,
    PipefacilDealUpdateError,
    PipefacilInboundMessageError,
    PipefacilMediaProcessingError,
    PipefacilSendMessageError,
    build_message_received_log_context,
    build_message_received_metadata,
    build_message_received_raw_log_payload,
    fetch_deal_by_seq,
    is_ai_attendance_custom_field_disabled_value,
    normalize_message_received_content,
    resolve_custom_field_value,
    resolve_message_received_custom_field,
    resolve_message_received_pipeline_run_id,
    resolve_message_received_session_id,
    resolve_message_received_trace_user_id,
    send_public_text_message,
    send_whatsapp_media_message,
    update_deal_properties,
    validate_message_received_content,
)
from app.observability import observe_agent_run
from app.outbound_media import get_outbound_media_asset

LOGGER = logging.getLogger(__name__)
MEDIA_FALLBACK_RESPONSE_TEXT = (
    "Nao consegui processar esse arquivo agora. Pode reenviar ou mandar a informacao em texto?"
)
GENERATED_AUDIO_DELIVERY_FALLBACK_PREFIX = (
    "Nao consegui gerar o audio agora, entao te explico por texto:"
)
AI_ATTENDANCE_DISABLED_STATUS = "ai_attendance_disabled"
CONTACT_WITHOUT_LEAD_IGNORED_STATUS = "contact_without_lead_ignored"
DUPLICATE_MESSAGE_IGNORED_STATUS = "duplicate_message_ignored"
LEAD_TOKEN_LIMIT_EXCEEDED_STATUS = "lead_token_limit_exceeded"


@dataclass(frozen=True, slots=True)
class PipefacilAiAttendanceFieldResult:
    field: CustomFieldValueResult
    deal_not_found: bool = False


@dataclass(frozen=True, slots=True)
class PipefacilResponseTarget:
    recipient_phone: str | None
    channel_id: str | None = None
    sender_phone_number_id: str | None = None
    profile_name: str | None = None


def build_pipefacil_message_received_log_context(
    payload: MessageReceivedEventRequest,
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
    delivery_status: str | None = None,
):
    return build_message_received_log_context(
        payload,
        thread_id=thread_id,
        user_id=user_id,
        delivery_status=delivery_status,
    )


def build_pipefacil_message_received_raw_log_payload(
    payload: MessageReceivedEventRequest,
):
    return build_message_received_raw_log_payload(payload)


def _pipefacil_message_idempotency_key(payload: MessageReceivedEventRequest) -> str:
    identity = ":".join(
        (
            payload.type,
            payload.data.channel.id,
            resolve_message_received_pipeline_run_id(payload),
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def validate_pipefacil_message_received(payload: MessageReceivedEventRequest) -> str:
    """Run the local checks required before acknowledging the webhook."""
    session_id = resolve_message_received_session_id(payload)
    if payload.data.deal is not None:
        validate_message_received_content(payload)
    return session_id


def handle_pipefacil_message_received(
    payload: MessageReceivedEventRequest,
    *,
    graph=None,
    settings: Settings,
    idempotency_store: MessageIdempotencyStore | None = None,
) -> ChatTurnResult:
    session_id = resolve_message_received_session_id(payload)
    trace_user_id = resolve_message_received_trace_user_id(
        payload,
        mode=settings.langfuse_pipefacil_user_id_mode,
    )
    log_user_id = resolve_message_received_trace_user_id(payload)
    log_context = build_message_received_log_context(
        payload,
        thread_id=session_id,
        user_id=log_user_id,
    )

    LOGGER.info(
        "pipefacil.inbound.resolved",
        extra={
            **log_context,
            "pipeline_step": "pipefacil.inbound.resolved",
        },
    )

    if payload.data.deal is None:
        return _ignore_pipefacil_contact_without_lead(
            session_id=session_id,
            log_context=log_context,
            reason="Pipefacil contact message has no lead/deal.",
            deal_seq=None,
        )

    current_idempotency_store = idempotency_store or InMemoryMessageIdempotencyStore()
    idempotency_key = _pipefacil_message_idempotency_key(payload)
    if not current_idempotency_store.claim(
        idempotency_key,
        ttl_seconds=settings.pipefacil_webhook_idempotency_ttl_seconds,
    ):
        LOGGER.info(
            "pipefacil.inbound.duplicate_ignored",
            extra={
                **log_context,
                "pipeline_step": "pipefacil.inbound.duplicate_ignored",
                "pipefacil_idempotency_key": idempotency_key,
            },
        )
        return ChatTurnResult(
            thread_id=session_id,
            intent=None,
            intent_reason="Duplicate Pipefacil message webhook ignored.",
            response_text="",
            status=DUPLICATE_MESSAGE_IGNORED_STATUS,
        )

    try:
        return _handle_pipefacil_message_received_once(
            payload,
            graph=graph,
            settings=settings,
            session_id=session_id,
            trace_user_id=trace_user_id,
            log_user_id=log_user_id,
            log_context=log_context,
        )
    except Exception:
        current_idempotency_store.release(idempotency_key)
        raise


def _handle_pipefacil_message_received_once(
    payload: MessageReceivedEventRequest,
    *,
    graph,
    settings: Settings,
    session_id: str,
    trace_user_id: str,
    log_user_id: str,
    log_context: dict[str, object],
) -> ChatTurnResult:
    ai_attendance_field_slug = (settings.pipefacil_ai_attendance_field_slug or "").strip()
    if ai_attendance_field_slug:
        ai_attendance_lookup = _resolve_pipefacil_ai_attendance_field(
            payload,
            field_slug=ai_attendance_field_slug,
            settings=settings,
            log_context=log_context,
        )
        if ai_attendance_lookup.deal_not_found:
            return _ignore_pipefacil_contact_without_lead(
                session_id=session_id,
                log_context=log_context,
                reason="Pipefacil contact message references a missing lead/deal.",
                deal_seq=payload.data.deal.seq,
            )

        ai_attendance_field = ai_attendance_lookup.field
        if not ai_attendance_field.found:
            LOGGER.info(
                "pipefacil.inbound.ai_attendance_default_enabled",
                extra={
                    **log_context,
                    "pipeline_step": "pipefacil.inbound.ai_attendance_default_enabled",
                    "pipefacil_custom_field_slug": ai_attendance_field_slug,
                },
            )

        if is_ai_attendance_custom_field_disabled_value(ai_attendance_field.value):
            LOGGER.info(
                "pipefacil.inbound.ai_attendance_disabled",
                extra={
                    **log_context,
                    "pipeline_step": "pipefacil.inbound.ai_attendance_disabled",
                    "pipefacil_custom_field_slug": ai_attendance_field_slug,
                },
            )
            return ChatTurnResult(
                thread_id=session_id,
                intent=None,
                intent_reason="Pipefacil Atendimento por IA custom field is disabled.",
                response_text="",
                status=AI_ATTENDANCE_DISABLED_STATUS,
            )

    lead_max_tokens = normalize_max_tokens(settings.pipefacil_max_tokens_per_lead)
    if lead_max_tokens:
        lead_token_usage = _build_pipefacil_lead_token_usage(
            payload,
            thread_id=session_id,
            graph=graph,
            settings=settings,
        )
        if lead_token_usage.exceeded:
            LOGGER.info(
                "pipefacil.inbound.lead_token_limit_exceeded",
                extra={
                    **log_context,
                    "pipeline_step": "pipefacil.inbound.lead_token_limit_exceeded",
                    "lead_current_tokens": lead_token_usage.current_tokens,
                    "lead_incoming_tokens": lead_token_usage.incoming_tokens,
                    "lead_total_tokens": lead_token_usage.total_tokens,
                    "lead_max_tokens": lead_token_usage.max_tokens,
                },
            )
            _disable_pipefacil_ai_attendance_for_token_limit(
                payload,
                field_slug=ai_attendance_field_slug,
                settings=settings,
                log_context=log_context,
            )
            return ChatTurnResult(
                thread_id=session_id,
                intent=None,
                intent_reason="Pipefacil lead token budget exceeded.",
                response_text="",
                status=LEAD_TOKEN_LIMIT_EXCEEDED_STATUS,
            )

    media_download_logged = False

    def log_media_downloaded(media_download: InboundMediaDownload) -> None:
        nonlocal media_download_logged
        media_download_logged = True
        LOGGER.info(
            "pipefacil.inbound.media_downloaded",
            extra={
                **log_context,
                "pipeline_step": "pipefacil.inbound.media_downloaded",
                "message_type": media_download.message_type,
                "media_mime_type": media_download.media_mime_type,
                "media_size": media_download.media_size,
                "status_code": media_download.media_status_code,
            },
        )

    try:
        inbound_message = normalize_message_received_content(
            payload,
            settings=settings,
            on_media_downloaded=log_media_downloaded,
        )
    except PipefacilMediaProcessingError as exc:
        LOGGER.warning(
            "pipefacil.inbound.media_failed",
            extra={
                **log_context,
                "pipeline_step": "pipefacil.inbound.media_failed",
                "error_code": exc.error_code,
                "status_code": exc.status_code,
                "media_mime_type": exc.media_mime_type,
                "media_size": exc.media_size,
            },
        )
        fallback_response = ChatTurnResult(
            thread_id=session_id,
            intent="fallback",
            intent_reason=f"Media processing failed: {exc.error_code}.",
            response_text=MEDIA_FALLBACK_RESPONSE_TEXT,
            status="media_failed",
            response_messages=split_whatsapp_messages(MEDIA_FALLBACK_RESPONSE_TEXT),
        )
        return _send_pipefacil_response(
            payload,
            response=fallback_response,
            user_id=log_user_id,
            settings=settings,
        )

    if inbound_message.has_media and not media_download_logged:
        LOGGER.info(
            "pipefacil.inbound.media_downloaded",
            extra={
                **log_context,
                "pipeline_step": "pipefacil.inbound.media_downloaded",
                "message_type": inbound_message.message_type,
                "media_mime_type": inbound_message.media_mime_type,
                "media_size": inbound_message.media_size,
                "status_code": inbound_message.media_status_code,
            },
        )

    if inbound_message.message_type == "audio":
        LOGGER.info(
            "pipefacil.inbound.audio_transcribed",
            extra={
                **log_context,
                "pipeline_step": "pipefacil.inbound.audio_transcribed",
                "media_mime_type": inbound_message.media_mime_type,
                "media_size": inbound_message.media_size,
                "transcription_length": inbound_message.transcription_length,
            },
        )

    LOGGER.debug(
        "pipefacil.inbound.details",
        extra={
            **log_context,
            "pipeline_step": "pipefacil.inbound.details",
            "message_type": inbound_message.message_type,
            "message_body_length": len(inbound_message.text),
            "channel_id": payload.data.channel.id,
            "contact_id": payload.data.contact.id,
            "deal_id": payload.data.deal.id if payload.data.deal else None,
        },
    )

    trace_metadata = build_message_received_metadata(
        payload,
        session_id=session_id,
        user_id=trace_user_id,
    ) | {
        "normalized_message": {
            "message_type": inbound_message.message_type,
            "has_media": inbound_message.has_media,
            "media_mime_type": inbound_message.media_mime_type,
            "media_size": inbound_message.media_size,
            "transcription_length": inbound_message.transcription_length,
        }
    }
    with observe_agent_run(
        name="handle-pipefacil-turn",
        input=_build_pipefacil_trace_input(inbound_message),
        session_id=session_id,
        user_id=trace_user_id,
        tags=("pipefacil", "whatsapp", "delivery"),
        metadata=trace_metadata,
        as_type="chain",
    ) as observation:
        LOGGER.info(
            "agent.run.started",
            extra={
                **log_context,
                "pipeline_step": "agent.run.started",
            },
        )
        response = run_chat_turn(
            message=inbound_message.content,
            thread_id=session_id,
            session_id=session_id,
            user_id=trace_user_id,
            metadata=trace_metadata,
            graph=graph,
        )
        LOGGER.info(
            "agent.run.completed",
            extra={
                **log_context,
                "pipeline_step": "agent.run.completed",
                "intent": response.intent,
                "agent_status": response.status,
            },
        )
        LOGGER.debug(
            "agent.run.details",
            extra={
                **log_context,
                "pipeline_step": "agent.run.details",
                "intent_reason": response.intent_reason,
                "response_text_length": len(response.response_text),
                "response_message_count": len(response.response_messages),
                "response_part_count": len(response.response_parts),
            },
        )
        delivered_response = _send_pipefacil_response(
            payload,
            response=response,
            user_id=log_user_id,
            settings=settings,
        )
        if observation is not None:
            observation.update(
                output={
                    "status": delivered_response.status,
                    "delivery_status": delivered_response.delivery_status,
                    "response_text": delivered_response.response_text,
                    "response_part_count": len(delivered_response.response_parts),
                }
            )
        return delivered_response


def _ignore_pipefacil_contact_without_lead(
    *,
    session_id: str,
    log_context: dict[str, object],
    reason: str,
    deal_seq: int | None,
) -> ChatTurnResult:
    LOGGER.info(
        "pipefacil.inbound.contact_without_lead_ignored",
        extra={
            **log_context,
            "pipeline_step": "pipefacil.inbound.contact_without_lead_ignored",
            "deal_seq": deal_seq,
        },
    )
    return ChatTurnResult(
        thread_id=session_id,
        intent=None,
        intent_reason=reason,
        response_text="",
        status=CONTACT_WITHOUT_LEAD_IGNORED_STATUS,
    )


def _send_pipefacil_response(
    payload: MessageReceivedEventRequest,
    *,
    response: ChatTurnResult,
    user_id: str,
    settings: Settings,
) -> ChatTurnResult:
    log_context = build_message_received_log_context(
        payload,
        thread_id=response.thread_id,
        user_id=user_id,
    )
    return deliver_pipefacil_response(
        response,
        target=PipefacilResponseTarget(
            recipient_phone=payload.data.contact.phone,
            channel_id=payload.data.channel.id,
            sender_phone_number_id=payload.data.channel.phoneNumberId,
            profile_name=payload.data.contact.name,
        ),
        settings=settings,
        log_context=log_context,
    )


def deliver_pipefacil_response(
    response: ChatTurnResult,
    *,
    target: PipefacilResponseTarget,
    settings: Settings,
    log_context: dict[str, object] | None = None,
) -> ChatTurnResult:
    resolved_log_context = dict(log_context or {})
    text_parts = response.response_messages or split_whatsapp_messages(response.response_text)
    text_parts = [message_part.strip() for message_part in text_parts if message_part.strip()]
    if not text_parts and response.response_text.strip():
        text_parts = [response.response_text.strip()]

    response_parts = response.response_parts or build_response_parts(
        response_messages=text_parts,
        response_media=[],
    )
    response_parts = _normalize_response_parts(response_parts)
    if not response_parts:
        response_parts = [ResponsePartResult(type="text", text=response.response_text)]
    response_parts, generated_media_urls = _apply_generated_audio_delivery(
        response=response,
        response_parts=response_parts,
        settings=settings,
        log_context=resolved_log_context,
    )

    text_parts = [part.text for part in response_parts if part.type == "text" and part.text]
    response_with_parts = replace(
        response,
        response_messages=text_parts,
        response_parts=response_parts,
    )
    message_part_count = len(response_parts)

    LOGGER.info(
        "pipefacil.outbound.started",
        extra={
            **resolved_log_context,
            "pipeline_step": "pipefacil.outbound.started",
            "message_part_count": message_part_count,
        },
    )

    for message_part_index, response_part in enumerate(response_parts, start=1):
        try:
            result = _send_pipefacil_response_part(
                target,
                response_part=response_part,
                settings=settings,
                generated_media_urls=generated_media_urls,
            )
        except PipefacilSendMessageError as exc:
            LOGGER.exception(
                "pipefacil.outbound.failed",
                extra={
                    **resolved_log_context,
                    "delivery_status": "failed",
                    "pipeline_step": "pipefacil.outbound.failed",
                    "error_code": exc.error_code,
                    "status_code": exc.status_code,
                    "request_id": exc.request_id,
                    "message_part_index": message_part_index,
                    "message_part_count": message_part_count,
                    "message_part_type": response_part.type,
                    "media_id": response_part.media_id,
                    "media_content_type": response_part.content_type,
                },
            )
            return replace(
                response_with_parts,
                delivery_status="failed",
                delivery_error=exc.error_code,
            )

        LOGGER.info(
            "pipefacil.outbound.delivered",
            extra={
                **resolved_log_context,
                "delivery_status": "sent",
                "pipeline_step": "pipefacil.outbound.delivered",
                "status_code": result.status_code,
                "request_id": result.request_id,
                "message_part_index": message_part_index,
                "message_part_count": message_part_count,
                "message_part_type": response_part.type,
                "media_id": response_part.media_id,
                "media_content_type": response_part.content_type,
            },
        )

    return replace(response_with_parts, delivery_status="sent")


def _apply_generated_audio_delivery(
    *,
    response: ChatTurnResult,
    response_parts: list[ResponsePartResult],
    settings: Settings,
    log_context: dict[str, object],
) -> tuple[list[ResponsePartResult], dict[str, str]]:
    generated_media_urls: dict[str, str] = {}
    if not settings.generated_audio_enabled:
        return response_parts, generated_media_urls

    audio_text = _resolve_generated_audio_text(response, response_parts, settings=settings)
    if not audio_text:
        return response_parts, generated_media_urls

    explicit_audio = response.response_audio is not None
    try:
        generated_audio = prepare_generated_audio(text=audio_text, settings=settings)
    except GeneratedAudioError as exc:
        LOGGER.warning(
            "generated_audio.failed",
            extra={
                **log_context,
                "pipeline_step": "generated_audio.failed",
                "error_code": exc.error_code,
                "upstream_status_code": exc.status_code,
                "generated_audio_attempt_count": exc.attempt_count,
                "generated_audio_explicit": explicit_audio,
                "generated_audio_text_length": len(audio_text),
            },
        )
        if explicit_audio:
            return _build_generated_audio_text_fallback(response, audio_text), generated_media_urls
        return response_parts, generated_media_urls

    generated_media_urls[generated_audio.media_id] = generated_audio.media_url
    LOGGER.info(
        "generated_audio.created",
        extra={
            **log_context,
            "pipeline_step": "generated_audio.created",
            "generated_audio_media_id": generated_audio.media_id,
            "generated_audio_content_type": generated_audio.content_type,
            "generated_audio_attempt_count": generated_audio.attempt_count,
            "generated_audio_text_length": len(generated_audio.text),
        },
    )

    generated_audio_part = ResponsePartResult(
        type="audio",
        media_id=generated_audio.media_id,
        content_type=generated_audio.content_type,
        filename=generated_audio.filename,
    )
    if explicit_audio:
        text_intro_parts = _ensure_generated_audio_text_intro(response, response_parts, settings)
        text_parts = [part for part in text_intro_parts if part.type == "text"]
        non_text_parts = [part for part in text_intro_parts if part.type != "text"]
        return [*text_parts, generated_audio_part, *non_text_parts], generated_media_urls

    non_text_parts = [part for part in response_parts if part.type != "text"]
    return [
        ResponsePartResult(type="text", text=_generated_audio_auto_text(settings)),
        generated_audio_part,
        *non_text_parts,
    ], generated_media_urls


def _resolve_generated_audio_text(
    response: ChatTurnResult,
    response_parts: list[ResponsePartResult],
    *,
    settings: Settings,
) -> str | None:
    if response.response_audio is not None:
        return response.response_audio.text.strip()

    if not settings.generated_audio_auto_enabled:
        return None

    response_text = response.response_text.strip()
    if len(response_text) < settings.generated_audio_auto_min_chars:
        return None

    if any(part.type == "audio" and part.media_id for part in response_parts):
        return None

    return response_text


def _build_pipefacil_trace_input(inbound_message: InboundMediaDownload) -> dict[str, object]:
    return {
        "message_type": inbound_message.message_type,
        "text": inbound_message.text,
        "has_media": inbound_message.has_media,
    }


def _ensure_generated_audio_text_intro(
    response: ChatTurnResult,
    response_parts: list[ResponsePartResult],
    settings: Settings,
) -> list[ResponsePartResult]:
    if any(part.type == "text" and (part.text or "").strip() for part in response_parts):
        return response_parts

    intro_text = response.response_text.strip() or _generated_audio_auto_text(settings)
    return [ResponsePartResult(type="text", text=intro_text), *response_parts]


def _build_generated_audio_text_fallback(
    response: ChatTurnResult,
    audio_text: str,
) -> list[ResponsePartResult]:
    non_audio_parts = [
        part
        for part in response.response_parts
        if not (
            part.type == "audio" and part.media_id and part.media_id.startswith("generated-audio:")
        )
    ]
    fallback_text = f"{GENERATED_AUDIO_DELIVERY_FALLBACK_PREFIX}\n\n{audio_text.strip()}"
    fallback_parts = [
        ResponsePartResult(type="text", text=text)
        for text in split_whatsapp_messages(fallback_text)
    ]
    non_text_parts = [part for part in non_audio_parts if part.type != "text"]
    return [*fallback_parts, *non_text_parts]


def _generated_audio_auto_text(settings: Settings) -> str:
    return settings.generated_audio_auto_text.strip() or "Te mandei um audio para explicar melhor."


def _build_pipefacil_lead_token_usage(
    payload: MessageReceivedEventRequest,
    *,
    thread_id: str,
    graph,
    settings: Settings,
) -> LeadTokenUsage:
    thread_state = fetch_thread_state(thread_id, graph=graph)
    return build_lead_token_usage(
        messages=list(thread_state.messages) if thread_state is not None else [],
        incoming_text=_message_received_token_text(payload),
        max_tokens=settings.pipefacil_max_tokens_per_lead,
        model_name=settings.openai_model,
    )


def _resolve_pipefacil_ai_attendance_field(
    payload: MessageReceivedEventRequest,
    *,
    field_slug: str,
    settings: Settings,
    log_context: dict[str, object],
) -> PipefacilAiAttendanceFieldResult:
    webhook_field = resolve_message_received_custom_field(payload, field_slug=field_slug)
    if webhook_field.found:
        return PipefacilAiAttendanceFieldResult(field=webhook_field)

    deal_seq = payload.data.deal.seq if payload.data.deal is not None else None
    try:
        deal_payload = fetch_deal_by_seq(seq=deal_seq, settings=settings)
    except PipefacilDealLookupError as exc:
        LOGGER.warning(
            "pipefacil.inbound.ai_attendance_lookup_failed",
            extra={
                **log_context,
                "pipeline_step": "pipefacil.inbound.ai_attendance_lookup_failed",
                "pipefacil_custom_field_slug": field_slug,
                "deal_seq": deal_seq,
                "error_code": exc.error_code,
                "status_code": exc.status_code,
                "request_id": exc.request_id,
            },
        )
        return PipefacilAiAttendanceFieldResult(
            field=CustomFieldValueResult(found=False),
            deal_not_found=exc.status_code == 404,
        )

    lookup_field = resolve_custom_field_value(deal_payload, field_slug=field_slug)
    LOGGER.info(
        "pipefacil.inbound.ai_attendance_lookup_completed",
        extra={
            **log_context,
            "pipeline_step": "pipefacil.inbound.ai_attendance_lookup_completed",
            "pipefacil_custom_field_slug": field_slug,
            "deal_seq": deal_seq,
            "pipefacil_custom_field_found": lookup_field.found,
        },
    )
    return PipefacilAiAttendanceFieldResult(field=lookup_field)


def _disable_pipefacil_ai_attendance_for_token_limit(
    payload: MessageReceivedEventRequest,
    *,
    field_slug: str,
    settings: Settings,
    log_context: dict[str, object],
) -> None:
    deal_seq = payload.data.deal.seq if payload.data.deal is not None else None
    if not field_slug or deal_seq is None:
        LOGGER.warning(
            "pipefacil.inbound.ai_attendance_disable_failed",
            extra={
                **log_context,
                "pipeline_step": "pipefacil.inbound.ai_attendance_disable_failed",
                "pipefacil_custom_field_slug": field_slug,
                "deal_seq": deal_seq,
                "error_code": "pipefacil_deal_seq_missing",
            },
        )
        return

    try:
        result = update_deal_properties(
            seq=deal_seq,
            properties={field_slug: False},
            settings=settings,
        )
    except PipefacilDealUpdateError as exc:
        LOGGER.warning(
            "pipefacil.inbound.ai_attendance_disable_failed",
            extra={
                **log_context,
                "pipeline_step": "pipefacil.inbound.ai_attendance_disable_failed",
                "pipefacil_custom_field_slug": field_slug,
                "deal_seq": deal_seq,
                "error_code": exc.error_code,
                "status_code": exc.status_code,
                "request_id": exc.request_id,
            },
        )
        return

    LOGGER.info(
        "pipefacil.inbound.ai_attendance_disabled_in_crm",
        extra={
            **log_context,
            "pipeline_step": "pipefacil.inbound.ai_attendance_disabled_in_crm",
            "pipefacil_custom_field_slug": field_slug,
            "deal_seq": deal_seq,
            "status_code": result.status_code,
            "request_id": result.request_id,
        },
    )


def _message_received_token_text(payload: MessageReceivedEventRequest) -> str:
    message = payload.data.message
    message_type = message.type.strip().lower()
    message_body = (message.body or "").strip()
    if message_type == "text":
        return message_body

    text_parts = [f"Tipo de mensagem: {message_type}"] if message_type else []
    if message_body:
        text_parts.append(f"Legenda: {message_body}")
    return "\n".join(text_parts)


def _normalize_response_parts(
    response_parts: list[ResponsePartResult],
) -> list[ResponsePartResult]:
    normalized_parts: list[ResponsePartResult] = []
    for response_part in response_parts:
        if response_part.type == "text":
            text = (response_part.text or "").strip()
            if text:
                normalized_parts.append(replace(response_part, text=text))
            continue

        if response_part.media_id:
            normalized_parts.append(response_part)

    return normalized_parts


def _send_pipefacil_response_part(
    target: PipefacilResponseTarget,
    *,
    response_part: ResponsePartResult,
    settings: Settings,
    generated_media_urls: dict[str, str] | None = None,
):
    if response_part.type == "text":
        return send_public_text_message(
            to=target.recipient_phone,
            text=response_part.text or "",
            sender_phone_number_id=target.sender_phone_number_id,
            profile_name=target.profile_name,
            settings=settings,
        )

    media_id = response_part.media_id or ""
    media_url = (generated_media_urls or {}).get(media_id)
    filename = response_part.filename
    content_type = response_part.content_type
    if media_url is None:
        media_asset = get_outbound_media_asset(media_id)
        if media_asset is not None:
            media_url = media_asset.media_url
            filename = media_asset.filename
            content_type = media_asset.content_type

    if media_url is None:
        raise PipefacilSendMessageError(
            "Outbound media selection is no longer available.",
            error_code="response_media_url_missing",
        )

    return send_whatsapp_media_message(
        to=target.recipient_phone,
        media_type=response_part.type,
        media_url=media_url,
        caption=response_part.caption,
        filename=filename,
        mime_type=content_type,
        channel_id=target.channel_id,
        sender_phone_number_id=target.sender_phone_number_id,
        settings=settings,
    )


__all__ = [
    "PipefacilInboundMessageError",
    "PipefacilResponseTarget",
    "build_pipefacil_message_received_log_context",
    "build_pipefacil_message_received_raw_log_payload",
    "deliver_pipefacil_response",
    "handle_pipefacil_message_received",
]
