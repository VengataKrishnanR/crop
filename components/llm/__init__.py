"""LLM component — SDK-based and REST-based model factories."""

from .embeddings import AzureEmbeddingsClient, EmbeddingUsage, EmbeddingsResult, build_embeddings_client
from .llm import build_generate_config, build_model
from .rest_llm import (
    build_azure_rest_model,
    build_model_for_env,
    build_openai_direct_model,
    build_rest_model,
    build_vertex_ai_rest_model,
    OpenAiDirectLlm,
)
from .stub_llm import build_stub_model, StubLlm
from .settings import ApigeeSettings, load_settings

__all__ = [
    "build_model",
    "build_generate_config",
    "build_model_for_env",
    "build_openai_direct_model",
    "build_rest_model",
    "build_vertex_ai_rest_model",
    "build_azure_rest_model",
    "build_stub_model",
    "OpenAiDirectLlm",
    "StubLlm",
    "AzureEmbeddingsClient",
    "EmbeddingsResult",
    "EmbeddingUsage",
    "build_embeddings_client",
    "ApigeeSettings",
    "load_settings",
]
