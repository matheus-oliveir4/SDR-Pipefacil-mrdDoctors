from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agent.messages import latest_user_message, serialize_messages
from app.agent.specialists import (
    DEFAULT_SPECIALIST_REGISTRY,
    OpenAISpecialistRunner,
    SpecialistRequest,
    SpecialistResult,
    failed_specialist_result,
    skipped_specialist_result,
)
from app.agent.state import AgentState
from app.core.config import Settings, get_settings

LOGGER = logging.getLogger(__name__)


def _thread_id_from_config(config: RunnableConfig = None) -> str | None:
    if not config:
        return None
    configurable = config.get("configurable", {})
    thread_id = configurable.get("thread_id")
    return str(thread_id) if thread_id else None


def _build_specialist_request(state: AgentState) -> SpecialistRequest:
    latest_message = state.get("latest_user_message") or latest_user_message(state)
    return SpecialistRequest(
        objective=state.get("specialist_reason") or "Run specialist analysis for this turn.",
        latest_user_message=latest_message,
        intent=state.get("intent"),
        intent_reason=state.get("intent_reason"),
        conversation_history=serialize_messages(state.get("messages", [])),
    )


def _run_specialist(
    *,
    specialist_name: str,
    request: SpecialistRequest,
    settings: Settings,
) -> SpecialistResult:
    return OpenAISpecialistRunner(settings=settings).run(
        specialist_name=specialist_name,
        request=request,
    )


def _result_payload(result: SpecialistResult) -> dict[str, Any]:
    return result.model_dump(mode="json")


def delegate_specialist(
    state: AgentState,
    config: RunnableConfig = None,
) -> dict[str, Any]:
    requested_specialist_name = state.get("specialist_name")
    thread_id = _thread_id_from_config(config)

    if not state.get("requires_specialist") or not requested_specialist_name:
        result = skipped_specialist_result("specialist_not_required")
        LOGGER.info(
            "specialist.run.skipped",
            extra={
                "thread_id": thread_id,
                "specialist_status": result.status,
                "specialist_error_code": result.error_code,
            },
        )
        return {
            "specialist_status": result.status,
            "specialist_result": _result_payload(result),
        }

    specialist_name = DEFAULT_SPECIALIST_REGISTRY.resolve_name(requested_specialist_name)
    if specialist_name is None:
        result = failed_specialist_result("specialist_unknown")
        LOGGER.warning(
            "specialist.run.failed",
            extra={
                "thread_id": thread_id,
                "specialist_name": requested_specialist_name,
                "specialist_status": result.status,
                "specialist_error_code": result.error_code,
            },
        )
        return {
            "specialist_name": requested_specialist_name,
            "specialist_status": result.status,
            "specialist_result": _result_payload(result),
        }

    settings = get_settings()
    if not settings.openai_specialists_enabled:
        result = skipped_specialist_result("openai_specialists_disabled")
        LOGGER.info(
            "specialist.run.skipped",
            extra={
                "thread_id": thread_id,
                "specialist_name": specialist_name,
                "specialist_status": result.status,
                "specialist_error_code": result.error_code,
            },
        )
        return {
            "specialist_name": specialist_name,
            "specialist_status": result.status,
            "specialist_result": _result_payload(result),
        }

    try:
        request = _build_specialist_request(state)
    except ValueError as exc:
        result = failed_specialist_result("specialist_request_invalid", summary=str(exc))
        LOGGER.warning(
            "specialist.run.failed",
            extra={
                "thread_id": thread_id,
                "specialist_name": specialist_name,
                "specialist_status": result.status,
                "specialist_error_code": result.error_code,
            },
        )
        return {
            "specialist_name": specialist_name,
            "specialist_status": result.status,
            "specialist_result": _result_payload(result),
        }

    LOGGER.info(
        "specialist.run.started",
        extra={
            "thread_id": thread_id,
            "specialist_name": specialist_name,
            "intent": state.get("intent"),
        },
    )
    result = _run_specialist(
        specialist_name=specialist_name,
        request=request,
        settings=settings,
    )

    log_extra = {
        "thread_id": thread_id,
        "specialist_name": specialist_name,
        "specialist_status": result.status,
        "specialist_confidence": result.confidence,
        "specialist_error_code": result.error_code,
    }
    if result.status == "failed":
        LOGGER.warning("specialist.run.failed", extra=log_extra)
    else:
        LOGGER.info("specialist.run.completed", extra=log_extra)

    return {
        "specialist_name": specialist_name,
        "specialist_status": result.status,
        "specialist_result": _result_payload(result),
    }
