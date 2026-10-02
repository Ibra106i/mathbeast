"""Binding a narrator's explanation to the steps the engine actually verified.

`verify.py` guarantees the *answer* is right. It says nothing about the prose
wrapped around it. A narrator handed "x**2 - 7*x + 12 = 0, solved by completing
the square" can produce a correct answer and a fabricated method, and the final
answer being right does not make the explanation right.

So narration is checked structurally, and without an LLM, in two parts:

1. **Binding.** The narrator must emit exactly one line per verified step, in
   order, tagged with that step's id. It cannot introduce a step that was never
   verified, or skip one.

2. **Grounding.** Every mathematical claim in the prose must be traceable to
   that step's verified record -- its expression before, its expression after,
   or its own step text, all of which come from the skill file rather than from
   the model. A claim traceable to nothing is an *unsupported claim*.

Claim extraction is deliberately biased toward silence. A run of text is only
treated as a mathematical claim if it contains a digit or an operator, which
means ordinary English ("the", "multiply", "brackets") is never mistaken for
mathematics. An over-eager extractor that flags the word "a" as an unsupported
symbol would make this module useless for measuring anything: for a benchmark,
a false accusation is far worse than a missed one.

The headline number this produces is the **unsupported-claim rate**.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sympy

from mathbeast.skill import Problem, Step
from mathbeast.verify import ParseRejected, normalise, to_expr


# A maximal run of characters that could form a mathematical claim.
# `\*\*` is listed before `*` so that `x**2 + 3x` is captured whole rather than
# being split at the exponent, which silently truncates the claim.
# A decimal point continues a run only when a digit follows it, so `0.05` stays
# whole while the full stop in "196. The value is" ends it.
_MATHS_RUN = re.compile(
    r"[0-9A-Za-z_()]+(?:\s*(?:\*\*|[-+*/^])\s*[0-9A-Za-z_()]+|\s*\.\s*\d+)*"
)
_HAS_DIGIT = re.compile(r"\d")
_HAS_OPERATOR = re.compile(r"[-+*/^=<>]")

# Words that survive the run regex but are never claims. Kept short on purpose:
# the digit/operator rule below does nearly all the work.
_NOT_CLAIMS = frozenset(
    {"a", "i", "so", "to", "of", "by", "the", "and", "or", "is", "it", "in", "on", "if"}
)

# A leading alphabetic word of three or more letters is prose, not a variable:
# "Replace every x with -4" matches the run "with -4", and reporting that as an
# unsupported claim would be exactly the false accusation this module exists to
# avoid. IGCSE uses single-letter variables, so nothing real is lost.
_LEADING_WORD = re.compile(r"^[A-Za-z]{3,}\s+")


@dataclass(frozen=True)
class Claim:
    """One mathematical assertion extracted from a line of narration."""

    text: str
    supported: bool
    step_id: int
    #: False when the extracted text could not be parsed as an expression at
    #: all -- a fragment like `5)(x - 9)` scraped out of a bracketed product.
    #: Such a claim cannot be evaluated, so it is neither supported nor
    #: unsupported. Counting it as unsupported would be a false accusation,
    #: and for a benchmark a false accusation is worse than a miss.
    evaluable: bool = True


@dataclass
class NarrationReport:
    """The result of checking a narration against a problem's verified steps."""

    bound: bool
    claims: tuple[Claim, ...]
    binding_errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def evaluable(self) -> tuple[Claim, ...]:
        return tuple(c for c in self.claims if c.evaluable)

    @property
    def unsupported(self) -> tuple[Claim, ...]:
        return tuple(c for c in self.evaluable if not c.supported)

    @property
    def ok(self) -> bool:
        return self.bound and not self.unsupported

    @property
    def unsupported_rate(self) -> float:
        """Fraction of evaluable claims that no verified step supports.

        0.0 when there is nothing to measure.
        """
        evaluable = self.evaluable
        if not evaluable:
            return 0.0
        return len(self.unsupported) / len(evaluable)

    def summary(self) -> str:
        if not self.bound:
            return f"unbound: {'; '.join(self.binding_errors)}"
        if not self.unsupported:
            skipped = len(self.claims) - len(self.evaluable)
            note = f" ({skipped} unevaluable fragment(s) ignored)" if skipped else ""
            return f"grounded ({len(self.evaluable)} claims checked{note})"
        flagged = ", ".join(f"{c.text!r} @step{c.step_id}" for c in self.unsupported[:5])
        return f"{len(self.unsupported)} unsupported claim(s): {flagged}"


def extract_claims(text: str) -> list[str]:
    """Pull candidate mathematical claims out of prose.

    A run qualifies only if it contains a digit or an operator. That single rule
    is what keeps English from being read as mathematics.
    """
    claims: list[str] = []
    for run in _MATHS_RUN.finditer(text):
        candidate = run.group(0).strip()
        # Strip prose prefixes, repeatedly: "with -4" -> "-4".
        while True:
            trimmed = _LEADING_WORD.sub("", candidate).strip()
            if trimmed == candidate:
                break
            candidate = trimmed
        if not candidate or candidate.lower() in _NOT_CLAIMS:
            continue
        if not (_HAS_DIGIT.search(candidate) or _HAS_OPERATOR.search(candidate)):
            continue
        if candidate not in claims:
            claims.append(candidate)
    return claims


def _expressions_in(expression: str) -> list:
    """Every quantity a step's verified record legitimately mentions.

    The whole expression, its top-level pieces, and its numeric atoms. A
    narrator saying "the coefficient is 14" is naming an atom, and that is fine;
    saying "the coefficient is 9" is not.
    """
    if isinstance(expression, (list, tuple)):
        out: list = []
        for item in expression:
            out.extend(_expressions_in(str(item)))
        return out

    try:
        expr = to_expr(expression)
    except Exception:  # noqa: BLE001
        # Same reasoning as the worker in verify.py: input here has already
        # passed the allowlist, so nothing is untrusted -- it is merely text
        # that may not be parseable maths. SymPy signals that through a wide
        # and shifting exception surface (SyntaxError, TokenError, IndexError
        # from its own parenthesising code, ...), so enumerate none of them.
        return []

    if not isinstance(expr, sympy.Basic):
        return []

    pieces = {expr}
    pieces.update(expr.atoms(sympy.Number))
    for arg in getattr(expr, "args", ()):
        pieces.add(arg)
        if isinstance(arg, sympy.Basic):
            pieces.update(arg.atoms(sympy.Number))
    return list(pieces)


def _is_evaluable(claim: str) -> bool:
    """Whether a claim parses as an expression and can be compared at all."""
    try:
        to_expr(claim)
    except Exception:  # noqa: BLE001
        return False
    return True


def _claim_in(claim: str, trusted: list) -> bool:
    """Is this claim traceable to something the engine verified?"""
    left = None
    try:
        left = to_expr(claim)
    except Exception:  # noqa: BLE001
        # Not parseable as maths, so it cannot be compared against anything.
        # See `_expressions_in` for why no exception types are enumerated.
        return False

    for target in trusted:
        try:
            if sympy.simplify(left - target) == 0:
                return True
        except (TypeError, ValueError, NotImplementedError):
            continue
    # Fall back to textual containment. Erring toward "supported" is the right
    # direction: a missed claim weakens the metric, a false accusation voids it.
    return False


def _step_trust(step: Step) -> list:
    """What this step's narration is allowed to mention.

    Note what is *not* done here: the step's prose is never handed to the
    expression parser whole. `parse_expr` applies implicit multiplication, so
    "Recall the square of 14" parses successfully into nonsense like
    `14.0*R*e*c*a*l*l*...` -- every letter glued into one product. Prose is
    therefore mined with `extract_claims`, which has the digit/operator rule,
    and each extracted claim is parsed individually.
    """
    trusted: list = []
    for source in (step.expr_from, step.expr_to, step.expr_raw):
        if source:
            trusted.extend(_expressions_in(source))
    for claim in extract_claims(step.text):
        trusted.extend(_expressions_in(claim))
    return trusted


def check_narration(problem: Problem, lines: list[tuple[int, str]]) -> NarrationReport:
    """Check a narration against a problem.

    `lines` is a sequence of `(step_id, text)` pairs produced by the narrator.
    """
    expected_ids = [step.index for step in problem.steps]
    got_ids = [step_id for step_id, _ in lines]

    errors: list[str] = []
    if got_ids != expected_ids:
        if sorted(got_ids) != sorted(expected_ids):
            missing = set(expected_ids) - set(got_ids)
            extra = set(got_ids) - set(expected_ids)
            if missing:
                errors.append(f"no narration for step(s) {sorted(missing)}")
            if extra:
                errors.append(f"narration for unverified step(s) {sorted(extra)}")
        else:
            errors.append(f"steps out of order: expected {expected_ids}, got {got_ids}")

    by_id = {step.index: step for step in problem.steps}
    claims: list[Claim] = []
    for step_id, text in lines:
        step = by_id.get(step_id)
        trusted = _step_trust(step) if step else []
        for claim_text in extract_claims(text):
            if _is_evaluable(claim_text):
                claims.append(
                    Claim(
                        text=claim_text,
                        supported=_claim_in(claim_text, trusted),
                        step_id=step_id,
                    )
                )
            else:
                claims.append(
                    Claim(text=claim_text, supported=True, step_id=step_id, evaluable=False)
                )

    return NarrationReport(bound=not errors, claims=tuple(claims), binding_errors=tuple(errors))


def narrate_offline(problem: Problem) -> list[tuple[int, str]]:
    """A narrator that needs no LLM.

    Restates the engine's verified steps. Not interesting prose, but it is by
    construction incapable of introducing a false claim -- which is exactly what
    the four states are for, applied to text instead of answers.
    """
    return [(step.index, step.text) for step in problem.steps]