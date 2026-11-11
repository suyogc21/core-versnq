"""Calculated fields: a tiny, safe formula language on numbers and dates (Decision log #27, A6).

    fee - ifempty(scholarship, 0)
    round(amount * 18 / 100, 2)
    days_between(enquiry_date, today())

Grammar: + - * / with the usual precedence, brackets, unary minus, numbers, field keys and
functions. Parsed by hand into a small tree and evaluated with Decimal arithmetic, never
`eval`. An empty field makes the result empty (use ifempty() for a default); dividing by
zero gives an empty result. Dates are only used through days_between().
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.core.errors import Invalid

MAX_LENGTH = 500
MAX_DEPTH = 30
_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([a-z][a-z0-9_]*)|(.))")

# name: (min args, max args)
FUNCTIONS = {
    "round": (1, 2),
    "days_between": (2, 2),
    "today": (0, 0),
    "ifempty": (2, 2),
    "min": (2, 10),
    "max": (2, 10),
    "abs": (1, 1),
}


@dataclass(frozen=True)
class Node:
    kind: str  # num / name / op / neg / call
    value: object = None
    args: tuple = ()


def _tokens(text: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        num, name, other = m.groups()
        if num:
            out.append(("num", num))
        elif name:
            out.append(("name", name))
        elif other and other.strip():
            if other not in "+-*/(),":
                raise Invalid(f"Formula: '{other}' is not allowed")
            out.append((other, other))
    return out


class _Parser:
    def __init__(self, text: str):
        if len(text) > MAX_LENGTH:
            raise Invalid(f"Formula: up to {MAX_LENGTH} characters")
        self.toks = _tokens(text.lower())
        self.i = 0

    def peek(self):
        return self.toks[self.i][0] if self.i < len(self.toks) else None

    def take(self, kind=None):
        if self.i >= len(self.toks) or (kind and self.toks[self.i][0] != kind):
            want = f"'{kind}'" if kind else "more"
            raise Invalid(f"Formula: expected {want}")
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def parse(self) -> Node:
        if not self.toks:
            raise Invalid("Formula: write a formula")
        node = self.expr(0)
        if self.i != len(self.toks):
            raise Invalid(f"Formula: unexpected '{self.toks[self.i][1]}'")
        return node

    def expr(self, depth):
        node = self.term(depth)
        while self.peek() in ("+", "-"):
            op = self.take()[0]
            node = Node("op", op, (node, self.term(depth)))
        return node

    def term(self, depth):
        node = self.factor(depth)
        while self.peek() in ("*", "/"):
            op = self.take()[0]
            node = Node("op", op, (node, self.factor(depth)))
        return node

    def factor(self, depth):
        if depth > MAX_DEPTH:
            raise Invalid("Formula: too deeply nested")
        kind = self.peek()
        if kind == "-":
            self.take()
            return Node("neg", None, (self.factor(depth + 1),))
        if kind == "num":
            return Node("num", Decimal(self.take()[1]))
        if kind == "(":
            self.take()
            node = self.expr(depth + 1)
            self.take(")")
            return node
        if kind == "name":
            name = self.take()[1]
            if self.peek() != "(":
                return Node("name", name)
            self.take("(")
            args = []
            if self.peek() != ")":
                args.append(self.expr(depth + 1))
                while self.peek() == ",":
                    self.take()
                    args.append(self.expr(depth + 1))
            self.take(")")
            if name not in FUNCTIONS:
                raise Invalid(f"Formula: unknown function {name}()")
            lo, hi = FUNCTIONS[name]
            if not lo <= len(args) <= hi:
                raise Invalid(
                    f"Formula: {name}() takes {lo if lo == hi else f'{lo} to {hi}'} values"
                )
            return Node("call", name, tuple(args))
        raise Invalid("Formula: expected a number, a field or a bracket")


def parse(text: str) -> Node:
    return _Parser(text).parse()


def names(node: Node) -> set[str]:
    """Field keys a formula reads."""
    if node.kind == "name":
        return {node.value}
    out: set[str] = set()
    for a in node.args:
        out |= names(a)
    return out


def check(text: str, fields: dict[str, str]) -> Node:
    """Parse and check every name is a usable field. fields: key -> "number" | "date"."""
    node = parse(text)
    unknown = sorted(names(node) - set(fields))
    if unknown:
        raise Invalid(f"Formula: no number or date field called '{unknown[0]}'")
    _types(node, fields)
    return node


def _types(node: Node, fields: dict[str, str]) -> str:
    """Static type of a node: number or date. Dates only go into days_between/ifempty."""
    if node.kind == "num":
        return "number"
    if node.kind == "name":
        return fields[node.value]
    kinds = [_types(a, fields) for a in node.args]
    if node.kind == "call" and node.value == "today":
        return "date"
    if node.kind == "call" and node.value == "days_between":
        if kinds != ["date", "date"]:
            raise Invalid("Formula: days_between() takes two dates")
        return "number"
    if node.kind == "call" and node.value == "ifempty":
        if kinds[0] != kinds[1]:
            raise Invalid("Formula: ifempty() needs a default of the same kind")
        return kinds[0]
    if "date" in kinds:
        raise Invalid("Formula: dates can only be used in days_between()")
    return "number"


def evaluate(node: Node, values: dict, today_: date) -> Decimal | date | None:
    k = node.kind
    if k == "num":
        return node.value
    if k == "name":
        return values.get(node.value)
    if k == "neg":
        v = evaluate(node.args[0], values, today_)
        return None if v is None else -v
    if k == "op":
        a, b = (evaluate(x, values, today_) for x in node.args)
        if a is None or b is None:
            return None
        if node.value == "+":
            return a + b
        if node.value == "-":
            return a - b
        if node.value == "*":
            return a * b
        return None if b == 0 else a / b
    name = node.value
    if name == "today":
        return today_
    if name == "ifempty":
        a = evaluate(node.args[0], values, today_)
        return a if a is not None else evaluate(node.args[1], values, today_)
    args = [evaluate(a, values, today_) for a in node.args]
    if any(a is None for a in args):
        return None
    if name == "days_between":
        return Decimal((args[1] - args[0]).days)
    if name == "round":
        places = int(args[1]) if len(args) > 1 else 0
        if not 0 <= places <= 6:
            return None
        return args[0].quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    if name == "abs":
        return abs(args[0])
    return min(args) if name == "min" else max(args)


def to_stored(value) -> int | float | None:
    """A result as a number field stores it: whole numbers as int, else up to 6 decimals."""
    if value is None or isinstance(value, date):
        return None
    try:
        q = value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None  # astronomically large
    if abs(q) > Decimal(10) ** 15:
        return None
    return int(q) if q == q.to_integral_value() else float(q)


def as_input(raw, field_type: str):
    """A stored field value as a formula input."""
    if raw is None:
        return None
    if field_type == "date":
        try:
            return date.fromisoformat(str(raw))
        except ValueError:
            return None
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        return None


def order(formulas: dict[str, Node]) -> list[str]:
    """Calculated field keys in the order to compute them; refuses cycles."""
    done: list[str] = []
    state: dict[str, int] = {}

    def visit(key: str, path: list[str]) -> None:
        if state.get(key) == 2:
            return
        if state.get(key) == 1:
            raise Invalid(f"Formula: {' → '.join([*path, key])} goes round in a circle")
        state[key] = 1
        for dep in sorted(names(formulas[key])):
            if dep in formulas:
                visit(dep, [*path, key])
        state[key] = 2
        done.append(key)

    for key in sorted(formulas):
        visit(key, [])
    return done
