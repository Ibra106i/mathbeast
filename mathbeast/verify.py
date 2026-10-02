"""Form-aware verification with an honest four-state answer.

SymPy's ``simplify`` can hang indefinitely, and it returns ``False`` for
expressions that are true but not provable. A boolean checker therefore lies in
two directions: it marks correct answers wrong, and it cannot distinguish
"wrong" from "I gave up".

Everything here returns one of four states. ``UNKNOWN`` is deliberately not
``PROVEN_DIFFERENT``.
"""

from __future__ import annotations

import re
import unicodedata
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from multiprocessing import get_context

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

    # Reject before NFKC, not after. NFKC rewrites `x³` to `x3`, which parses as
    # x*3 -- silently turning a typo into a confidently wrong comparison. A
    # rejection is recoverable; a misread is the exact bug this project exists
    # to prevent. Covers superscripts, vulgar fractions and Roman numerals.
    for ch in text:
        if unicodedata.category(ch) in ("No", "Nl"):
            raise ParseRejected(
                f"character {ch!r} (U+{ord(ch):04X}) is not supported; "
                "write it out, e.g. x^3 not x³"
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


def _numeric_probe(a, b) -> str | None:
    """Decide equality numerically where possible.

    Returns "equal", "different", or None when the probe is inconclusive (a
    singularity, or a non-numeric constant).
    """
    syms = sorted(a.free_symbols | b.free_symbols, key=lambda s: s.name)
    if not syms:
        try:
            diff = complex(sympy.N(a - b))
        except (TypeError, ValueError):
            return None
        return "equal" if abs(diff) < 1e-12 else "different"

    for probe in _PROBES:
        try:
            sub = dict.fromkeys(syms, probe)
            diff = complex(sympy.N((a - b).subs(sub)))
        except (TypeError, ValueError, ZeroDivisionError):
            continue  # singular or non-numeric at this probe; try another
        if abs(diff) > 1e-9:
            # A disagreement at a point where both sides are defined is a
            # proof of difference, not merely evidence of it.
            return "different"
    return "equal"


def _compare_worker(expected: str, given: str) -> tuple[str, str]:
    """Run inside the worker process. Returns (state, reason)."""
    # The allowlist in `normalise` has already run, so nothing reaching this
    # point is untrusted code -- it is validated text that may still be
    # syntactically wrong. SymPy signals that through a wide and undocumented
    # spread of exception types (SyntaxError, TokenError, IndexError, ...), so
    # enumerating them is brittle; every failure to parse is the same verdict.
    try:
        a = to_expr(expected)
        b = to_expr(given)
    except Exception as exc:  # noqa: BLE001
        return ("unparseable", f"could not parse: {type(exc).__name__}: {exc}")

    if isinstance(a, sympy.FiniteSet) or isinstance(b, sympy.FiniteSet):
        if not (isinstance(a, sympy.FiniteSet) and isinstance(b, sympy.FiniteSet)):
            return ("proven_different", "one side is a set and the other is not")
        if a == b:
            return ("proven_equal", "sets have identical elements")
        return ("proven_different", "sets differ")

    try:
        probe = _numeric_probe(a, b)
    except (TypeError, ValueError, ZeroDivisionError):
        probe = None

    if probe == "equal":
        return ("proven_equal", "numeric probe agreed at every valid sample point")
    if probe == "different":
        return ("proven_different", "numeric probe disagreed at a valid sample point")

    try:
        if sympy.simplify(a - b) == 0:
            return ("proven_equal", "simplify reduced the difference to zero")
        if a.equals(b):
            return ("proven_equal", "equals() proved identity")
    except (TypeError, ValueError, NotImplementedError):
        return ("unknown", "no proof found and symbolic comparison could not decide")

    return ("unknown", "no proof of equality or difference found")


# --- timeout ----------------------------------------------------------------

# SymPy's simplify can run forever. A thread cannot be killed, so this uses a
# process, which works identically on Windows and Linux. On timeout the pool is
# destroyed and rebuilt, because the stuck worker never comes back.
DEFAULT_TIMEOUT = 5.0
_POOL: ProcessPoolExecutor | None = None


def _pool() -> ProcessPoolExecutor:
    global _POOL
    if _POOL is None:
        _POOL = ProcessPoolExecutor(
            max_workers=2, mp_context=get_context("spawn")
        )
    return _POOL


def _reset_pool() -> None:
    global _POOL
    if _POOL is not None:
        _POOL.shutdown(wait=False, cancel_futures=True)
        _POOL = None


def verify(expected: str, given: str, timeout: float = DEFAULT_TIMEOUT) -> CheckResult:
    """Decide, honestly, whether `given` matches `expected`.

    Never returns a verdict stronger than it can support.
    """
    try:
        # Catch allowlist failures before paying for a subprocess.
        normalise(given)
        normalise(expected)
    except ParseRejected as exc:
        return CheckResult(Verdict.UNPARSEABLE, expected, given, str(exc))

    try:
        future = _pool().submit(_compare_worker, expected, given)
        state, reason = future.result(timeout=timeout)
    except FutureTimeout:
        _reset_pool()
        return CheckResult(
            Verdict.UNKNOWN, expected, given, f"timed out after {timeout}s"
        )
    except Exception as exc:  # noqa: BLE001 - never let verification crash a drill
        return CheckResult(Verdict.UNKNOWN, expected, given, f"{type(exc).__name__}: {exc}")

    return CheckResult(Verdict(state), expected, given, reason)