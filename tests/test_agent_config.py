from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.agent_config import AgentConfig, agent_defaults, load_agent_config
from app.core.agent_config_generated import AGENT_DEFAULTS
from app.core.config import Settings

CONFIG_PATH = Path(".agent.json")


def _config_data() -> dict[str, object]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _load_generator_module():
    script_path = Path("scripts/generate_agent_config.py")
    spec = importlib.util.spec_from_file_location("generate_agent_config", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_config_rejects_unknown_fields() -> None:
    data = _config_data()
    data["unexpected"] = True

    with pytest.raises(ValidationError, match="unexpected"):
        AgentConfig.model_validate(data)


def test_agent_config_rejects_secrets_recursively() -> None:
    data = _config_data()
    data["openai"]["api_key"] = "must-not-be-here"  # type: ignore[index]

    with pytest.raises(ValidationError, match="Sensitive configuration key"):
        AgentConfig.model_validate(data)


def test_agent_config_rejects_invalid_audio_limits() -> None:
    data = _config_data()
    data["audio"]["auto_enabled"] = True  # type: ignore[index]
    data["audio"]["auto_min_chars"] = 1_201  # type: ignore[index]

    with pytest.raises(ValidationError, match="audio.auto_min_chars"):
        AgentConfig.model_validate(data)


def test_generated_defaults_match_validated_agent_config() -> None:
    config = load_agent_config(CONFIG_PATH)

    assert agent_defaults(config) == AGENT_DEFAULTS
    settings = Settings(_env_file=None)
    assert settings.app_name == "SDR Agent Template"
    assert settings.app_slug == "sdr-agent-template"
    assert settings.pipefacil_conversation_history_path == "/api/v1/messages"
    assert settings.generated_audio_storage_dir == ".runtime/generated-audio"
    assert settings.elevenlabs_voice_id == "RGymW84CSmfVugnA5tvA"
    assert settings.elevenlabs_output_format == "opus_48000_96"


def test_environment_and_explicit_values_override_generated_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "gpt-environment-override")

    environment_settings = Settings(_env_file=None)
    explicit_settings = Settings(_env_file=None, openai_model="gpt-explicit-override")

    assert environment_settings.openai_model == "gpt-environment-override"
    assert explicit_settings.openai_model == "gpt-explicit-override"


def test_agent_config_check_detects_stale_generated_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _load_generator_module()
    stale_target = tmp_path / "agent_config_generated.py"
    stale_target.write_text("stale\n", encoding="utf-8")
    monkeypatch.setattr(generator, "TARGET", stale_target)
    monkeypatch.setattr(sys, "argv", ["generate_agent_config.py", "--check"])

    assert generator.main() == 1
