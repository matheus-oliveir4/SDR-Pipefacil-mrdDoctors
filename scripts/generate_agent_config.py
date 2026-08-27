from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.core.agent_config import agent_defaults, load_agent_config

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".agent.json"
TARGET = ROOT / "src/app/core/agent_config_generated.py"


def _python_literal(value: Any, *, indent: int = 0) -> str:
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = ["{"]
        child_indent = indent + 4
        for key, child in value.items():
            lines.append(
                f"{' ' * child_indent}{_python_literal(str(key))}: "
                f"{_python_literal(child, indent=child_indent)},"
            )
        lines.append(f"{' ' * indent}}}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = ["["]
        child_indent = indent + 4
        for child in value:
            lines.append(f"{' ' * child_indent}{_python_literal(child, indent=child_indent)},")
        lines.append(f"{' ' * indent}]")
        return "\n".join(lines)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    return repr(value)


def rendered_module() -> str:
    config = load_agent_config(SOURCE)
    defaults = _python_literal(agent_defaults(config))
    return (
        '"""Generated from .agent.json. Do not edit manually."""\n\n'
        f"AGENT_DEFAULTS: dict[str, object] = {defaults}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and generate agent defaults.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the JSON and fail if the generated module is stale.",
    )
    args = parser.parse_args()

    rendered = rendered_module()
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != rendered:
            print(f"Generated agent config is stale: {TARGET}")
            return 1
        print("Agent config is valid and generated module is current.")
        return 0

    if TARGET.exists() and TARGET.read_text(encoding="utf-8") == rendered:
        print(f"Generated module is current: {TARGET.relative_to(ROOT)}.")
        return 0

    TARGET.write_text(rendered, encoding="utf-8")
    print(f"Generated {TARGET.relative_to(ROOT)} from {SOURCE.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
