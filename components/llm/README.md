# LLM Component

Provides REST-based LLM factories that connect to the DHL GenAI Gateway (Apigee proxy) without requiring GCP Application Default Credentials. Both providers authenticate exclusively via `Authorization: Bearer {APIGEE_API_KEY}`.

---

## Files

| File | Purpose |
|---|---|
| `rest_llm.py` | **Primary path.** `VertexAiRestLlm`, `AzureOpenAiRestLlm`, three LLM factory functions, and all payload/response helpers. |
| `embeddings.py` | `AzureEmbeddingsClient` and `build_embeddings_client()` factory for text embeddings (Azure OpenAI only). |
| `llm.py` | SDK-based fallback (`_DhlApigeeLlm`). Not used by `agent.py` by default but kept for compatibility. |
| `models_registry.py` | Loads `models.prod.yaml` or `models.test.yaml` at import time. Provides `get_model_info()`, `list_models()`, `ModelInfo`. |
| `models.prod.yaml` | **Source of truth** for all valid `deployment_id` values in production (33 models, with capability metadata). |
| `models.test.yaml` | Model overrides for `APIGEE_ENVIRONMENT=testing`. |

---

## Providers & URL Patterns

| Provider | Non-streaming URL | Streaming URL |
|---|---|---|
| Vertex AI | `{APIGEE_PROXY_URL}/vertexai/publishers/google/models/{id}:generateContent` | `.../:streamGenerateContent` |
| Azure OpenAI | `{APIGEE_PROXY_URL}/openai/deployments/{id}/chat/completions?api-version={ver}` | Same URL + `"stream": true` + `"stream_options": {"include_usage": true}` in body |

---

## Factory Functions

```python
from adk_skeleton.components.llm import (
    build_rest_model,
    build_vertex_ai_rest_model,
    build_azure_rest_model,
    build_embeddings_client,
)

# Auto-routing: looks up deployment_id in registry, picks the right provider
model = build_rest_model()
model = build_rest_model(deployment_id="gemini-2.5-flash")
model = build_rest_model(deployment_id="gpt-4o-2024-08-06-eudz", streaming=True)
model = build_rest_model(timeout_seconds=30.0)

# Explicit provider
model = build_vertex_ai_rest_model(deployment_id="gemini-2.5-flash")
model = build_azure_rest_model(deployment_id="gpt-4o-2024-08-06-eudz")

# Text embeddings (Azure OpenAI only)
client = build_embeddings_client(deployment_id="text-embedding-3-large-1")
result = await client.embed(["Hello", "World"])
# result.embeddings  → list[list[float]]
# result.usage.total_tokens
```

All LLM factories raise `ValueError` if `deployment_id` is not in the active registry.

---

## LLM Class Fields

Both `VertexAiRestLlm` and `AzureOpenAiRestLlm` share these Pydantic fields:

| Field | Default | Description |
|---|---|---|
| `streaming` | `False` | Enable SSE streaming |
| `max_retries` | `3` | Retry attempts on 429/5xx |
| `retry_initial_delay` | `1.0` | Initial backoff delay in seconds (doubles each retry) |
| `timeout_seconds` | `60.0` | HTTP request timeout |

---

## Capabilities (both providers are symmetric)

| Feature | Vertex AI | Azure OpenAI |
|---|---|---|
| Text generation | ✅ | ✅ |
| Streaming (SSE) | ✅ | ✅ |
| Tool / function calling (request + response) | ✅ | ✅ |
| Tool calls in streaming | ✅ | ✅ (accumulated from deltas) |
| Multi-modal: inline image (base64) | ✅ | ✅ |
| Multi-modal: file_data (GCS URI) | ✅ | — |
| `finish_reason` in response | ✅ | ✅ |
| `finish_reason` in streaming final event | ✅ | ✅ |
| `usage_metadata` in response | ✅ | ✅ |
| `usage_metadata` in streaming final event | ✅ | ✅ |
| Retry + exponential backoff (429/5xx) | ✅ | ✅ |
| `temperature`, `top_p`, `stop`, penalties, `seed` | ✅ | ✅ |
| `max_output_tokens` | ✅ | ✅ → `max_tokens` |
| `candidate_count` | ✅ | ✅ → `n` |
| `response_mime_type` (JSON mode) | ✅ | ✅ → `response_format` |
| `top_k` | ✅ | — (no OpenAI equivalent) |
| `thinking_config` | ✅ (Gemini 2.5) | — |

---

## Streaming Control (highest precedence first)

1. `stream=True` passed to `generate_content_async()` at call time (ADK-driven)
2. `streaming=True` passed to the factory function
3. `APIGEE_STREAMING_ENABLED=true` environment variable (default: `false`)

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `APIGEE_API_KEY` | ✅ | — | Bearer token for all requests |
| `APIGEE_PROXY_URL_PRODUCTION` | ✅* | — | Proxy base URL for the `production` environment |
| `APIGEE_PROXY_URL_TESTING` | ✅* | — | Proxy base URL for the `testing` environment |
| `APIGEE_PROXY_URL` | ✅* | — | Legacy fallback URL (used when env-specific var is absent) |
| `APIGEE_DEFAULT_VERTEX_MODEL` | ✅ | — | Default Vertex AI `deployment_id`, e.g. `gemini-2.5-flash` |
| `APIGEE_DEFAULT_AZURE_OPENAI_MODEL` | ✅ | — | Default Azure OpenAI `deployment_id`, e.g. `gpt-5-mini-2025-08-07-eudz` |
| `APIGEE_DEFAULT_EMBEDDING_MODEL` | ✅* | — | Default embedding `deployment_id` (*required only when using embeddings) |
| `AZURE_API_VERSION` | ❌ | `2024-10-21` | Azure API version query param |
| `APIGEE_ENVIRONMENT` | ❌ | `production` | `production` → `models.prod.yaml` + `APIGEE_PROXY_URL_PRODUCTION`; `testing` → `models.test.yaml` + `APIGEE_PROXY_URL_TESTING` |
| `APIGEE_STREAMING_ENABLED` | ❌ | `false` | Set `true` to enable streaming globally |
| `APIGEE_TIMEOUT_SECONDS` | ❌ | `60.0` | HTTP timeout in seconds for all providers |

> **URL resolution order:** `APIGEE_PROXY_URL_{ENVIRONMENT}` → `APIGEE_PROXY_URL` (legacy fallback). Set the env-specific vars; keep `APIGEE_PROXY_URL` only for backward-compatibility.

---

## Model Registry

`models.prod.yaml` is loaded once at import time into `SUPPORTED_MODELS`. Every factory call validates against it via `get_model_info(deployment_id)`.

Each model entry carries capability metadata:

```yaml
models:
  - deployment_id: gemini-2.5-flash
    provider: vertex_ai
    model_type: chat
    supports_streaming: true
    supports_tools: true
    supports_vision: true
    context_window: 1048576
```

**Adding a new model** requires only a YAML entry — no code change.

**Querying the registry:**

```python
from adk_skeleton.components.llm.models_registry import get_model_info, list_models, Provider, ModelType

info = get_model_info("gemini-2.5-flash")
# ModelInfo(deployment_id, provider, model_type, supports_streaming, supports_tools, supports_vision, context_window)

chat_models = list_models(provider=Provider.VERTEX_AI, model_type=ModelType.CHAT)
vision_models = [m for m in list_models() if m.supports_vision]
```

---

## Tests

```
tests/components/llm/
├── test_rest_llm.py         # ~300 tests: both LLM classes, streaming, retry, tools, multimodal, helpers, factories
├── test_embeddings.py       # ~25 tests: AzureEmbeddingsClient and build_embeddings_client
├── test_llm.py              # 16 tests: SDK-based path (_DhlApigeeLlm)
└── test_models_registry.py  # ~25 tests: YAML loading, capability fields, get_model_info, list_models
```

Tests mock `httpx.AsyncClient` at the boundary — they never hit the network. Use the `apigee_env` fixture from `tests/conftest.py`.
