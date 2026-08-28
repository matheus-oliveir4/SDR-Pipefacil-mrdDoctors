from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agent.chains import build_qualification_chain, invoke_with_temperature_fallback
from app.agent.messages import latest_user_message, serialize_messages
from app.agent.state import (
    AgentState,
    LeadQualificationStatus,
    QualificationCriterionName,
)

_CRITERION_NAMES: tuple[QualificationCriterionName, ...] = (
    "segment_fit",
    "real_need",
    "purchase_intent",
    "plausible_plan",
    "decision_access",
)
_FALLBACK_QUESTIONS: dict[QualificationCriterionName, str] = {
    "segment_fit": "Você atua com fardamentos, saúde ou estética?",
    "real_need": "Qual necessidade de fardamentos ou scrubs você precisa atender agora?",
    "purchase_intent": "Você está buscando comprar agora ou planejando uma reposição?",
    "plausible_plan": "Você já tem um prazo, orçamento ou planejamento para essa compra?",
    "decision_access": "Você decide essa compra ou pode indicar quem participa da decisão?",
}


def _build_qualification_chain(*, use_custom_temperature: bool = True):
    return build_qualification_chain(use_custom_temperature=use_custom_temperature)


def _derive_status(criteria: dict[str, dict[str, str | None]]) -> LeadQualificationStatus:
    statuses = [criteria[name]["status"] for name in _CRITERION_NAMES]
    if all(status == "confirmed" for status in statuses):
        return "qualified"
    if any(status == "contradicted" for status in statuses):
        return "not_qualified"
    return "qualifying"


def qualify_lead(
    state: AgentState,
    config: RunnableConfig = None,
) -> dict[str, Any]:
    latest_message = state.get("latest_user_message") or latest_user_message(state)
    result = invoke_with_temperature_fallback(
        _build_qualification_chain,
        {
            "latest_user_message": latest_message,
            "conversation_history": serialize_messages(list(state.get("messages", []))),
        },
        config=config,
    )
    criteria = {
        name: getattr(result, name).model_dump()
        for name in _CRITERION_NAMES
    }
    missing_criteria = [
        name for name in _CRITERION_NAMES if criteria[name]["status"] == "missing"
    ]
    contradicted_criteria = [
        name for name in _CRITERION_NAMES if criteria[name]["status"] == "contradicted"
    ]
    status = _derive_status(criteria)
    next_question = None
    if status == "qualifying" and missing_criteria:
        next_question = (result.next_question or "").strip()
        if not next_question:
            next_question = _FALLBACK_QUESTIONS[missing_criteria[0]]

    return {
        "lead_qualification": {
            "status": status,
            "profile": result.profile,
            "criteria": criteria,
            "missing_criteria": missing_criteria,
            "contradicted_criteria": contradicted_criteria,
            "next_question": next_question,
            "reason": result.reason,
        }
    }
