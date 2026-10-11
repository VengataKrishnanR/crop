"""Prompt assembly for the CCRE sub-agents.

Each agent prompt is a markdown file under ``prompts/``. The shared house rules
(and, for agents that write or read condition expressions, the expression notes)
are prepended so every agent carries the hard rules even when it runs alone.
"""
from __future__ import annotations

from pathlib import Path

_PROMPTS = Path(__file__).parent / "prompts"


def load_prompt(name: str, *, expression_notes: bool = False) -> str:
    """Return the agent prompt ``prompts/<name>.md`` with the shared fragments prepended."""
    parts = [(_PROMPTS / f"{name}.md").read_text(encoding="utf-8").strip()]
    parts.append((_PROMPTS / "_house_rules.md").read_text(encoding="utf-8").strip())
    if expression_notes:
        parts.append((_PROMPTS / "_expression_notes.md").read_text(encoding="utf-8").strip())
    return "\n\n".join(parts) + "\n"
