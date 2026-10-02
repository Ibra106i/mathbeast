"""Form-aware verification with an honest four-state answer.

SymPy's ``simplify`` can hang indefinitely, and it returns ``False`` for
expressions that are true but not provable. A boolean checker therefore lies in
two directions: it marks correct answers wrong, and it cannot distinguish
"wrong" from "I gave up".

Everything here returns one of four states. ``UNKNOWN`` is deliberately not
``PROVEN_DIFFERENT``.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

import sympy
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

# --- normalisation ---------------------------------------------------------

# Unicode that students paste in constantly, mapped to ASCII SymPy understands.
_UNICODE_MAP = {
    "\u2212": "-",  # minus sign
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u00d7": "*",  # multiplication sign
    "\u22c5": "*",  # dot operator
    "\u00f7": "/",  # division sign
    "\u00b7": "*",  # middle dot
    "\u03c0": "pi",  # pi
    "\u221a": "sqrt",  # radical
    "\u2264": "<=",
    "\u2265": ">=",
    "\u2260": "!=",
    "\u00a0": " ",
}

# Strict allowlist. This parser is a trust boundary: a student typing into a
# drill, or a narrator emitting prose, must never reach code execution. Only
# these characters may reach the parser at all.
_ALLOWED_CHARS = re.compile(r"^[0-9a-zA-Z\s\+\-\*/\^\(\)\[\]\{\}\.\,<>=!%:_\|]*$")

# The character allowlist cannot see identifiers, and `__import__` is all
# letters and underscores. Block dunder/private access explicitly.
_FORBIDDEN_IDENT = re.compile(r"(^|[^A-Za-z0-9])_[A-Za-z0-9_]*")
_FORBIDDEN_WORDS = re.compile(
    r"\b(import|lambda|def|class|exec|eval|compile|globals|locals|open|system)\b",
    re.IGNORECASE,
)

_TRANSFORMS = standard_transformations + (implicit_multiplication_application,)


class Verdict(Enum):
    """The only four things this project is allowed to say about an answer."""

    PROVEN_EQUAL = "proven_equal"
    PROVEN_DIFFERENT = "proven_different"
    UNKNOWN = "unknown"
    UNPARSEABLE = "unparseable"

    @property
    def is_correct(self) -> bool:
        return self is Verdict.PROVEN_EQUAL


@dataclass(frozen=True)
class CheckResult:
    verdict: Verdict
    expected: str
    given: str
    reason: str

    @property
    def is_correct(self) -> bool:
        return self.verdict.is_correct

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.verdict.value}: {self.reason}"


class ParseRejected(ValueError):
    """Input failed the allowlist. Never reaches the expression parser."""


def normalise(text: str) -> str:
    """Fold unicode maths and reject anything outside the allowlist."""
    if not isinstance(text, str):
        raise ParseRejected(f"expected str, got {type(text).__name__}")

    # Reject before NFKC, not after. NFKC rewrites `xÂ³` to `x3`, which parses as
    # x*3 -- silently turning a typo into a confidently wrong comparison. A
    # rejection is recoverable; a misread is the exact bug this project exists
    # to prevent. Covers superscripts, vulgar fractions and Roman numerals.
    for ch in text:
        if unicodedata.category(ch) in ("No", "Nl"):
            raise ParseRejected(
                f"character {ch!r} (U+{ord(ch):04X}) is not supported; "
                "write it out, e.g. x^3 not xÂ³"
            )

    cleaned = unicodedata.normalize("NFKC", text)
    for bad, good in _UNICODE_MAP.items():
        cleaned = cleaned.replace(bad, good)

    cleaned = cleaned.strip().replace("^", "**")

    if not _ALLOWED_CHARS.match(cleaned):
        raise ParseRejected("input contains characters outside the allowlist")
    if _FORBIDDEN_IDENT.search(cleaned):
        raise ParseRejected("private/dunder identifiers are not allowed")
    if _FORBIDDEN_WORDS.search(cleaned):
        raise ParseRejected("input contains a reserved word")

    return cleaned


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    """Split on `sep` ignoring separators nested inside brackets."""
    parts, depth, buf = [], 0, []
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _find_relation(text: str) -> tuple[str, str, str]:
    """Split a top-level relational operator out of `text`.

    Returns (lhs, op, rhs). Op is "" when there is no relation. Deliberately
    does not match `<=`, `>=` or `!=`, which are answer *forms* rather than
    equations -- see `forms.py`.
    """
    depth = 0
    for i, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "=" and depth == 0:
            prev, nxt = text[i - 1 : i] or "", text[i + 1 : i + 2]
            if prev in "<>!" or nxt == "=":
                continue
            return text[:i].strip(), "=", text[i + 1 :].strip()
    return text.strip(), "", ""


def _parse_atom(text: str):
    """Parse a bare expression, with no relation or set handling."""
    return parse_expr(text, transformations=_TRANSFORMS, evaluate=True)


# Functions this engine is willing to evaluate. Anything else called with
# parentheses is rejected.
#:
#: The reason is not tidiness. `implicit_multiplication_application` rewrites
#: `g(a)` into `a*g` -- the name followed by a bracket becomes a product -- so
#: an undefined function silently turns into a different, valid-looking
#: expression. `g(a)` and `g(b)` then both became `a*g` and `b*g`, substituted
#: to the same value at every probe, and came back as a *proven match*. A false
#: accept, from a one-character difference in spelling. Rejecting is the only
#: honest option: nothing about `g` is known, so no verdict is available.
_KNOWN_FUNCTIONS = frozenset(
    """
    sqrt cbrt root exp log ln sin cos tan sec csc cot asin acos atan
    sinh cosh tanh asinh acosh atanh abs Abs sign floor ceiling factorial
    gamma Min Max Mod re im conjugate simplify
    """.split()
)

_CALL_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*)\s*\(")

#: Inequalities are answer forms, not expressions. `<=` reduces to its boundary
#: only if the direction is kept, and `x <= 3` and `x >= 3` share a boundary --
#: so parsing one as the other would manufacture a false match. `forms.py`
#: compares them properly as intervals.
_RELATIONAL_RE = re.compile(r"<=|>=|(?<![<>=!])[<>]")


def _reject_unsupported_shape(cleaned: str) -> None:
    for name in _CALL_RE.findall(cleaned):
        if name not in _KNOWN_FUNCTIONS:
            raise ParseRejected(
                f"undefined function {name!r}; this engine evaluates the "
                f"functions it knows and refuses to guess at the rest"
            )
    if _RELATIONAL_RE.search(cleaned):
        raise ParseRejected(
            "inequalities are compared as intervals, not as expressions; "
            "use AnswerForm.INTERVAL"
        )


@lru_cache(maxsize=8192)
def to_expr(text: str):
    """Parse allowlisted text into a comparable SymPy object.

    Cached, because parsing is the single hottest operation in the project and
    the same strings recur constantly -- step texts are re-checked per seed,
    and every test module loads the pack independently. SymPy objects are
    immutable, so sharing them is safe. Failures are not cached (lru_cache does
    not store exceptions), so a malformed input is re-parsed and rejected the
    same way every time.

    Two shapes matter for IGCSE 0580 and are handled explicitly, because
    SymPy's expression parser gets both wrong:

    - equations  `x = 3`      -> the zero-locus `x - 3`, so `x = 6/2` matches `x = 3`
    - sets       `{2, 3}`     -> a real FiniteSet, so ordering is not a difference

    Solution-set equality for quadratics (`2x = 6` versus `x = 3`) is a separate
    question and lives in `forms.py`, not here.
    """
    cleaned = normalise(text)
    if not cleaned:
        raise ParseRejected("empty input")
    _reject_unsupported_shape(cleaned)

    if cleaned.startswith("{") and cleaned.endswith("}"):
        inner = cleaned[1:-1].strip()
        if not inner:
            return sympy.FiniteSet()
        return sympy.FiniteSet(*[_parse_atom(p) for p in _split_top_level(inner)])

    lhs, op, rhs = _find_relation(cleaned)
    if op:
        return _parse_atom(lhs) - _parse_atom(rhs)

    return _parse_atom(cleaned)


# --- numeric probing --------------------------------------------------------

# Fixed probes rather than random ones: reproducible, and a benchmark that
# cannot be re-run identically is not a benchmark.
_PROBES = [
    sympy.Rational(7, 3),
    sympy.Rational(-5, 2),
    sympy.Rational(11, 4),
    sympy.Rational(-13, 6),
    sympy.Rational(17, 5),
]


def _is_finite(value: complex) -> bool:
    """Whether a complex probe result is usable evidence.

    `math.isfinite` raises on a complex, and the probe result *is* one --
    which silently turned every comparison into an exception, so every symbolic
    check fell through and spawned a subprocess. nan is not evidence of
    anything, so it has to be excluded explicitly.
    """
    return math.isfinite(value.real) and math.isfinite(value.imag)


def _numeric_probe(a, b) -> str | None:
    """Decide equality numerically where possible.

    Returns "equal", "different", or None when the probe cannot decide.

    Two soundness rules, both learned the hard way:

    * An undefined applied function (`f(x)`, `g(a)`) makes the probe unsound.
      SymPy will happily substitute a number into it and hand back something
      that compares equal, so `g(a)` and `g(b)` came back as a proven match.
      They are not: nothing is known about `g`. Bail out and let the symbolic
      path decide, which will honestly say UNKNOWN.
    * "No probe disagreed" is not "every probe agreed". If every sample point
      was inconclusive the answer is None, never "equal". Reporting equality
      from zero evidence is exactly the failure this project exists to prevent.
    """
    syms = sorted(a.free_symbols | b.free_symbols, key=lambda s: s.name)
    if not syms:
        try:
            diff = complex(sympy.N(a - b))
        except (TypeError, ValueError):
            return None
        if not _is_finite(diff):
            return None
        return "equal" if abs(diff) < 1e-12 else "different"

    if a.has(sympy.core.function.AppliedUndef) or b.has(
        sympy.core.function.AppliedUndef
    ):
        return None

    decisive = 0
    for probe in _PROBES:
        try:
            sub = dict.fromkeys(syms, probe)
            diff = complex(sympy.N((a - b).subs(sub)))
        except (TypeError, ValueError, ZeroDivisionError):
            continue  # singular or non-numeric here; try another
        if not _is_finite(diff):
            continue  # nan is not evidence of anything
        decisive += 1
        if abs(diff) > 1e-9:
            # A disagreement at a point where both sides are defined is a
            # proof of difference, not merely evidence of it.
            return "different"

    return "equal" if decisive else None


def _symbolic_decision(expected: str, given: str) -> tuple[str, str]:
    """The expensive part: decide by simplifying. Runs in a child process.

    Separated from parsing so `verify()` can do the cheap numeric comparison
    in-process and only pay for a subprocess when it genuinely cannot decide.
    """
    try:
        a = to_expr(expected)
        b = to_expr(given)
    except Exception as exc:  # noqa: BLE001
        return ("unparseable", f"could not parse: {type(exc).__name__}: {exc}")

    try:
        if sympy.simplify(a - b) == 0:
            return ("proven_equal", "simplify reduced the difference to zero")
        if a.equals(b):
            return ("proven_equal", "equals() proved identity")
    except (TypeError, ValueError, NotImplementedError):
        return ("unknown", "no proof found and symbolic comparison could not decide")

    return ("unknown", "no proof of equality or difference found")


# --- running the worker -----------------------------------------------------

DEFAULT_TIMEOUT = 5.0


def _run_symbolic(expected: str, given: str, timeout: float) -> tuple[str, str]:
    """Hand the comparison to a fresh interpreter, with a killable timeout.

    A fresh interpreter rather than a process pool, because `multiprocessing`
    with the `spawn` context re-imports the caller's `__main__` in every
    worker. A plain script calling `verify()` would then re-run itself once per
    worker, printing its output several times and returning whatever the child
    happened to compute. That was not hypothetical; it is what this replaced.
    """
    payload = json.dumps({"expected": expected, "given": given})
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "mathbeast._worker"],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ("unknown", f"timed out after {timeout}s")
    except OSError as exc:
        return ("unknown", f"could not start the comparison process: {exc}")

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        return ("unknown", f"comparison process failed: {detail[-1] if detail else 'unknown error'}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ("unknown", "comparison process returned no usable result")
    return (str(result["state"]), str(result["reason"]))


def verify(expected: str, given: str, timeout: float = DEFAULT_TIMEOUT) -> CheckResult:
    """Decide, honestly, whether `given` matches `expected`.

    Never returns a verdict stronger than it can support.
    """
    try:
        # Catch allowlist failures before paying for anything else.
        normalise(given)
        normalise(expected)
    except ParseRejected as exc:
        return CheckResult(Verdict.UNPARSEABLE, expected, given, str(exc))

    # Parsing and the numeric probe are cheap and cannot hang, so they stay
    # in-process. Most comparisons finish here.
    try:
        a = to_expr(expected)
        b = to_expr(given)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            Verdict.UNPARSEABLE, expected, given, f"could not parse: {type(exc).__name__}"
        )

    if isinstance(a, sympy.FiniteSet) or isinstance(b, sympy.FiniteSet):
        if not (isinstance(a, sympy.FiniteSet) and isinstance(b, sympy.FiniteSet)):
            return CheckResult(Verdict.PROVEN_DIFFERENT, expected, given,
                               "one side is a set and the other is not")
        if a == b:
            return CheckResult(Verdict.PROVEN_EQUAL, expected, given,
                               "sets have identical elements")
        return CheckResult(Verdict.PROVEN_DIFFERENT, expected, given, "sets differ")

    try:
        probe = _numeric_probe(a, b)
    except (TypeError, ValueError, ZeroDivisionError):
        probe = None

    if probe == "equal":
        return CheckResult(Verdict.PROVEN_EQUAL, expected, given,
                           "numeric probe agreed at every valid sample point")
    if probe == "different":
        return CheckResult(Verdict.PROVEN_DIFFERENT, expected, given,
                           "numeric probe disagreed at a valid sample point")

    state, reason = _run_symbolic(expected, given, timeout)
    return CheckResult(Verdict(state), expected, given, reason)