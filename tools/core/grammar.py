"""Grammar for the ``Other Logic`` rule condition language.

Storing these expressions as free text is how two incompatible ``matchCiMask``
syntaxes and an operator-precedence bug both reached a live workbook. Parsing
them to an AST makes those mechanical findings instead of review luck.

Grammar (lowest precedence first)::

    or_expr    := and_expr ( '||' and_expr )*
    and_expr   := unary ( '&&' unary )*
    unary      := '!' unary | primary
    primary    := '(' or_expr ')' | comparison | call | member_call | atom
    comparison := atom ( '==' | '!=' ) atom
    call       := IDENT '(' [ args ] ')'
    member     := IDENT '.' IDENT '(' [ args ] ')'
    atom       := STRING | NUMBER | IDENT
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional, Union

# --------------------------------------------------------------------------- #
# Known vocabulary, derived from expressions observed in live workbook rows.
# Anything outside this set is reported rather than silently accepted.
# --------------------------------------------------------------------------- #

KNOWN_FUNCTIONS: dict[str, int] = {
    # name -> required argument count (-1 = variadic)
    "matchCiMask": -1,
    "hscode": 2,
}

KNOWN_METHODS: dict[str, set[str]] = {
    "serviceCodeList": {"contains"},
    "incotermCodeList": {"contains"},
    "destinationServiceArea": {"contains"},
}

KNOWN_FIELDS: set[str] = {"OriginCountry", "DestinationCountry", "inboundHsCode"}

# matchCiMask arguments are "field|op|value" triples. The Other Logic palette in
# the workbook uses commas instead, which does not parse the same way -- copying
# from the palette into a live row is therefore a defect, not a convenience.
_MASK_PIPE = re.compile(r"^[^|]+\|(==|!=|>=|<=|>|<)\|.*$")
_MASK_COMMA = re.compile(r"^[^,]+,(==|!=|>=|<=|>|<),.*$")


class ExpressionError(ValueError):
    """Raised when an expression cannot be parsed at all."""

    def __init__(self, message: str, position: int = -1) -> None:
        super().__init__(message)
        self.message = message
        self.position = position


# --------------------------------------------------------------------------- #
# Tokeniser
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Token:
    kind: str  # IDENT STRING NUMBER OP LPAREN RPAREN COMMA DOT BANG
    value: str
    pos: int


_TOKEN_RE = re.compile(
    r"""
    (?P<WS>\s+)
  | (?P<STRING>"[^"]*"|'[^']*')
  | (?P<NUMBER>\d+(?:\.\d+)?)
  | (?P<OP>==|!=|>=|<=|&&|\|\||>|<)
  | (?P<BANG>!)
  | (?P<LPAREN>\()
  | (?P<RPAREN>\))
  | (?P<COMMA>,)
  | (?P<DOT>\.)
  | (?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)
    """,
    re.VERBOSE,
)


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    while i < len(src):
        m = _TOKEN_RE.match(src, i)
        if not m:
            raise ExpressionError(f"unexpected character {src[i]!r}", i)
        kind = m.lastgroup
        assert kind is not None
        if kind != "WS":
            tokens.append(Token(kind, m.group(), m.start()))
        i = m.end()
    return tokens


# --------------------------------------------------------------------------- #
# AST
# --------------------------------------------------------------------------- #

@dataclass
class Literal:
    value: str
    is_string: bool = True


@dataclass
class Field:
    name: str


@dataclass
class Call:
    name: str
    args: list["Node"] = field(default_factory=list)


@dataclass
class MethodCall:
    target: str
    method: str
    args: list["Node"] = field(default_factory=list)


@dataclass
class Compare:
    left: "Node"
    op: str
    right: "Node"


@dataclass
class Not:
    operand: "Node"


@dataclass
class BoolOp:
    op: str  # '&&' or '||'
    operands: list["Node"]
    parenthesised: bool = False


Node = Union[Literal, Field, Call, MethodCall, Compare, Not, BoolOp]


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.t = tokens
        self.i = 0

    def peek(self) -> Optional[Token]:
        return self.t[self.i] if self.i < len(self.t) else None

    def next(self) -> Token:
        tok = self.peek()
        if tok is None:
            raise ExpressionError("unexpected end of expression", -1)
        self.i += 1
        return tok

    def expect(self, kind: str, value: Optional[str] = None) -> Token:
        tok = self.next()
        if tok.kind != kind or (value is not None and tok.value != value):
            raise ExpressionError(f"expected {value or kind}, found {tok.value!r}", tok.pos)
        return tok

    def parse(self) -> Node:
        node = self.parse_or()
        if self.peek() is not None:
            tok = self.peek()
            assert tok is not None
            raise ExpressionError(f"trailing input at {tok.value!r}", tok.pos)
        return node

    def parse_or(self) -> Node:
        parts = [self.parse_and()]
        while (tok := self.peek()) and tok.kind == "OP" and tok.value == "||":
            self.next()
            parts.append(self.parse_and())
        return parts[0] if len(parts) == 1 else BoolOp("||", parts)

    def parse_and(self) -> Node:
        parts = [self.parse_unary()]
        while (tok := self.peek()) and tok.kind == "OP" and tok.value == "&&":
            self.next()
            parts.append(self.parse_unary())
        return parts[0] if len(parts) == 1 else BoolOp("&&", parts)

    def parse_unary(self) -> Node:
        tok = self.peek()
        if tok and tok.kind == "BANG":
            self.next()
            return Not(self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> Node:
        tok = self.peek()
        if tok is None:
            raise ExpressionError("unexpected end of expression", -1)

        if tok.kind == "LPAREN":
            self.next()
            inner = self.parse_or()
            self.expect("RPAREN")
            if isinstance(inner, BoolOp):
                inner.parenthesised = True
            return self._maybe_compare(inner)

        left = self.parse_atom()
        return self._maybe_compare(left)

    def _maybe_compare(self, left: Node) -> Node:
        tok = self.peek()
        if tok and tok.kind == "OP" and tok.value in {"==", "!=", ">=", "<=", ">", "<"}:
            self.next()
            right = self.parse_atom()
            return Compare(left, tok.value, right)
        return left

    def parse_atom(self) -> Node:
        tok = self.next()
        if tok.kind == "STRING":
            return Literal(tok.value[1:-1], is_string=True)
        if tok.kind == "NUMBER":
            return Literal(tok.value, is_string=False)
        if tok.kind != "IDENT":
            raise ExpressionError(f"expected a value, found {tok.value!r}", tok.pos)

        nxt = self.peek()
        if nxt and nxt.kind == "DOT":
            self.next()
            method = self.expect("IDENT").value
            args = self.parse_args()
            return MethodCall(tok.value, method, args)
        if nxt and nxt.kind == "LPAREN":
            args = self.parse_args()
            return Call(tok.value, args)
        return Field(tok.value)

    def parse_args(self) -> list[Node]:
        self.expect("LPAREN")
        args: list[Node] = []
        if (tok := self.peek()) and tok.kind == "RPAREN":
            self.next()
            return args
        while True:
            args.append(self.parse_or())
            tok = self.next()
            if tok.kind == "RPAREN":
                break
            if tok.kind != "COMMA":
                raise ExpressionError(f"expected ',' or ')', found {tok.value!r}", tok.pos)
        return args


def parse(expression: str) -> Node:
    """Parse an expression, raising :class:`ExpressionError` if it is malformed."""
    tokens = tokenize(expression)
    if not tokens:
        raise ExpressionError("empty expression")
    return _Parser(tokens).parse()


# --------------------------------------------------------------------------- #
# Static analysis
# --------------------------------------------------------------------------- #

@dataclass
class Diagnostic:
    code: str
    severity: str  # "error" | "warning"
    message: str


def walk(node: Node) -> Iterable[Node]:
    yield node
    if isinstance(node, Not):
        yield from walk(node.operand)
    elif isinstance(node, BoolOp):
        for child in node.operands:
            yield from walk(child)
    elif isinstance(node, Compare):
        yield from walk(node.left)
        yield from walk(node.right)
    elif isinstance(node, (Call, MethodCall)):
        for child in node.args:
            yield from walk(child)


def render(node: Node) -> str:
    """Render an AST back to source. Used for normalised comparison and export."""
    if isinstance(node, Literal):
        return f'"{node.value}"' if node.is_string else node.value
    if isinstance(node, Field):
        return node.name
    if isinstance(node, Call):
        return f"{node.name}({','.join(render(a) for a in node.args)})"
    if isinstance(node, MethodCall):
        return f"{node.target}.{node.method}({','.join(render(a) for a in node.args)})"
    if isinstance(node, Compare):
        return f"{render(node.left)}{node.op}{render(node.right)}"
    if isinstance(node, Not):
        return f"!{render(node.operand)}"
    if isinstance(node, BoolOp):
        joined = node.op.join(render(o) for o in node.operands)
        return f"({joined})" if node.parenthesised else joined
    raise TypeError(f"unrenderable node {node!r}")


def normalise(expression: str) -> str:
    """Whitespace- and layout-insensitive form, for comparing two expressions."""
    return render(parse(expression))


def analyse(expression: str) -> list[Diagnostic]:
    """Static checks over one expression. Empty list means clean."""
    out: list[Diagnostic] = []

    if not expression or not expression.strip():
        return out

    try:
        tree = parse(expression)
    except ExpressionError as exc:
        return [Diagnostic("EXPR_PARSE", "error", f"Expression does not parse: {exc.message}")]

    nodes = list(walk(tree))

    # Unknown vocabulary.
    for node in nodes:
        if isinstance(node, Call):
            if node.name not in KNOWN_FUNCTIONS:
                out.append(Diagnostic("EXPR_UNKNOWN_FN", "error", f"Unknown function {node.name!r}."))
            else:
                arity = KNOWN_FUNCTIONS[node.name]
                if arity >= 0 and len(node.args) != arity:
                    out.append(Diagnostic(
                        "EXPR_ARITY", "error",
                        f"{node.name} takes {arity} arguments, got {len(node.args)}.",
                    ))
        elif isinstance(node, MethodCall):
            allowed = KNOWN_METHODS.get(node.target)
            if allowed is None:
                out.append(Diagnostic("EXPR_UNKNOWN_FIELD", "error", f"Unknown list {node.target!r}."))
            elif node.method not in allowed:
                out.append(Diagnostic(
                    "EXPR_UNKNOWN_METHOD", "error",
                    f"{node.target} has no method {node.method!r}.",
                ))
        elif isinstance(node, Field):
            if node.name not in KNOWN_FIELDS and node.name not in KNOWN_METHODS:
                out.append(Diagnostic("EXPR_UNKNOWN_FIELD", "error", f"Unknown field {node.name!r}."))

    # matchCiMask argument syntax: pipes, not commas.
    for node in nodes:
        if isinstance(node, Call) and node.name == "matchCiMask":
            for arg in node.args:
                if not isinstance(arg, Literal) or not arg.is_string:
                    out.append(Diagnostic(
                        "EXPR_MASK_ARG", "error",
                        "matchCiMask arguments must be quoted 'field|op|value' strings.",
                    ))
                    continue
                if _MASK_PIPE.match(arg.value):
                    continue
                if _MASK_COMMA.match(arg.value):
                    out.append(Diagnostic(
                        "EXPR_MASK_SYNTAX", "error",
                        f"matchCiMask argument {arg.value!r} is comma-delimited. Live rules require "
                        f"pipes: {arg.value.replace(',', '|')!r}.",
                    ))
                else:
                    out.append(Diagnostic(
                        "EXPR_MASK_SYNTAX", "error",
                        f"matchCiMask argument {arg.value!r} is not a 'field|op|value' triple.",
                    ))

    # Mixed && / || without parentheses: && binds tighter, which is rarely intended
    # in these rules and has already shipped as a defect.
    for node in nodes:
        if isinstance(node, BoolOp) and node.op == "||":
            for child in node.operands:
                if isinstance(child, BoolOp) and child.op == "&&" and not child.parenthesised:
                    out.append(Diagnostic(
                        "EXPR_PRECEDENCE", "warning",
                        "'&&' binds tighter than '||' and is not parenthesised, so the '&&' clause "
                        "applies only to its immediate neighbour. Add brackets to state the intent.",
                    ))
                    break

    # Repeated identical terms inside one boolean group.
    for node in nodes:
        if isinstance(node, BoolOp):
            seen: set[str] = set()
            for child in node.operands:
                key = render(child)
                if key in seen:
                    out.append(Diagnostic(
                        "EXPR_REPEATED_TERM", "warning",
                        f"Term {key} appears more than once in the same {node.op} group.",
                    ))
                seen.add(key)

    return out


def referenced_service_codes(expression: str) -> set[str]:
    """Service codes the expression tests, for coverage and test-case generation."""
    try:
        tree = parse(expression)
    except ExpressionError:
        return set()
    codes: set[str] = set()
    for node in walk(tree):
        if isinstance(node, MethodCall) and node.target == "serviceCodeList":
            for arg in node.args:
                if isinstance(arg, Literal) and arg.is_string:
                    codes.add(arg.value)
    return codes
