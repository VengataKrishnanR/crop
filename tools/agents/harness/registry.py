"""The tool registry: the only way an agent reaches data.

Rules enforced here, in code rather than in prompts:

* **Read-only.** Registering a tool with ``read_only=False`` fails. There is no
  write path to case state, approvals, email, uploads or CCRE behind any tool.
* **Allow-lists.** Each tool names the agents that may call it;
  :meth:`ToolRegistry.get_tools_for` returns only those, and :meth:`call`
  refuses anything else.
* **Country scope.** Every call carries a :class:`CallScope` (the requesting
  user's role and countries). Each tool declares how its country is found -- an
  argument, a resolver, or "country-neutral" reference data -- and an
  out-of-scope country raises :class:`ScopeError` before the tool runs.
* **Logged.** Every call is recorded: tool, agent, args hash, duration, ok/error.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

log = logging.getLogger(__name__)

#: The nine agents of the design: 8 specialists + the root orchestrator.
AGENT_NAMES: frozenset[str] = frozenset({
    "ccre_orchestrator", "intake_assistant", "requirement_interpreter", "timeline_planner",
    "rule_drafter", "test_case_designer", "payload_generator", "response_reviewer", "failure_analyst",
})

# Roles that see every country, mirroring ``tools.core.security.can_see_country``.
_ALL_COUNTRY_ROLES = frozenset({"ADMIN", "PM", "CCRE_CONSULTANT", "CCRE_TEAM"})


class ToolError(Exception):
    """Base class for registry refusals."""


class RegistrationError(ToolError):
    """A tool definition breaks a registry rule (e.g. not read-only)."""


class UnknownToolError(ToolError):
    pass


class ToolNotAllowedError(ToolError):
    """The agent is not on the tool's allow-list."""


class ToolArgumentError(ToolError):
    """Arguments did not match the tool's input model."""


class ScopeError(ToolError):
    """The call reaches a country outside the requesting user's scope."""


class CallScope(BaseModel):
    """Who the agent is acting for. Carried by the job, never set by the model."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    role: str
    countries: frozenset[str] = frozenset()

    @property
    def all_countries(self) -> bool:
        return self.role.upper() in _ALL_COUNTRY_ROLES

    def allows(self, country: Optional[str]) -> bool:
        if self.all_countries:
            return True
        return bool(country) and country.strip().upper() in {c.upper() for c in self.countries}

    @classmethod
    def for_user(cls, user: Any) -> "CallScope":
        return cls(user_id=str(user.id), role=str(user.role), countries=frozenset(user.countries or []))


ToolFn = Callable[[Any, CallScope], Any]
CountryResolver = Callable[[Any], Optional[str]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    output_type: Any
    fn: ToolFn
    agents: frozenset[str]
    read_only: bool
    country_arg: Optional[str] = None
    country_resolver: Optional[CountryResolver] = None
    country_neutral: bool = False
    backed_by: str = ""


@dataclass(frozen=True)
class ToolCallRecord:
    tool: str
    agent: str
    args_hash: str
    duration_ms: float
    ok: bool
    error: Optional[str] = None


def args_hash(args: BaseModel) -> str:
    raw = json.dumps(args.model_dump(mode="json"), sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class ToolRegistry:
    _tools: dict[str, ToolSpec] = field(default_factory=dict)
    calls: deque[ToolCallRecord] = field(default_factory=lambda: deque(maxlen=1000))

    # -- registration ---------------------------------------------------------
    def register(self, *, name: str, description: str, input_model: type[BaseModel], output_type: Any,
                 fn: ToolFn, agents: set[str] | frozenset[str], read_only: bool = True,
                 country_arg: Optional[str] = None, country_resolver: Optional[CountryResolver] = None,
                 country_neutral: bool = False, backed_by: str = "") -> ToolSpec:
        if read_only is not True:
            raise RegistrationError(f"Tool {name!r} is not read-only. Agent tools must be read-only.")
        if name in self._tools:
            raise RegistrationError(f"Tool {name!r} is already registered.")
        unknown = set(agents) - AGENT_NAMES
        if unknown:
            raise RegistrationError(f"Tool {name!r} names unknown agent(s): {sorted(unknown)}.")
        if not agents:
            raise RegistrationError(f"Tool {name!r} has an empty allow-list.")
        declared = sum([country_arg is not None, country_resolver is not None, country_neutral])
        if declared != 1:
            raise RegistrationError(
                f"Tool {name!r} must declare exactly one of country_arg, country_resolver or country_neutral.")
        if country_arg is not None and country_arg not in input_model.model_fields:
            raise RegistrationError(f"Tool {name!r}: country_arg {country_arg!r} is not an input field.")
        spec = ToolSpec(name=name, description=description, input_model=input_model, output_type=output_type,
                        fn=fn, agents=frozenset(agents), read_only=True, country_arg=country_arg,
                        country_resolver=country_resolver, country_neutral=country_neutral, backed_by=backed_by)
        self._tools[name] = spec
        return spec

    # -- lookup -----------------------------------------------------------------
    def names(self) -> list[str]:
        return sorted(self._tools)

    def spec(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(f"No tool named {name!r}.") from exc

    def get_tools_for(self, agent: str) -> list[ToolSpec]:
        if agent not in AGENT_NAMES:
            raise UnknownToolError(f"Unknown agent {agent!r}.")
        return [t for t in self._tools.values() if agent in t.agents]

    # -- calling ------------------------------------------------------------------
    def _country_of(self, spec: ToolSpec, args: BaseModel) -> Optional[str]:
        if spec.country_arg is not None:
            return getattr(args, spec.country_arg)
        assert spec.country_resolver is not None
        return spec.country_resolver(args)

    def call(self, agent: str, name: str, args: dict[str, Any], scope: CallScope) -> Any:
        spec = self.spec(name)
        if agent not in spec.agents:
            raise ToolNotAllowedError(f"Agent {agent!r} may not call {name!r}.")
        try:
            parsed = spec.input_model.model_validate(args)
        except ValidationError as exc:
            raise ToolArgumentError(f"Invalid arguments for {name!r}: {exc}") from exc

        digest = args_hash(parsed)
        started = time.perf_counter()
        try:
            if not spec.country_neutral:
                country = self._country_of(spec, parsed)
                if not scope.allows(country):
                    raise ScopeError(f"{name!r} refused: country {country or '(none)'} is outside the scope "
                                     f"of user {scope.user_id}.")
            result = spec.fn(parsed, scope)
            result = TypeAdapter(spec.output_type).validate_python(result)
        except Exception as exc:
            self._record(spec.name, agent, digest, started, ok=False, error=f"{type(exc).__name__}: {exc}")
            raise
        self._record(spec.name, agent, digest, started, ok=True)
        return result

    def _record(self, tool: str, agent: str, digest: str, started: float, *, ok: bool,
                error: Optional[str] = None) -> None:
        record = ToolCallRecord(tool=tool, agent=agent, args_hash=digest,
                                duration_ms=round((time.perf_counter() - started) * 1000, 3), ok=ok, error=error)
        self.calls.append(record)
        log.info("tool_call tool=%s agent=%s args_hash=%s duration_ms=%s ok=%s%s", tool, agent, digest,
                 record.duration_ms, ok, f" error={error}" if error else "")
