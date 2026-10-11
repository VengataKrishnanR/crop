"""Smoke tests — import health and basic objects.

These must pass on any machine with the requirements installed, with no
reference artifacts, no network and no API key.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.smoke


def test_json_utils_importable() -> None:
    from server.json_utils import AgentInvocationError, extract_json

    assert callable(extract_json)
    assert issubclass(AgentInvocationError, RuntimeError)


def test_extract_json_takes_the_last_fenced_block() -> None:
    from server.json_utils import extract_json

    assert extract_json('{"result": 42}')["result"] == 42
    text = 'thinking...\n```json\n{"ok": false}\n```\nfinal:\n```json\n{"ok": true}\n```'
    assert extract_json(text)["ok"] is True


def test_domain_core_importable() -> None:
    from tools.core import export, grammar, models  # noqa: F401
    from tools.ingestion import ingest_package, ingest_workbook
    from tools.validation import available_checks

    assert callable(ingest_package) and callable(ingest_workbook)
    assert len(available_checks()) >= 16


def test_workflow_state_machine_importable() -> None:
    from tools.workflow import TRANSITIONS, State

    assert State.DRAFT.value == "DRAFT"
    assert len(TRANSITIONS) > 10


def test_llm_component_selects_stub_mode() -> None:
    from components.llm import build_model_for_env

    assert type(build_model_for_env()).__name__ == "StubLlm"


def test_logging_and_tracing_components_apply() -> None:
    from components.logging import configure_logging
    from components.tracing import apply_tracing_patch

    configure_logging()
    apply_tracing_patch()
    apply_tracing_patch()  # idempotent


def test_settings_point_at_the_sibling_reference_folder() -> None:
    import os

    from tools.core.config import REPO_ROOT, SETTINGS

    if "CCRE_REFERENCE_DIR" not in os.environ:
        assert SETTINGS.reference_dir == REPO_ROOT.parent / "Reference"


def test_server_app_importable() -> None:
    from server.app import app

    paths = set(app.openapi()["paths"]) | {getattr(r, "path", "") for r in app.routes}
    assert "/api/health" in paths
    assert "/api/run" in paths
    assert "/" in paths
