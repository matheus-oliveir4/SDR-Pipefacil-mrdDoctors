from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agent.chains import build_classifier_chain, invoke_with_temperature_fallback
from app.agent.messages import latest_user_message
from app.agent.state import AgentState


def _invoke_with_temperature_fallback(
    chain_factory,
    payload: dict[str, Any],
    *,
    config: RunnableConfig = None,
) -> Any:
    return invoke_with_temperature_fallback(chain_factory, payload, config=config)


def _latest_user_message(state: AgentState) -> str:
    return latest_user_message(state)


def _build_classifier_chain(*, use_custom_temperature: bool = True):
    return build_classifier_chain(use_custom_temperature=use_custom_temperature)


def classify_intent(
    state: AgentState,
    config: RunnableConfig = None,
) -> dict[str, str]:
    latest_message = _latest_user_message(state)
    if not latest_message and state.get("resume_context"):
        latest_message = "Retome a conversa com o lead de forma natural."
    if not latest_message:
        return {
            "latest_user_message": "",
            "intent": "fallback",
            "intent_reason": "No user message was available for classification.",
            "status": "classified",
        }

    result = _invoke_with_temperature_fallback(
        _build_classifier_chain,
        {"latest_user_message": latest_message},
        config=config,
    )

    return {
        "latest_user_message": latest_message,
        "intent": result.intent,
        "intent_reason": result.reason,
        "requires_specialist": result.requires_specialist,
        "specialist_name": result.specialist_name,
        "specialist_reason": result.specialist_reason,
        "status": "classified",
    }
