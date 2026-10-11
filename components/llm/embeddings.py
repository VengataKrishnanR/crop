"""
REST-based embeddings client for the DHL GenAI Gateway (Azure OpenAI).

  POST {APIGEE_PROXY_URL}/openai/deployments/{deployment_id}/embeddings
       ?api-version={api_version}
  Authorization: Bearer {APIGEE_API_KEY}

Public API:
  EmbeddingsResult         — result dataclass
  AzureEmbeddingsClient    — async embeddings client class
  build_embeddings_client  — factory function

Env vars:
  APIGEE_API_KEY                   – Bearer token (required)
  APIGEE_PROXY_URL                 – Base URL (required)
  APIGEE_DEFAULT_EMBEDDING_MODEL   – Fallback embedding deployment ID
  AZURE_API_VERSION                – Azure API version (default: 2024-10-21)
  APIGEE_TIMEOUT_SECONDS           – HTTP timeout in seconds (default: 60.0)
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import httpx

from .models_registry import ModelType, Provider, get_model_info
from .settings import load_settings

_DEFAULT_API_VERSION = "2024-10-21"
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


@dataclass
class EmbeddingUsage:
    prompt_tokens: int
    total_tokens: int


@dataclass
class EmbeddingsResult:
    """Result returned by AzureEmbeddingsClient.embed()."""
    texts: list[str]
    embeddings: list[list[float]]
    model: str
    usage: EmbeddingUsage | None = None


class AzureEmbeddingsClient:
    """Async client for Azure OpenAI text embeddings via the DHL Apigee proxy.

    Usage:
        client = AzureEmbeddingsClient(proxy_url=..., api_key=..., deployment_id=..., api_version=...)
        result = await client.embed(["Hello, world!", "How are you?"])
    """

    def __init__(
        self,
        proxy_url: str,
        api_key: str,
        deployment_id: str,
        api_version: str = _DEFAULT_API_VERSION,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        retry_initial_delay: float = 1.0,
    ) -> None:
        self.proxy_url = proxy_url
        self.api_key = api_key
        self.deployment_id = deployment_id
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_initial_delay = retry_initial_delay

    async def embed(self, texts: str | list[str]) -> EmbeddingsResult:
        """Embed one or more texts, returning an EmbeddingsResult.

        Args:
            texts: A single string or list of strings to embed.

        Returns:
            EmbeddingsResult with embeddings in the same order as input.

        Raises:
            RuntimeError: If the API returns a non-retryable error after all retries.
        """
        if isinstance(texts, str):
            texts = [texts]

        url = (
            f"{self.proxy_url}/openai/deployments/{self.deployment_id}"
            f"/embeddings?api-version={self.api_version}"
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"input": texts, "model": self.deployment_id}

        delay = self.retry_initial_delay
        resp: httpx.Response | None = None
        for attempt in range(self.max_retries + 1):
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(url, json=payload, headers=headers)
            if resp.is_success:
                break
            if resp.status_code not in _RETRYABLE_STATUS_CODES or attempt == self.max_retries:
                break
            await asyncio.sleep(delay)
            delay *= 2

        assert resp is not None
        if not resp.is_success:
            raise RuntimeError(
                f"Embeddings request failed with status {resp.status_code}: {resp.text[:500]}"
            )

        data = resp.json()
        embeddings = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
        usage_raw = data.get("usage")
        usage = (
            EmbeddingUsage(
                prompt_tokens=usage_raw.get("prompt_tokens", 0),
                total_tokens=usage_raw.get("total_tokens", 0),
            )
            if usage_raw
            else None
        )
        return EmbeddingsResult(
            texts=texts,
            embeddings=embeddings,
            model=data.get("model", self.deployment_id),
            usage=usage,
        )


def build_embeddings_client(
    deployment_id: str | None = None,
    timeout_seconds: float | None = None,
) -> AzureEmbeddingsClient:
    """Return an AzureEmbeddingsClient for the given (or default) embedding deployment.

    Args:
        deployment_id: Embedding deployment ID. Falls back to APIGEE_DEFAULT_EMBEDDING_MODEL.
        timeout_seconds: HTTP timeout. Falls back to APIGEE_TIMEOUT_SECONDS env var (default: 60).

    Raises:
        ValueError: If the deployment ID is not an embedding model in the registry.
    """
    s = load_settings()
    if not s.api_key:
        raise KeyError("APIGEE_API_KEY")
    if not s.proxy_url:
        raise KeyError("APIGEE_PROXY_URL")
    resolved_id = deployment_id or s.default_embedding_model
    if not resolved_id:
        raise KeyError("APIGEE_DEFAULT_EMBEDDING_MODEL")
    timeout = timeout_seconds if timeout_seconds is not None else s.timeout_seconds

    info = get_model_info(resolved_id)
    if info.provider != Provider.AZURE_OPENAI or info.model_type != ModelType.EMBEDDING:
        raise ValueError(
            f"'{resolved_id}' is not an Azure OpenAI embedding model. "
            f"Got provider={info.provider.value}, model_type={info.model_type.value}."
        )

    return AzureEmbeddingsClient(
        proxy_url=s.proxy_url,
        api_key=s.api_key,
        deployment_id=resolved_id,
        api_version=s.azure_api_version,
        timeout_seconds=timeout,
    )
