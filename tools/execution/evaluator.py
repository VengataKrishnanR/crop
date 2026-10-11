"""Evaluate an ``Other Logic`` condition expression against shipment facts.

Used by the mock CCRE endpoint so the UAT loop can run offline. It interprets
the same AST the validator parses (:mod:`tools.core.grammar`).

Facts are a flat dict built from a payload by :func:`facts_from_payload`:
``serviceCodeList`` (list), ``incotermCodeList`` (list),
``destinationServiceArea`` (str), ``OriginCountry`` / ``DestinationCountry``
(str), ``shortCodes`` (list of ``{shortCode, value}``) and ``hsCodes`` (dict).
"""
from __future__ import annotations

from typing import Any

from tools.core import grammar
from tools.core.grammar import BoolOp, Call, Compare, Field, Literal, MethodCall, Not

_BLANK = "<blank>"


class EvaluationError(ValueError):
    """The expression uses a construct the evaluator cannot decide."""


def _norm(value: Any) -> str:
    text = "" if value is None else str(value)
    return "" if text == _BLANK else text.strip().lower()


def _compare(left: Any, op: str, right: Any) -> bool:
    lhs, rhs = _norm(left), _norm(right)
    if op == "==":
        return lhs == rhs
    if op == "!=":
        return lhs != rhs
    try:
        a, b = float(lhs), float(rhs)
    except ValueError:
        a, b = lhs, rhs  # type: ignore[assignment]
    return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}.get(op, False)


def _lookup(facts: dict[str, Any], name: str) -> Any:
    for key, value in facts.items():
        if key.lower() == name.lower():
            return value
    hs = facts.get("hsCodes") or {}
    for key, value in hs.items():
        if key.lower() == name.lower():
            return value
    return None


def _mask(facts: dict[str, Any], args: list[Any]) -> bool:
    """matchCiMask("shortCode|==|SDT","value|!=|<blank>") — one short-code entry satisfies all."""
    triples = []
    for arg in args:
        parts = str(arg).split("|")
        if len(parts) != 3:
            raise EvaluationError(f"matchCiMask argument is not field|op|value: {arg!r}")
        triples.append(parts)
    for entry in facts.get("shortCodes") or []:
        lowered = {str(k).lower(): v for k, v in entry.items()}
        if all(_compare(lowered.get(f.lower()), op, val) for f, op, val in triples):
            return True
    return False


def _eval(node: Any, facts: dict[str, Any]) -> Any:
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, Field):
        return _lookup(facts, node.name)
    if isinstance(node, Not):
        return not _eval(node.operand, facts)
    if isinstance(node, BoolOp):
        values = (_eval(o, facts) for o in node.operands)
        return all(values) if node.op == "&&" else any(values)
    if isinstance(node, Compare):
        return _compare(_eval(node.left, facts), node.op, _eval(node.right, facts))
    if isinstance(node, MethodCall):
        if node.method != "contains" or len(node.args) != 1:
            raise EvaluationError(f"Unsupported method {node.target}.{node.method}")
        target = _lookup(facts, node.target)
        needle = _norm(_eval(node.args[0], facts))
        if isinstance(target, (list, tuple, set)):
            return needle in {_norm(x) for x in target}
        return needle in _norm(target)
    if isinstance(node, Call):
        args = [_eval(a, facts) for a in node.args]
        if node.name == "matchCiMask":
            return _mask(facts, args)
        if node.name == "hscode" and len(args) == 2:
            return _compare(_lookup(facts, str(args[0])), "==", args[1])
        raise EvaluationError(f"Unsupported function {node.name}")
    raise EvaluationError(f"Unsupported expression node {type(node).__name__}")


def evaluate(expression: str, facts: dict[str, Any]) -> bool:
    """True when the expression holds for these facts. Blank expressions always hold."""
    if not expression or not expression.strip():
        return True
    try:
        tree = grammar.parse(expression)
    except grammar.ExpressionError as exc:
        raise EvaluationError(f"Expression does not parse: {exc}") from exc
    return bool(_eval(tree, facts))


def facts_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Map the demo shipment payload shape onto the expression vocabulary."""
    def pick(*names: str) -> Any:
        for name in names:
            for key, value in payload.items():
                if key.lower() == name.lower():
                    return value
        return None

    incoterm = pick("incoterm", "incoterms")
    return {
        "serviceCodeList": list(pick("serviceCodes", "serviceCodeList") or []),
        "incotermCodeList": incoterm if isinstance(incoterm, list) else ([incoterm] if incoterm else []),
        "destinationServiceArea": pick("destinationServiceArea") or "",
        "OriginCountry": pick("originCountry") or "",
        "DestinationCountry": pick("destinationCountry") or "",
        "shortCodes": list(pick("shortCodes") or []),
        "hsCodes": dict(pick("hsCodes") or {}),
    }
