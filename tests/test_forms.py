"""Answer forms decide *which question* is being asked.

The asymmetry between `exact` and `rounded` is the whole point of this module,
and it is asserted in both directions so it cannot silently regress.
"""

from __future__ import annotations

import pytest

from mathbeast.forms import (
    AnswerForm,
    check,
    check_rounded,
    check_set,
    sig_figs_round,
)
from mathbeast.verify import Verdict


# --- the headline requirement: 3 s.f. behaviour ----------------------------


@pytest.mark.parametrize(
    ("given", "expected", "spec"),
    [
        ("14.1", "14.14213562", "3sf"),   # correctly rounded
        ("14.142", "14.14213562", "3sf"),  # over-precise but agrees at 3sf
        ("14.1421", "14.14213562", "3sf"),
    ],
)
def test_rounded_accepts_over_precision(given, expected, spec) -> None:
    """Handing back more digits than asked is not a mathematical error."""
    assert check_rounded(expected, given, spec).verdict is Verdict.PROVEN_EQUAL


@pytest.mark.parametrize("given", ["14.2", "14.0", "141"])
def test_rounded_rejects_a_different_value(given) -> None:
    assert check_rounded("14.14213562", given, "3sf").verdict is Verdict.PROVEN_DIFFERENT


def test_exact_rejects_what_rounded_accepts() -> None:
    """The other direction of the asymmetry: exact really is exact."""
    rounded_ok = check_rounded("14.14213562", "14.1", "3sf")
    exact_bad = check("14.14213562", "14.1", AnswerForm.EXACT)
    assert rounded_ok.verdict is Verdict.PROVEN_EQUAL
    assert exact_bad.verdict is Verdict.PROVEN_DIFFERENT


def test_decimal_places_differs_from_significant_figures() -> None:
    """3sf and 2dp are different questions and must not be conflated."""
    # 1234.5 -> 3sf is 1230; 2dp is 1234.50
    assert check_rounded("1234.5", "1230", "3sf").verdict is Verdict.PROVEN_EQUAL
    assert check_rounded("1234.5", "1234.50", "2dp").verdict is Verdict.PROVEN_EQUAL
    assert check_rounded("1234.5", "1230", "2dp").verdict is Verdict.PROVEN_DIFFERENT


def test_sig_figs_round_basics() -> None:
    import sympy

    # sig_figs_round returns a float, so compare numerically.
    assert float(sig_figs_round(sympy.Float("1234.5"), 3)) == 1230.0
    assert float(sig_figs_round(sympy.Float("0.0004567"), 2)) == 0.00046
    assert float(sig_figs_round(sympy.Integer(0), 3)) == 0.0


def test_rounded_rejects_symbolic_answers() -> None:
    """Asking for a number and getting an expression is not a rounding failure."""
    assert (
        check_rounded("14.1", "x + 2", "3sf").verdict is Verdict.UNPARSEABLE
    )


@pytest.mark.parametrize("spec", ["", "3", "three sf", "0sf", None])
def test_bad_precision_spec_is_unparseable(spec) -> None:
    result = check_rounded("14.1", "14.1", spec or "")
    assert result.verdict is Verdict.UNPARSEABLE


# --- solution sets -----------------------------------------------------------


def test_equivalent_routes_to_the_same_answer_agree() -> None:
    """The case phase 2 deferred: 2x = 6 and x = 3 denote the same solution."""
    assert check_set("2x = 6", "x = 3").verdict is Verdict.PROVEN_EQUAL
    assert check_set("x = 3", "3").verdict is Verdict.PROVEN_EQUAL


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("2, 3", "3, 2"),            # order-free
        ("{2, 3}", "{2, 3}"),        # braces optional
        ("x=2 or x=3", "{2, 3}"),    # stated as solutions
    ],
)
def test_set_accepts_the_usual_spellings(given, expected) -> None:
    assert check_set(expected, given).verdict is Verdict.PROVEN_EQUAL


def test_set_is_order_free_but_not_membership_free() -> None:
    assert check_set("{2, 3}", "{2, 3, 4}").verdict is Verdict.PROVEN_DIFFERENT


def test_set_with_a_different_variable() -> None:
    assert check_set("2y = 6", "y = 3", spec="y").verdict is Verdict.PROVEN_EQUAL


# --- intervals ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [("[0,5]", "[0,5]"), ("0<=x<=5", "[0,5]"), ("[0,5)", "[0,5)"), ("0<x<5", "(0,5)")],
)
def test_interval_equivalences(given, expected) -> None:
    assert check(expected, given, AnswerForm.INTERVAL).verdict is Verdict.PROVEN_EQUAL


def test_interval_endpoints_are_significant() -> None:
    from mathbeast.forms import check_interval

    assert check_interval("[0,5]", "[0,5)").verdict is Verdict.PROVEN_DIFFERENT
    assert check_interval("[0,5]", "0<=x<=5").verdict is Verdict.PROVEN_EQUAL


def test_unknown_form_spec_raises_loudly() -> None:
    with pytest.raises(ValueError):
        check("1", "1", "not-a-form")  # type: ignore[arg-type]