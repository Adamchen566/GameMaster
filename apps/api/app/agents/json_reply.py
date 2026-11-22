"""For providers that cannot be held to a JSON schema: ask in words, read tolerantly.

The Claude API guarantees the shape of its answer. DeepSeek's JSON mode and a
command-line client only promise "some JSON", sometimes wrapped in a code block
or a sentence. Whatever comes back is still only a proposal: the contract and
the rules engine check it like any other answer.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from app.agents.model import ModelBadOutput


def schema_instructions(schema: Mapping[str, Any]) -> str:
    """Spell the schema out, for a model that is not constrained by it."""
    return (
        "Answer with exactly one JSON object and nothing else: no code block, no commentary. "
        "It must have every one of these fields, with these types:\n"
        f"{json.dumps(schema.get('properties', {}), ensure_ascii=False, sort_keys=True)}"
    )


def parse_json_object(text: str) -> dict[str, Any]:
    """The JSON object in `text`, ignoring anything around it."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ModelBadOutput("The answer contained no JSON object.")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        raise ModelBadOutput("The answer was not valid JSON.") from error
    if not isinstance(data, dict):
        raise ModelBadOutput("The answer must be a JSON object.")
    return data
