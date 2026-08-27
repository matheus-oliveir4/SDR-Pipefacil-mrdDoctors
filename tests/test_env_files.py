from __future__ import annotations

import re
from pathlib import Path

from app.core.agent_config import ENVIRONMENT_OVERRIDE_DEFAULT_FIELDS
from app.core.agent_config_generated import AGENT_DEFAULTS
from app.core.config import Settings

ENV_FILES = (
    Path(".env.example"),
    Path(".env.dev"),
    Path(".env.staging"),
    Path(".env.prod"),
)
ENV_KEY_PATTERN = re.compile(r"^#?\s*([A-Z0-9_]+)=")


def _env_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text().splitlines():
        match = ENV_KEY_PATTERN.match(line)
        if match:
            keys.add(match.group(1))
    return keys


def test_versioned_env_files_document_all_settings_keys() -> None:
    universal_agent_keys = {
        field_name.upper()
        for field_name in AGENT_DEFAULTS
        if field_name not in ENVIRONMENT_OVERRIDE_DEFAULT_FIELDS
    }
    expected_keys = {
        field_name.upper() for field_name in Settings.model_fields
    } - universal_agent_keys

    for env_file in ENV_FILES:
        missing_keys = expected_keys - _env_keys(env_file)
        assert missing_keys == set(), f"{env_file} is missing: {sorted(missing_keys)}"


def test_versioned_env_files_do_not_duplicate_universal_agent_defaults() -> None:
    universal_agent_keys = {
        field_name.upper()
        for field_name in AGENT_DEFAULTS
        if field_name not in ENVIRONMENT_OVERRIDE_DEFAULT_FIELDS
    }

    for env_file in ENV_FILES:
        duplicated_keys = universal_agent_keys & _env_keys(env_file)
        assert duplicated_keys == set(), (
            f"{env_file} still duplicates universal agent defaults: {sorted(duplicated_keys)}"
        )
