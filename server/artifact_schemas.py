"""Validators for agent outputs.

Each validator parses the agent's JSON against its pydantic contract in
:mod:`tools.agents.schemas` and returns a plain JSON-safe dict. A raised
exception triggers the invoker's one repair retry, with the error fed back.
"""
from __future__ import annotations

from typing import Any

from tools.agents.schemas import (
    ChangeSet,
    FailureAnalysis,
    RequirementInterpretation,
    TestCaseSuite,
)


def _require_object(d: Any, name: str) -> dict:
    if not isinstance(d, dict):
        raise TypeError(f"{name} must be a JSON object, got {type(d).__name__}")
    return d


def validate_interpretation(d: Any) -> dict:
    return RequirementInterpretation.model_validate(
        _require_object(d, "RequirementInterpretation")
    ).model_dump(mode="json")


def validate_change_set(d: Any) -> dict:
    change_set = ChangeSet.model_validate(_require_object(d, "ChangeSet"))
    if not change_set.rules:
        raise ValueError("ChangeSet.rules must contain at least one proposed rule")
    return change_set.model_dump(mode="json")


def validate_test_suite(d: Any) -> dict:
    suite = TestCaseSuite.model_validate(_require_object(d, "TestCaseSuite"))
    if not suite.cases:
        raise ValueError("TestCaseSuite.cases must contain at least one case")
    return suite.model_dump(mode="json")


def validate_failure_analysis(d: Any) -> dict:
    return FailureAnalysis.model_validate(
        _require_object(d, "FailureAnalysis")
    ).model_dump(mode="json")
