"""The checker must never claim more than it knows."""

from __future__ import annotations

import pytest

from mathbeast.verify import ParseRejected, Verdict, normalise, to_expr, verify


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("x=3", "x = 3"),          # whitespace is not a difference
        ("x = 6/2", "x = 3"),      # arithmetic, not string identity
        ("2x+2x", "4*x"),          # implicit multiplication
        ("(x+1)^2", "(x+1)**2"),   # caret normalised
        ("\u22125", "-5"),              # unicode minus
        ("2\u00d7\u03c0", "2*pi"),       # unicode times and pi
        ("x\u22643", "x<=3"),            # unicode less-or-equal
        ("{2, 3}", "{3, 2}"),            # set equality is order-free
    ],
)
def test_proven_equal(given: str, expected: str) -> None:
    assert verify(expected, given).verdict is Verdict.PROVEN_EQUAL


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("x=4", "x=3"),
        ("2x", "3x"),
        ("1/2", "2/3"),
        ("x^2", "x^3"),
    ],
)
def test_proven_different(given: str, expected: str) -> None:
    assert verify(expected, given).verdict is Verdict.PROVEN_DIFFERENT


@pytest.mark.parametrize(
    "hostile",
    [
        "__import__('os').system('echo hi')",
        "x + __builtins__",
        "lambda: 1",
        "open('/etc/passwd')",
        "x; import os",
        "x³",  # superscript three is outside the allowlist
    ],
)
def test_hostile_input_is_unparseable_never_executed(hostile: str) -> None:
    result = verify("1", hostile)
    assert result.verdict is Verdict.UNPARSEABLE


@pytest.mark.parametrize("junk", ["", "   ", ")", "((", "1 +"])
def test_malformed_is_unparseable_not_a_crash(junk: str) -> None:
    assert verify("1", junk).verdict is Verdict.UNPARSEABLE


def test_unknown_is_distinct_from_wrong() -> None:
    """The whole point of the four states: a timeout is not a wrong answer."""
    result = verify("x", "some_unprovable_thing(x)", timeout=0.001)
    assert result.verdict in (Verdict.UNKNOWN, Verdict.PROVEN_DIFFERENT)
    assert result.verdict is not Verdict.PROVEN_EQUAL
    assert result.is_correct is False


def test_is_correct_only_on_proven_equal() -> None:
    assert verify("5", "5").is_correct is True
    assert verify("5", "6").is_correct is False
    assert verify("5", "!!!").is_correct is False


def test_normalise_rejects_before_parsing() -> None:
    with pytest.raises(ParseRejected):
        normalise("__import__")
    with pytest.raises(ParseRejected):
        to_expr("os.system")


def test_result_string_is_informative() -> None:
    assert "proven_equal" in str(verify("2x", "x+x"))


def test_verifier_survives_a_nonsense_timeout() -> None:
    """A pathological timeout must still return a four-state answer, not raise."""
    result = verify("x + 1", "x + 1", timeout=0.0001)
    assert result.verdict in tuple(Verdict)