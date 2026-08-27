from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from openai import BadRequestError

from app.agent.chains import build_responder_chain, invoke_with_temperature_fallback
from app.agent.chains.schemas import AgentResponsePlan, OutboundMediaChoice
from app.agent.messages import latest_user_message, message_to_text, serialize_messages
from app.agent.prompts import get_whatsapp_style_prompt_text
from app.agent.state import AgentState
from app.outbound_media import (
    OUTBOUND_MEDIA_CATALOG_UNAVAILABLE_TEXT,
    build_outbound_media_prompt_view,
    get_enabled_outbound_media_by_id,
)

LOGGER = logging.getLogger(__name__)

_MEDIA_REQUEST_TERMS = {
    "arquivo",
    "arquivos",
    "audio",
    "audios",
    "catalogo",
    "comparativo",
    "documento",
    "documentos",
    "enviar",
    "envia",
    "foto",
    "fotos",
    "imagem",
    "imagens",
    "manda",
    "mandar",
    "mostra",
    "mostrar",
    "pdf",
    "tabela",
    "video",
    "videos",
    "voz",
    "vozes",
}
_PLAN_REQUEST_TERMS = {
    "condicao",
    "condicoes",
    "plano",
    "planos",
    "preco",
    "precos",
    "valor",
    "valores",
}
_PERIOD_ALIASES = {
    "anual": {"anual", "anuais"},
    "semestral": {"semestral", "semestrais"},
    "mensal": {"mensal", "mensais", "mes", "meses"},
}
_MEDIA_TYPE_ALIASES = {
    "audio": {"audio", "audios", "voz", "vozes"},
    "image": {"foto", "fotos", "imagem", "imagens"},
    "video": {"video", "videos"},
    "document": {"arquivo", "arquivos", "documento", "documentos", "pdf"},
}


def _fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _message_tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _fold_text(value)))


def _infer_catalog_media_choice(latest_message: str) -> OutboundMediaChoice | None:
    tokens = _message_tokens(latest_message)
    explicit_media_request = bool(tokens & _MEDIA_REQUEST_TERMS)
    plan_request = bool(tokens & _PLAN_REQUEST_TERMS)
    if not explicit_media_request and not plan_request:
        return None

    candidates = list(get_enabled_outbound_media_by_id().values())
    if not candidates:
        return None

    requested_periods = [period for period, aliases in _PERIOD_ALIASES.items() if tokens & aliases]
    if len(requested_periods) > 1:
        return None
    requested_period = requested_periods[0] if requested_periods else None
    if requested_period is not None:
        candidates = [
            asset
            for asset in candidates
            if requested_period
            in _fold_text(f"{asset.title} {asset.description} {asset.when_to_use}")
        ]
        if not candidates:
            return None
    elif plan_request:
        default_candidates = [
            asset
            for asset in candidates
            if "sem indicar periodicidade" in _fold_text(asset.when_to_use)
        ]
        if default_candidates:
            candidates = default_candidates

    requested_types = [
        media_type for media_type, aliases in _MEDIA_TYPE_ALIASES.items() if tokens & aliases
    ]
    if len(requested_types) > 1:
        return None
    requested_type = requested_types[0] if requested_types else None
    if requested_type is not None:
        candidates = [asset for asset in candidates if asset.type == requested_type]
        if not candidates:
            return None

    if len(candidates) != 1:
        return None

    return OutboundMediaChoice(
        media_id=candidates[0].id,
        reason="Catalog media matched the user's explicit request.",
    )


def _invoke_with_temperature_fallback(
    chain_factory,
    payload: dict[str, Any],
    *,
    config: RunnableConfig = None,
) -> Any:
    return invoke_with_temperature_fallback(chain_factory, payload, config=config)


def _latest_user_message(state: AgentState) -> str:
    return latest_user_message(state)


def _response_to_text(response: Any) -> str:
    if isinstance(response, BaseMessage):
        return message_to_text(response)

    return str(response)


def _response_to_plan(response: Any) -> AgentResponsePlan:
    if isinstance(response, AgentResponsePlan):
        return response

    if isinstance(response, dict) and "response_text" in response:
        return AgentResponsePlan.model_validate(response)

    return AgentResponsePlan(response_text=_response_to_text(response), media_choices=[])


def _build_responder_chain(*, use_custom_temperature: bool = True):
    return build_responder_chain(use_custom_temperature=use_custom_temperature)


def _get_response_style() -> str:
    _, response_style = get_whatsapp_style_prompt_text()
    return response_style


def _get_available_media_prompt_view() -> str:
    return build_outbound_media_prompt_view()


def _build_delivery_context_message(available_media: str) -> SystemMessage | None:
    safe_media_context = available_media.strip()
    if not safe_media_context or safe_media_context == OUTBOUND_MEDIA_CATALOG_UNAVAILABLE_TEXT:
        return None

    return SystemMessage(
        content=(
            "Delivery capability for this turn:\n"
            "You can select outbound media from the catalog by returning media_choices "
            "in the structured response. The application will send selected media after "
            "your text reply.\n"
            "If the user asks for an audio, image, video, or document and a catalog item "
            "matches, choose that media_id. Do not say you cannot send media when a "
            "matching catalog item is available.\n"
            "Use only media_id values listed here. Never invent URLs, filenames, or raw "
            f"file content.\nAvailable outbound media:\n{safe_media_context}"
        )
    )


def _conversation_history_with_delivery_context(
    messages: list[Any],
    *,
    available_media: str,
) -> list[Any]:
    delivery_context = _build_delivery_context_message(available_media)
    if delivery_context is None:
        return messages

    return [delivery_context, *messages]


def _validate_media_choices(
    choices: list[OutboundMediaChoice],
) -> list[dict[str, Any]]:
    enabled_media = get_enabled_outbound_media_by_id()
    selected_media: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    for choice in choices:
        media_id = choice.media_id.strip()
        asset = enabled_media.get(media_id)
        if asset is None:
            LOGGER.warning(
                "agent.outbound_media.ignored",
                extra={
                    "pipeline_step": "agent.outbound_media.ignored",
                    "media_id": media_id,
                    "reason": "unknown_or_disabled_media",
                },
            )
            continue

        if media_id in selected_ids:
            LOGGER.warning(
                "agent.outbound_media.ignored",
                extra={
                    "pipeline_step": "agent.outbound_media.ignored",
                    "media_id": media_id,
                    "reason": "duplicate_media",
                },
            )
            continue

        selected_ids.add(media_id)
        selected_media.append(
            {
                "media_id": asset.id,
                "type": asset.type,
                "caption": choice.caption.strip() if choice.caption else None,
                "reason": choice.reason,
                "content_type": asset.content_type,
                "filename": asset.filename,
            }
        )

    return selected_media


def _has_file_content(messages: list[Any]) -> bool:
    for message in messages:
        content = message.get("content", "") if isinstance(message, dict) else message.content
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "file":
                return True

    return False


def _invoke_responder_with_file_fallback(
    payload: dict[str, Any],
    *,
    config: RunnableConfig = None,
) -> Any:
    try:
        return _invoke_with_temperature_fallback(
            _build_responder_chain,
            payload,
            config=config,
        )
    except BadRequestError:
        if not _has_file_content(list(payload.get("conversation_history", []))):
            raise

    retry_payload = dict(payload)
    retry_payload["conversation_history"] = serialize_messages(
        list(payload.get("conversation_history", []))
    )
    return _invoke_with_temperature_fallback(
        _build_responder_chain,
        retry_payload,
        config=config,
    )


def _specialist_context(state: AgentState) -> str:
    result = state.get("specialist_result")
    if not result:
        return "No specialist result."

    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def respond(
    state: AgentState,
    config: RunnableConfig = None,
) -> dict[str, Any]:
    latest_message = state.get("latest_user_message") or _latest_user_message(state)
    intent = state.get("intent", "fallback")

    if not latest_message:
        response_text = "Ainda nao recebi nenhuma mensagem do usuario."
        return {
            "latest_user_message": "",
            "response_text": response_text,
            "response_media": [],
            "messages": [AIMessage(content=response_text)],
            "status": "responded",
        }

    available_media = _get_available_media_prompt_view()
    resume_context = str(state.get("resume_context") or "").strip()
    conversation_history = _conversation_history_with_delivery_context(
        list(state.get("messages", [])),
        available_media=available_media,
    )

    response = _invoke_responder_with_file_fallback(
        {
            "intent": intent,
            "latest_user_message": latest_message,
            "conversation_history": conversation_history,
            "specialist_result": state.get("specialist_result"),
            "specialist_context": _specialist_context(state),
            "resume_context": resume_context or "No additional resume context.",
            "response_style": _get_response_style(),
            "available_media": available_media,
        },
        config=config,
    )
    response_plan = _response_to_plan(response)
    response_text = response_plan.response_text
    response_media = _validate_media_choices(response_plan.media_choices)
    if not response_media:
        inferred_media = _infer_catalog_media_choice(latest_message)
        if inferred_media is not None:
            response_media = _validate_media_choices([inferred_media])
            LOGGER.info(
                "agent.outbound_media.inferred",
                extra={
                    "pipeline_step": "agent.outbound_media.inferred",
                    "media_id": inferred_media.media_id,
                    "reason": inferred_media.reason,
                },
            )

    response_audio = None
    if not any(media.get("type") == "audio" for media in response_media):
        response_audio = (
            response_plan.generated_audio.model_dump()
            if response_plan.generated_audio is not None
            else None
        )
    response_message = (
        response if isinstance(response, BaseMessage) else AIMessage(content=response_text)
    )

    return {
        "latest_user_message": latest_message,
        "response_text": response_text,
        "response_media": response_media,
        "response_audio": response_audio,
        "messages": [response_message],
        "status": "responded",
    }
