from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_validator_module():
    path = Path("scripts/validate_golden_dataset.py")
    spec = importlib.util.spec_from_file_location("validate_golden_dataset", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_golden_dataset_examples_are_valid() -> None:
    validator = _load_validator_module()

    errors = validator.validate_file(Path("datasets/golden/examples.jsonl"))

    assert errors == []


def test_golden_dataset_schema_documents_required_contract() -> None:
    schema = json.loads(Path("datasets/golden/schema.json").read_text())

    assert schema["required"] == [
        "id",
        "version",
        "status",
        "source",
        "scenario",
        "cut",
        "input",
        "expected",
        "evaluation",
        "metadata",
    ]
    assert set(schema["properties"]["status"]["enum"]) == {"candidate", "approved", "deprecated"}
    assert "messages_so_far" in schema["properties"]["input"]["properties"]
