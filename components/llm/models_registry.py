"""
DHL GenAI Gateway — Model Registry loader.

Reads models.prod.yaml or models.test.yaml depending on APIGEE_ENVIRONMENT.

Env vars:
    APIGEE_ENVIRONMENT – "production" (default) | "testing"

Usage:
    from .models_registry import get_model_info, list_models, Provider, ModelType
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

_REGISTRY_DIR = Path(__file__).parent

_ENV_FILES: dict[str, str] = {
    "production": "models.prod.yaml",
    "testing": "models.test.yaml",
}


class Provider(str, Enum):
    VERTEX_AI = "vertex_ai"
    AZURE_OPENAI = "azure_openai"


class ModelType(str, Enum):
    CHAT = "chat"
    EMBEDDING = "embedding"


@dataclass(frozen=True)
class ModelInfo:
    deployment_id: str
    provider: Provider
    model_type: ModelType
    supports_streaming: bool = True
    supports_tools: bool = False
    supports_vision: bool = False
    context_window: int | None = None


def _load_registry() -> dict[str, ModelInfo]:
    env = os.getenv("APIGEE_ENVIRONMENT", "production").lower()
    filename = _ENV_FILES.get(env)
    if filename is None:
        raise ValueError(
            f"Unknown APIGEE_ENVIRONMENT '{env}'. "
            f"Must be one of: {', '.join(_ENV_FILES)}"
        )
    registry_path = _REGISTRY_DIR / filename
    with registry_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return {
        entry["deployment_id"]: ModelInfo(
            deployment_id=entry["deployment_id"],
            provider=Provider(entry["provider"]),
            model_type=ModelType(entry["model_type"]),
            supports_streaming=entry.get("supports_streaming", True),
            supports_tools=entry.get("supports_tools", False),
            supports_vision=entry.get("supports_vision", False),
            context_window=entry.get("context_window", None),
        )
        for entry in data["models"]
    }


# Loaded once at import time — reflects the current APIGEE_ENVIRONMENT.
SUPPORTED_MODELS: dict[str, ModelInfo] = _load_registry()


def get_model_info(deployment_id: str) -> ModelInfo:
    """Return ModelInfo for a deployment ID, raising ValueError if unknown."""
    info = SUPPORTED_MODELS.get(deployment_id)
    if info is None:
        supported = ", ".join(sorted(SUPPORTED_MODELS))
        raise ValueError(
            f"Unknown deployment ID '{deployment_id}' for environment "
            f"'{os.getenv('APIGEE_ENVIRONMENT', 'production')}'.\n"
            f"Supported models: {supported}"
        )
    return info


def list_models(
    provider: Provider | None = None,
    model_type: ModelType | None = None,
) -> list[ModelInfo]:
    """Return all models, optionally filtered by provider and/or model_type."""
    return [
        m for m in SUPPORTED_MODELS.values()
        if (provider is None or m.provider == provider)
        and (model_type is None or m.model_type == model_type)
    ]
