from __future__ import annotations

from app.agent.chains.llm import get_chat_model
from app.agent.chains.schemas import LeadQualificationAssessment
from app.agent.prompts import get_qualification_prompt_template


def build_qualification_chain(*, use_custom_temperature: bool = True):
    _, prompt_template = get_qualification_prompt_template()
    model = get_chat_model(temperature=0 if use_custom_temperature else None)
    return prompt_template | model.with_structured_output(LeadQualificationAssessment)
