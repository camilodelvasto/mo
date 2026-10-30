# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Compile a filter expression against the flow's declared vocabulary; fold to a
doc_id set over the projection cache. Undeclared field / invalid enum THROWS.
Imports the flow reader from the corpus engine; never redefines the vocabulary.

Grammar (total — anything else is a rejected expression with its reason):
    expr   := or
    or     := and ( 'OR' and )*
    and    := unary ( 'AND' unary )*
    unary  := 'NOT' unary | '(' expr ')' | comparison
    comparison := FIELD ('==' | '!=') VALUE
                | FIELD 'in' '[' VALUE (',' VALUE)* ']'
                | FIELD 'has' VALUE
                | FIELD 'not' 'has' VALUE
A VALUE runs to the next boundary token (AND/OR/)/]/,/end), so values may
contain spaces. FIELD is a single declared field name.
"""
import re

from shapes.corpus.access.errors import FilterError
from shapes.corpus.engine.assert_inbox import _declared

_BOUNDARY = {"AND", "OR", ")", "]", ","}
_TOKEN = re.compile(r"\(|\)|\[|\]|,|==|!=|\bAND\b|\bOR\b|\bNOT\b|\bin\b|\bhas\b|[^\s()\[\],=!]+")


def doc_ids_for(expr, flow: dict, projections: dict) -> set | None:
    if expr is None or not expr.strip():
        return None
    declared = _declared(flow)
    tokens = _TOKEN.findall(expr)
    parser = _Parser(tokens, declared)
    predicate = parser.parse()
    return {doc_id for doc_id, proj in projections.items() if predicate(proj)}


class _Parser:
    def __init__(self, tokens: list, declared: dict):
        self.toks = tokens
        self.i = 0
        self.declared = declared

    def _peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def _next(self):
        tok = self._peek()
        self.i += 1
        return tok

    def parse(self):
        pred = self._or()
        if self.i != len(self.toks):
            raise FilterError(f"unexpected token: {self._peek()!r}")
        return pred

    def _or(self):
        left = self._and()
        while self._peek() == "OR":
            self._next()
            right = self._and()
            left = (lambda a, b: lambda p: a(p) or b(p))(left, right)
        return left

    def _and(self):
        left = self._unary()
        while self._peek() == "AND":
            self._next()
            right = self._unary()
            left = (lambda a, b: lambda p: a(p) and b(p))(left, right)
        return left

    def _unary(self):
        if self._peek() == "NOT":
            self._next()
            inner = self._unary()
            return lambda p: not inner(p)
        if self._peek() == "(":
            self._next()
            inner = self._or()
            if self._next() != ")":
                raise FilterError("missing closing )")
            return inner
        return self._comparison()

    def _value_until_boundary(self) -> str:
        parts = []
        while self._peek() is not None and self._peek() not in _BOUNDARY:
            parts.append(self._next())
        if not parts:
            raise FilterError("expected a value")
        return " ".join(parts)

    def _comparison(self):
        field = self._next()
        decl = self.declared.get(field)
        if decl is None:
            raise FilterError(f"field not declared by this flow: {field}")
        op = self._next()
        kind = decl["type"]

        if op in ("==", "!="):
            if kind == "set":
                raise FilterError(f"{field}: {op!r} needs a scalar or enum field, not set (use 'has')")
            value = self._value_until_boundary()
            self._check_enum(field, decl, value)
            neg = op == "!="
            return lambda p, f=field, v=value, n=neg: (
                (p.get(f) != v) if n else (p.get(f) == v))

        if op == "in":
            if kind == "set":
                raise FilterError(f"{field}: 'in' needs a scalar or enum field, not set (use 'has')")
            if self._next() != "[":
                raise FilterError(f"{field} in expects [")
            values = []
            while True:
                values.append(self._value_until_boundary())
                nxt = self._next()
                if nxt == "]":
                    break
                if nxt != ",":
                    raise FilterError(f"expected , or ] in set literal, got {nxt!r}")
            for v in values:
                self._check_enum(field, decl, v)
            return lambda p, f=field, vs=set(values): p.get(f) in vs

        if op == "has" or op == "not":
            negated = False
            if op == "not":
                if self._next() != "has":
                    raise FilterError(f"{field}: expected 'has' after 'not'")
                negated = True
            if kind != "set":
                raise FilterError(f"{field}: 'has' needs a set field, not {kind}")
            value = self._value_until_boundary()
            return lambda p, f=field, v=value, n=negated: (
                (v not in (p.get(f) or [])) if n else (v in (p.get(f) or [])))

        raise FilterError(f"unknown operator: {op!r}")

    def _check_enum(self, field: str, decl: dict, value: str) -> None:
        if decl["type"] == "enum" and value not in decl["values"]:
            raise FilterError(f"{field}: {value!r} not in {decl['values']}")
