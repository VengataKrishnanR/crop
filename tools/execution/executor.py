"""Pluggable UAT executors — where the request is actually sent.

Normally the CCRE team picks an **endpoint configured by the admin** in the UI
(:class:`EndpointExecutor` — the onboarded CRMS test-suite sender). Without one,
the executor is selected by ``CCRE_UAT_EXECUTOR``:

* ``mock`` (default) — the in-process mock CCRE (:mod:`tools.execution.mock_ccre`).
* ``http`` — POST the payload to ``CCRE_UAT_ENDPOINT`` with optional
  ``CCRE_UAT_AUTH_HEADER`` ("Header-Name: value") and ``CCRE_UAT_TIMEOUT_SECONDS``.
* ``package.module:ClassName`` — your own execution code. The class is built
  with no arguments and must provide ``execute(payload: dict) -> dict`` returning
  ``{"status": int, "body": <json or text>}``. See ``tools/execution/custom/``.
"""
from __future__ import annotations

import importlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from .mock_ccre import evaluate_shipment


@dataclass
class ExecutionOutcome:
    status: Optional[int]
    body: Any
    latency_ms: float
    error: Optional[str] = None


class Executor:
    name = "base"

    def execute(self, payload: dict[str, Any]) -> ExecutionOutcome:  # pragma: no cover - interface
        raise NotImplementedError


class MockExecutor(Executor):
    name = "mock"

    def __init__(self, session: Session, rule_set_id: str) -> None:
        self.session = session
        self.rule_set_id = rule_set_id

    def execute(self, payload: dict[str, Any]) -> ExecutionOutcome:
        started = time.perf_counter()
        try:
            body = evaluate_shipment(self.session, payload, self.rule_set_id)
            return ExecutionOutcome(200, body, (time.perf_counter() - started) * 1000)
        except Exception as exc:  # noqa: BLE001 — recorded as an ERROR result
            return ExecutionOutcome(None, None, (time.perf_counter() - started) * 1000, str(exc))


class HttpExecutor(Executor):
    name = "http"

    def __init__(self, url: str, headers: Optional[dict[str, str]] = None, timeout: float = 30.0) -> None:
        self.url = url
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.timeout = timeout

    def execute(self, payload: dict[str, Any]) -> ExecutionOutcome:
        started = time.perf_counter()
        try:
            resp = httpx.post(self.url, json=payload, headers=self.headers, timeout=self.timeout)
            try:
                body: Any = resp.json()
            except (ValueError, json.JSONDecodeError):
                body = resp.text
            return ExecutionOutcome(resp.status_code, body, (time.perf_counter() - started) * 1000)
        except httpx.HTTPError as exc:
            return ExecutionOutcome(None, None, (time.perf_counter() - started) * 1000,
                                    f"{type(exc).__name__}: {exc}")


#: Test hook: an ``httpx`` transport used instead of the network (tests only).
_TRANSPORT: Optional[httpx.BaseTransport] = None


class EndpointExecutor(Executor):
    """Calls an Admin-configured endpoint — the onboarded CRMS test-suite sender.

    Port of the suite's ``makeApiRequest``: method + JSON body + configured headers
    (credential header from the encrypted store, ``Content-Type`` by default), and
    hosts under ``.dhl.com`` bypass the corporate proxy (``no_proxy='.dhl.com'``).
    """

    def __init__(self, name: str, url: str, method: str = "POST", headers: Optional[dict[str, str]] = None,
                 timeout: float = 30.0) -> None:
        self.name = name
        self.url = url
        self.method = (method or "POST").upper()
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.timeout = timeout

    @classmethod
    def from_endpoint(cls, endpoint: Any) -> "EndpointExecutor":
        from tools.core.security import decrypt_secret

        headers = dict(endpoint.extra_headers or {})
        secret = decrypt_secret(endpoint.secret_enc)
        if endpoint.secret_enc and secret is None:
            raise ValueError(f"The credential for endpoint '{endpoint.name}' can no longer be read; "
                             "an admin must re-enter it.")
        if endpoint.auth_header and secret:
            headers[endpoint.auth_header] = secret
        return cls(endpoint.name, endpoint.url, endpoint.method, headers, endpoint.timeout_seconds or 30.0)

    def _client(self) -> httpx.Client:
        host = httpx.URL(self.url).host or ""
        # The suite bypasses the corporate proxy for DHL-internal hosts.
        trust_env = not host.endswith(".dhl.com")
        return httpx.Client(timeout=self.timeout, trust_env=trust_env, transport=_TRANSPORT)

    def execute(self, payload: dict[str, Any]) -> ExecutionOutcome:
        started = time.perf_counter()
        try:
            with self._client() as client:
                send_body = self.method in {"POST", "PUT", "PATCH"}
                resp = client.request(self.method, self.url, headers=self.headers,
                                      content=json.dumps(payload) if send_body else None)
            try:
                body: Any = resp.json()
            except (ValueError, json.JSONDecodeError):
                body = resp.text
            return ExecutionOutcome(resp.status_code, body, (time.perf_counter() - started) * 1000)
        except httpx.HTTPError as exc:
            return ExecutionOutcome(None, None, (time.perf_counter() - started) * 1000,
                                    f"{type(exc).__name__}: {exc}")


class CustomExecutor(Executor):
    """Wraps user-supplied execution code that follows the documented contract."""

    def __init__(self, target: str) -> None:
        module_name, _, class_name = target.partition(":")
        if not class_name:
            raise ValueError("CCRE_UAT_EXECUTOR must look like 'package.module:ClassName'.")
        self.impl = getattr(importlib.import_module(module_name), class_name)()
        self.name = target

    def execute(self, payload: dict[str, Any]) -> ExecutionOutcome:
        started = time.perf_counter()
        try:
            out = self.impl.execute(payload)
            return ExecutionOutcome(out.get("status"), out.get("body"),
                                    (time.perf_counter() - started) * 1000, out.get("error"))
        except Exception as exc:  # noqa: BLE001 — recorded as an ERROR result
            return ExecutionOutcome(None, None, (time.perf_counter() - started) * 1000,
                                    f"{type(exc).__name__}: {exc}")


def _auth_header() -> dict[str, str]:
    raw = os.getenv("CCRE_UAT_AUTH_HEADER", "")
    if ":" not in raw:
        return {}
    name, value = raw.split(":", 1)
    return {name.strip(): value.strip()}


def build_executor(session: Session, rule_set_id: str, endpoint: Any = None) -> Executor:
    """The Admin-configured ``endpoint`` when given; otherwise ``CCRE_UAT_EXECUTOR`` (default mock)."""
    if endpoint is not None:
        return EndpointExecutor.from_endpoint(endpoint)
    mode = os.getenv("CCRE_UAT_EXECUTOR", "mock").strip()
    if mode in ("", "mock"):
        return MockExecutor(session, rule_set_id)
    if mode == "http":
        url = os.getenv("CCRE_UAT_ENDPOINT", "")
        if not url:
            raise ValueError("CCRE_UAT_EXECUTOR=http needs CCRE_UAT_ENDPOINT.")
        return HttpExecutor(url, _auth_header(), float(os.getenv("CCRE_UAT_TIMEOUT_SECONDS", "30")))
    return CustomExecutor(mode)
