"""The guarantee is about the answer; this is what extends it to the method."""

from __future__ import annotations

import pytest

from mathbeast.prose import (
    check_narration,
    extract_claims,
    narrate_offline,
)
from mathbeast.skill import load
from pathlib import Path

SKILL = Path(__file__).parent.parent / "mathbeast" / "skills" / "0580.c2.10.expand_quadratic.yaml"


@pytest.fixture()
def problem():
    return load(SKILL).generate(1)  # Expand (x + 3)(x + 10) -> x**2 + 13*x + 30


# --- claim extraction --------------------------------------------------------


def test_english_is_not_mathematics() -> None:
    """The over-eager-extractor failure mode that would void the metric."""
    text = "Multiply the brackets and collect like terms."
    assert extract_claims(text) == []


def test_digits_and_operators_are_claims() -> None:
    claims = extract_claims("The coefficient of x is 13, so we get x**2 + 30.")
    assert "13" in claims
    assert any("x**2" in c or "x^2" in c for c in claims)


def test_ordinary_words_never_become_symbols() -> None:
    for word in ("the", "multiply", "brackets", "terms", "so", "if"):
        assert extract_claims(word) == []


def test_a_prose_prefix_is_stripped_from_a_claim() -> None:
    """"Replace every x with -4" must yield "-4", never "with -4".

    Reporting the English word as an unsupported claim is the false accusation
    that would make this module useless as a measurement.
    """
    assert extract_claims("Replace every x with -4.") == ["-4"]
    assert "with" not in " ".join(extract_claims("Substitute -6 for the value."))


# --- binding ----------------------------------------------------------------


def test_offline_narration_is_always_grounded(problem) -> None:
    report = check_narration(problem, narrate_offline(problem))
    assert report.ok
    assert report.unsupported_rate == 0.0


def test_narration_must_cover_every_step(problem) -> None:
    report = check_narration(problem, [(0, "the first step only")])
    assert not report.bound
    assert "no narration for step" in report.summary()


def test_narration_may_not_invent_a_step(problem) -> None:
    lines = narrate_offline(problem) + [(99, "and therefore the answer is 42")]
    report = check_narration(problem, lines)
    assert not report.bound
    assert "unverified step" in report.summary()


def test_narration_may_not_reorder_steps(problem) -> None:
    lines = narrate_offline(problem)
    lines[0], lines[1] = lines[1], lines[0]
    assert not check_narration(problem, lines).bound


def test_empty_narration_is_unbound(problem) -> None:
    assert not check_narration(problem, []).bound


# --- grounding --------------------------------------------------------------


def test_a_fabricated_number_is_caught(problem) -> None:
    """Right answer, invented arithmetic -- the failure the guarantee must catch."""
    lines = narrate_offline(problem)
    lines[1] = (1, "Collect the x terms: 3 + 10 = 17, so the coefficient is 17.")
    report = check_narration(problem, lines)
    assert report.unsupported
    assert not report.ok
    assert "17" in report.summary()


def test_equivalent_restatements_are_accepted(problem) -> None:
    """The check is semantic, not textual.

    `x**2 + 3x + 10x + 30` is the uncollected form of the verified answer
    `x**2 + 13*x + 30`. It is a legitimate intermediate step, so accepting it is
    correct -- flagging it would make the checker useless on real narration.
    """
    lines = narrate_offline(problem)
    lines[0] = (0, "Multiply out to get x**2 + 3x + 10x + 30.")
    assert check_narration(problem, lines).unsupported_rate == 0.0


def test_a_non_equivalent_intermediate_is_caught(problem) -> None:
    """A plausible step that the verified record does not contain."""
    lines = narrate_offline(problem)
    lines[0] = (0, "Multiply out to get x**2 + 3x + 10x + 30, and the discriminant is 121.")
    report = check_narration(problem, lines)
    assert report.unsupported
    assert not report.ok


def test_restating_the_verified_answer_is_supported(problem) -> None:
    lines = narrate_offline(problem)
    lines[0] = (0, f"The expansion is {problem.answer}.")
    assert check_narration(problem, lines).unsupported_rate == 0.0


def test_numeric_atoms_of_the_answer_are_supported(problem) -> None:
    lines = narrate_offline(problem)
    atoms = [str(a) for a in __import__("sympy").sympify(problem.answer).atoms(__import__("sympy").Number)]
    lines[0] = (0, "The numbers involved are " + ", ".join(atoms) + ".")
    assert check_narration(problem, lines).unsupported_rate == 0.0


def test_unsupported_rate_is_a_proportion(problem) -> None:
    """The benchmark metric must be a number, in [0, 1], that rises with errors."""
    clean = check_narration(problem, narrate_offline(problem))
    assert clean.unsupported_rate == 0.0

    dirty = narrate_offline(problem)
    dirty[0] = (0, "Expanding gives x**2 + 3x + 10x + 987654.")
    polluted = check_narration(problem, dirty)
    assert 0.0 < polluted.unsupported_rate <= 1.0
    assert polluted.unsupported_rate > clean.unsupported_rate


def test_report_is_informative_when_clean(problem) -> None:
    report = check_narration(problem, narrate_offline(problem))
    assert "grounded" in report.summary()