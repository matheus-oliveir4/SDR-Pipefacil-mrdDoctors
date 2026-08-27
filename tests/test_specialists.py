import json

from app.agent.specialists import (
    OpenAISpecialistRunner,
    SpecialistRequest,
    build_test_specialist_agent,
)
from app.core.config import Settings


def test_specialist_runner_returns_failed_for_unknown_specialist() -> None:
    result = OpenAISpecialistRunner(settings=Settings(_env_file=None)).run(
        specialist_name="missing",
        request=SpecialistRequest(objective="Run test.", latest_user_message="oi"),
    )

    assert result.status == "failed"
    assert result.error_code == "specialist_unknown"


def test_specialist_runner_requires_openai_api_key() -> None:
    result = OpenAISpecialistRunner(settings=Settings(_env_file=None, openai_api_key=None)).run(
        specialist_name="test_specialist",
        request=SpecialistRequest(objective="Run test.", latest_user_message="oi"),
    )

    assert result.status == "failed"
    assert result.error_code == "openai_api_key_missing"


def test_specialist_runner_preserves_request_objective_in_input() -> None:
    request = SpecialistRequest(
        objective="Objective from LangGraph.",
        latest_user_message="Mensagem",
    )

    payload = json.loads(
        OpenAISpecialistRunner._format_input("Default specialist objective.", request)
    )

    assert payload["objective"] == "Objective from LangGraph."
    assert payload["specialist_definition_objective"] == "Default specialist objective."


def test_test_specialist_uses_non_strict_output_schema_for_flexible_fields() -> None:
    agent = build_test_specialist_agent(Settings(_env_file=None))

    assert agent.output_type is not None
    assert agent.output_type.is_strict_json_schema() is False
