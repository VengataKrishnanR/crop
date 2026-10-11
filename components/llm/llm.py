"""
LLM factory for the CCRE onboarding agent.

All calls go through the DHL Apigee proxy, which exposes two provider paths:
  - Vertex AI     : POST {APIGEE_PROXY_URL}/vertexai/v1/projects/.../models/{id}:generateContent
  - Azure OpenAI  : POST {APIGEE_PROXY_URL}/openai/deployments/{id}/chat/completions

build_model() auto-routes to the correct provider by looking up the deployment
ID in the model registry (models.prod.yaml / models.test.yaml).

Authentication for both paths uses Bearer token:
    Authorization: Bearer {APIGEE_API_KEY}

The proxy validates this token and calls the real backend with its own
service account — no GCP Application Default Credentials are required here.

Env vars:
    APIGEE_API_KEY       – DHL Apigee API key
    APIGEE_PROXY_URL     – Base proxy URL, e.g. https://apihub-sandbox.dhl.com/genai-test
    APIGEE_DEFAULT_VERTEX_MODEL    – Default Vertex AI deployment ID, e.g. gemini-2.5-flash
    APIGEE_DEFAULT_AZURE_OPENAI_MODEL – Default Azure OpenAI deployment ID, e.g. gpt-5-mini-2025-08-07-eudz
    APIGEE_ENVIRONMENT   – "production" (default) | "testing"
    AZURE_API_VERSION    – Azure OpenAI API version (default: 2024-10-21)
"""

from __future__ import annotations

import os
from functools import cached_property
from typing import Any

import google.auth.credentials
from google.adk.models.apigee_llm import ApigeeLlm
from google.genai import Client, types
from pydantic import PrivateAttr

from .models_registry import Provider, get_model_info

# ApigeeLlm.__init__ validates these for Vertex AI models; dummy values are
# intentional — the proxy uses its own GCP project/location internally.
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "apigee-proxy")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")

_DEFAULT_AZURE_API_VERSION = "2024-10-21"


class _ApigeeKeyCredentials(google.auth.credentials.Credentials):
    """Credential shim that uses the Apigee API key as the Bearer token.

    The DHL Apigee proxy accepts ``Authorization: Bearer {APIGEE_API_KEY}``
    and then calls the real Google backend with its own service account.
    GCP Application Default Credentials are not required on the client side.
    """

    def __init__(self, api_key: str) -> None:
        super().__init__()
        self.token = api_key

    def refresh(self, request: Any) -> None:  # type: ignore[override]
        pass  # token never expires; proxy handles real auth

    @property
    def valid(self) -> bool:
        return True

    @property
    def expired(self) -> bool:
        return False


class _DhlApigeeLlm(ApigeeLlm):
    """ApigeeLlm variant that injects the Apigee API key as the Bearer credential.

    Overrides ``api_client`` so the underlying ``google.genai.Client`` uses
    :class:`_ApigeeKeyCredentials` instead of GCP Application Default
    Credentials, bypassing the need for ``gcloud auth`` or a service account key.
    """

    _apigee_api_key: str = PrivateAttr()

    def __init__(self, *, apigee_api_key: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._apigee_api_key = apigee_api_key

    @cached_property  # type: ignore[override]
    def api_client(self) -> Any:
        extra_http: dict[str, Any] = {}
        if self._api_version:
            extra_http["api_version"] = self._api_version

        http_options = types.HttpOptions(
            base_url=self._proxy_url,
            headers=self._merge_tracking_headers(self._custom_headers),
            retry_options=self.retry_options,
            **extra_http,
        )

        client_kwargs: dict[str, Any] = {"vertexai": self._isvertexai}
        if self._isvertexai:
            client_kwargs["project"] = self._project
            client_kwargs["location"] = self._location
            client_kwargs["credentials"] = _ApigeeKeyCredentials(
                self._apigee_api_key
            )

        return Client(http_options=http_options, **client_kwargs)


def build_model(deployment_id: str | None = None) -> ApigeeLlm:
    """Return a configured ApigeeLlm, auto-routing to Vertex AI or Azure OpenAI.

    Args:
        deployment_id: Deployment ID from the model registry. Falls back to
                  APIGEE_DEFAULT_VERTEX_MODEL, then APIGEE_DEFAULT_AZURE_OPENAI_MODEL.

    Raises:
        ValueError: If the deployment ID is not found in the active registry.
    """
    api_key = os.environ["APIGEE_API_KEY"]
    proxy_base = os.environ["APIGEE_PROXY_URL"]
    deployment_id = (
        deployment_id
        or os.environ.get("APIGEE_DEFAULT_VERTEX_MODEL")
        or os.environ["APIGEE_DEFAULT_AZURE_OPENAI_MODEL"]
    )

    info = get_model_info(deployment_id)
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

    if info.provider == Provider.VERTEX_AI:
        # _DhlApigeeLlm injects the Apigee key as a Bearer credential so that
        # google.genai.Client does not attempt GCP Application Default Credentials.
        return _DhlApigeeLlm(
            apigee_api_key=api_key,
            model=f"apigee/vertex_ai/v1/{deployment_id}",
            proxy_url=f"{proxy_base}/vertexai",
            custom_headers=headers,
        )

    # Azure OpenAI
    api_version = os.getenv("AZURE_API_VERSION", _DEFAULT_AZURE_API_VERSION)
    return ApigeeLlm(
        model=f"apigee/openai/{deployment_id}",
        proxy_url=f"{proxy_base}/openai/deployments/{deployment_id}/chat/completions",
        custom_headers={**headers, "api-version": api_version},
    )

# Enhancement 3: Tuning LLM response style via thinking_level and temperature parameters in the generate config.
def build_generate_config(
    *,
    temperature: float = 0.5,
    thinking_level: types.ThinkingLevel = types.ThinkingLevel.MINIMAL,
    include_thoughts: bool = True,
) -> types.GenerateContentConfig:
    """Return a GenerateContentConfig. Adjust temperature / thinking_level as needed."""
    return types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(
            # include_thoughts=include_thoughts,
            thinking_level=thinking_level,
        ),
        temperature=temperature,
    )
