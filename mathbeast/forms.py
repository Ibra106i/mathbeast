"""Answer forms: what "the right answer" even means for a given question.

The checker in `verify.py` decides mathematical equality. This module decides
which question is being asked. `x = 3` is a different requirement from "give
your answer to 3 significant figures", and conflating them is how a tutor ends
up marking correct work as wrong.

Design decision, documented because exam boards differ: under a `rounded` form
we accept any value that rounds to the same figure at the stated precision. We
do not punish over-precision. Handing back 14.142 when 14.1 was asked for is not
a mathematical error, and a system whose whole pitch is that it cannot lie
about correctness has no business calling it one.

The reverse asymmetry is deliberate and does hold: under an `exact` form,
14.1 is rejected when the true answer is 14.1421.
"""

from __future__ import annotations

import math
import re
from enum import Enum

import sympy

from mathbeast.verify import (
    CheckResult,
    ParseRejected,
    Verdict,
    _find_relation,
    _split_top_level,
    normalise,
    to_expr,
    verify,
)


class AnswerForm(Enum):
    EXACT = "exact"
    ROUNDED = "rounded"
    SET = "set"
    INTERVAL = "interval"


_PRECISION_RE = re.compile(r"^\s*(\d+)\s*(sf|dp)\s*$", re.IGNORECASE)


def sig_figs_round(value, n: int) -> float:
    """Round to `n` significant figures.

    Returns a plain float on purpose. SymPy's `Float` carries precision
    metadata, so `Float(1234.5, 3) == 1230` is False even though both are
    numerically 1230. Precision answers are compared numerically throughout.
    """
    if n < 1:
        raise ValueError("significant figures must be >= 1")
    number = float(sympy.N(value))
    if number == 0:
        return 0.0
    return round(number, n - 1 - math.floor(math.log10(abs(number))))


def _parse_precision(spec: str | None) -> tuple[int, str]:
    """`"3sf"` -> (3, "sf"); `"2dp"` -> (2, "dp")."""
    if not spec:
        raise ParseRejected("a rounded form needs a precision, e.g. '3sf' or '2dp'")
    match = _PRECISION_RE.match(spec)
    if not match:
        raise ParseRejected(f"unrecognised precision {spec!r}; use e.g. '3sf' or '2dp'")
    digits = int(match.group(1))
    if digits < 1:
        raise ParseRejected("precision must be at least 1")
    return digits, match.group(2).lower()


def _round_to(value, digits: int, kind: str) -> float:
    if kind == "dp":
        return round(float(sympy.N(value)), digits)
    if kind == "sf":
        return sig_figs_round(value, digits)
    raise ParseRejected(f"unknown precision kind {kind!r}")


def _numerically_equal(a, b, tol: float = 1e-9) -> bool:
    try:
        return abs(float(sympy.N(a)) - float(sympy.N(b))) < tol
    except (TypeError, ValueError):
        return False


def check_rounded(expected: str, given: str, spec: str) -> CheckResult:
    """Accept any value agreeing with the expected value at the stated precision."""
    try:
        digits, kind = _parse_precision(spec)
    except ParseRejected as exc:
        return CheckResult(Verdict.UNPARSEABLE, expected, given, str(exc))

    try:
        expected_value = sympy.sympify(normalise(expected))
        given_value = sympy.sympify(normalise(given))
    except (ParseRejected, TypeError, ValueError, SyntaxError) as exc:
        return CheckResult(Verdict.UNPARSEABLE, expected, given, str(exc))

    if expected_value.free_symbols or given_value.free_symbols:
        return CheckResult(
            Verdict.UNPARSEABLE,
            expected,
            given,
            "a rounded answer must be a number, not an expression",
        )

    want, got = _round_to(expected_value, digits, kind), _round_to(given_value, digits, kind)

    if _numerically_equal(want, got):
        return CheckResult(
            Verdict.PROVEN_EQUAL,
            expected,
            given,
            f"agrees at {digits} {kind} (both round to {want:g})",
        )

    # They differ at the required precision. For plain numbers this is
    # arithmetic, not a proof problem, so it is decidable -- do not shrug.
    try:
        difference = float(sympy.N(given_value - expected_value))
        if abs(difference) > 1e-12:
            return CheckResult(
                Verdict.PROVEN_DIFFERENT,
                expected,
                given,
                f"differs at {digits} {kind} ({want:g} vs {got:g})",
            )
    except (TypeError, ValueError):
        pass

    return CheckResult(Verdict.UNKNOWN, expected, given, "precision comparison failed")


def _solutions_of(text: str, variable: str):
    """The solution set a student answer denotes.

    Accepts a bare value, a comma-separated list, an equation, an equation in a
    different but equivalent form -- `2x = 6` and `x = 3` both denote {3} -- or
    a disjunction such as `x = 2 or x = 3`.
    """
    cleaned = normalise(text)
    var = sympy.Symbol(variable)

    if cleaned.startswith("{") and cleaned.endswith("}"):
        inner = cleaned[1:-1].strip()
        if not inner:
            return sympy.FiniteSet()
        return sympy.FiniteSet(*[to_expr(p) for p in _split_top_level(inner)])

    # Unions before relations: `x=2 or x=3` is two equations, and splitting on
    # the first `=` alone would try to parse "2 or x=3" as a single expression.
    disjuncts = re.split(r"\s+or\s+", cleaned)
    if len(disjuncts) > 1:
        return sympy.Union(*[_solutions_of(d, variable) for d in disjuncts])

    conjuncts = re.split(r"\s+and\s+", cleaned)
    if len(conjuncts) > 1:
        return sympy.Intersection(*[_solutions_of(c, variable) for c in conjuncts])

    lhs, op, rhs = _find_relation(cleaned)
    if op:
        equation = sympy.Eq(to_expr(lhs), to_expr(rhs))
        try:
            roots = sympy.solve(equation, var)
        except (TypeError, ValueError, NotImplementedError):
            raise ParseRejected("could not solve that equation") from None
        return sympy.FiniteSet(*roots)

    # No relation: treat as a bare value, or a list separated by comma.
    parts = [p for p in re.split(r"\s*,\s*", cleaned) if p]
    if len(parts) > 1:
        return sympy.FiniteSet(*[to_expr(p) for p in parts])
    return sympy.FiniteSet(to_expr(cleaned))


def check_set(expected: str, given: str, spec: str | None = None) -> CheckResult:
    """Compare solution *sets*, so equivalent routes to the answer agree."""
    variable = spec or "x"
    try:
        want = _solutions_of(expected, variable)
        got = _solutions_of(given, variable)
    except (ParseRejected, TypeError, ValueError, SyntaxError) as exc:
        return CheckResult(Verdict.UNPARSEABLE, expected, given, str(exc))

    if want == got:
        return CheckResult(
            Verdict.PROVEN_EQUAL, expected, given, f"identical solution sets {want}"
        )
    return CheckResult(
        Verdict.PROVEN_DIFFERENT, expected, given, f"{got} is not {want}"
    )


def check_interval(expected: str, given: str, spec: str | None = None) -> CheckResult:
    """Compare intervals written as `[0,5]`, `(0,5]` or `0 <= x <= 5`."""
    variable = spec or "x"
    try:
        want = _to_interval(expected, variable)
        got = _to_interval(given, variable)
    except (ParseRejected, TypeError, ValueError, SyntaxError) as exc:
        return CheckResult(Verdict.UNPARSEABLE, expected, given, str(exc))

    if want == got:
        return CheckResult(
            Verdict.PROVEN_EQUAL, expected, given, f"identical intervals {want}"
        )
    return CheckResult(Verdict.PROVEN_DIFFERENT, expected, given, f"{got} is not {want}")


def _to_interval(text: str, variable: str):
    cleaned = normalise(text)
    var = sympy.Symbol(variable)

    bracket = re.match(r"^([\[\(])([^,]+),([^,]+)([\]\)])$", cleaned)
    if bracket:
        return sympy.Interval(
            to_expr(bracket.group(2)),
            to_expr(bracket.group(3)),
            bracket.group(1) == "(",
            bracket.group(4) == ")",
        )

    # Capture the operators rather than discarding them. Splitting `0<=x<=5`
    # on a plain non-capturing group yields ['0','x','5'] -- the two `<=` are
    # swallowed, and an inclusive interval silently becomes an open one.
    tokens = re.split(r"\s*(<=|>=|<|>|=)\s*", cleaned)
    if len(tokens) == 5:
        left, op_left, variable, op_right, right = tokens
        if op_left != op_right:
            raise ParseRejected(f"{text!r} is not a single interval")
        closed = op_left in ("<=", ">=")
        return sympy.Interval(
            to_expr(left), to_expr(right), not closed, not closed
        )

    raise ParseRejected(f"{text!r} is not an interval")


def check(expected: str, given: str, form: AnswerForm, spec: str | None = None) -> CheckResult:
    """Dispatch to the comparator for the question's answer form."""
    if form is AnswerForm.EXACT:
        return verify(expected, given)
    if form is AnswerForm.ROUNDED:
        return check_rounded(expected, given, spec or "")
    if form is AnswerForm.SET:
        return check_set(expected, given, spec)
    if form is AnswerForm.INTERVAL:
        return check_interval(expected, given, spec)
    raise ValueError(f"unhandled answer form {form!r}")