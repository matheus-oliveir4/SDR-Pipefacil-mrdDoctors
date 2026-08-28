import operator
from typing import Annotated, Any, Literal, NotRequired

from langchain_core.messages import BaseMessage
from typing_extensions import TypedDict

IntentType = Literal["greeting", "question", "request", "fallback"]
QualificationCriterionStatus = Literal["confirmed", "missing", "contradicted"]
LeadQualificationStatus = Literal["qualifying", "qualified", "not_qualified"]
LeadProfileType = Literal[
    "retailer_reseller",
    "healthcare_professional",
    "uniforms_business",
    "other",
    "unknown",
]
QualificationCriterionName = Literal[
    "segment_fit",
    "real_need",
    "purchase_intent",
    "plausible_plan",
    "decision_access",
]


class QualificationCriterion(TypedDict):
    status: QualificationCriterionStatus
    evidence: str | None


class LeadQualification(TypedDict):
    status: LeadQualificationStatus
    profile: LeadProfileType
    criteria: dict[QualificationCriterionName, QualificationCriterion]
    missing_criteria: list[QualificationCriterionName]
    contradicted_criteria: list[QualificationCriterionName]
    next_question: str | None
    reason: str


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]
    resume_context: NotRequired[str]
    latest_user_message: NotRequired[str]
    intent: NotRequired[IntentType]
    intent_reason: NotRequired[str]
    lead_qualification: NotRequired[LeadQualification]
    requires_specialist: NotRequired[bool]
    specialist_name: NotRequired[str | None]
    specialist_reason: NotRequired[str | None]
    specialist_status: NotRequired[str | None]
    specialist_result: NotRequired[dict[str, Any] | None]
    response_text: NotRequired[str]
    response_media: NotRequired[list[dict[str, Any]]]
    response_audio: NotRequired[dict[str, Any] | None]
    status: NotRequired[str]
