from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.state import (
    IntentType,
    LeadProfileType,
    QualificationCriterionStatus,
)


class IntentClassification(BaseModel):
    intent: IntentType
    reason: str = Field(min_length=1)
    requires_specialist: bool = False
    specialist_name: str | None = None
    specialist_reason: str | None = None


class QualificationCriterionAssessment(BaseModel):
    status: QualificationCriterionStatus
    evidence: str | None = Field(
        default=None,
        max_length=500,
        description="Short evidence grounded in the conversation; null when missing.",
    )


class LeadQualificationAssessment(BaseModel):
    profile: LeadProfileType
    segment_fit: QualificationCriterionAssessment
    real_need: QualificationCriterionAssessment
    purchase_intent: QualificationCriterionAssessment
    plausible_plan: QualificationCriterionAssessment
    decision_access: QualificationCriterionAssessment
    next_question: str | None = Field(
        default=None,
        max_length=300,
        description="One concise question for the highest-priority missing criterion.",
    )
    reason: str = Field(min_length=1, max_length=500)


class OutboundMediaChoice(BaseModel):
    media_id: str = Field(min_length=1)
    caption: str | None = None
    reason: str = Field(min_length=1)


class GeneratedAudioChoice(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=1600,
        description=("Spoken explanation only. Exact or copyable facts belong in response_text."),
    )
    reason: str = Field(
        min_length=1,
        description="Why spoken audio is more useful than text for this part of the reply.",
    )


class AgentResponsePlan(BaseModel):
    response_text: str = Field(
        min_length=1,
        description=(
            "WhatsApp text reply, including all exact, scannable, or copyable information."
        ),
    )
    media_choices: list[OutboundMediaChoice] = Field(default_factory=list)
    generated_audio: GeneratedAudioChoice | None = Field(
        default=None,
        description=(
            "Optional spoken explanation. Leave empty for text-only replies; combine with "
            "response_text for hybrid replies."
        ),
    )
