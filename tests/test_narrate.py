"""The narrator is the only component allowed to be wrong, so its binding is tested hardest."""

from __future__ import annotations

from pathlib import Path

import pytest

from mathbeast.narrate import (
    SYSTEM_PROMPT,
    OfflineNarrator,
    OllamaNarrator,
    _parse_lines,
    narrate_and_check,
)
from mathbeast.skill import load

SKILL = Path(__file__).parent.parent / "mathbeast" / "skills" / "0580.c2.10.expand_quadratic.yaml"


@pytest.fixture()
def problem():
    return load(SKILL).generate(1)


# --- offline ----------------------------------------------------------------


def test_offline_narrator_covers_every_step(problem) -> None:
    lines = OfflineNarrator().narrate(problem)
    assert [step_id for step_id, _ in lines] == [s.index for s in problem.steps]


def test_offline_narration_is_grounded(problem) -> None:
    _, report = narrate_and_check(OfflineNarrator(), problem)
    assert report.ok
    assert report.unsupported_rate == 0.0


# --- binding ----------------------------------------------------------------


def test_a_well_formed_reply_binds(problem) -> None:
    raw = (
        "0. Multiply out each bracket in turn.\n"
        "1. Collect the x terms to get 13.\n"
        "2. The constant term is 30."
    )
    parsed = _parse_lines(raw, problem)
    assert parsed is not None
    assert [pid for pid, _ in parsed] == [0, 1, 2]


@pytest.mark.parametrize(
    "raw",
    [
        "0. Only the first step.",                       # too few
        "0. One.\n1. Two.\n2. Three.\n3. Four.",          # too many
        "0. One.\n2. Two.\n1. Three.",                    # wrong ids, right count
        "1. One.\n0. Two.\n2. Three.",                    # out of order
        "nothing numeric here at all",                    # unparseable
        "",                                               # empty
    ],
)
def test_an_unbindable_reply_is_rejected(problem, raw: str) -> None:
    assert _parse_lines(raw, problem) is None


def test_reply_with_a_step_renumbered_is_rejected(problem) -> None:
    """A model that restarts its numbering must not be silently accepted."""
    assert _parse_lines("1. One.\n2. Two.\n3. Three.", problem) is None


# --- degradation ------------------------------------------------------------


def test_ollama_degrades_when_the_server_is_absent(problem, monkeypatch) -> None:
    """No real socket: a refused connection would cost the real timeout."""
    narrator = OllamaNarrator(model="definitely-not-pulled")

    def refuse(prompt: str) -> str:
        raise ConnectionRefusedError("no server on that port")

    monkeypatch.setattr(narrator, "_call", refuse)
    lines, report = narrate_and_check(narrator, problem)
    assert narrator.degraded, "should record why it fell back"
    assert "ConnectionRefusedError" in narrator.degraded
    assert report.ok
    assert [pid for pid, _ in lines] == [s.index for s in problem.steps]


def test_ollama_degrades_when_the_reply_is_unbindable(problem, monkeypatch) -> None:
    narrator = OllamaNarrator(model="stub")
    monkeypatch.setattr(narrator, "_call", lambda prompt: "I cannot help with that.")
    lines, report = narrate_and_check(narrator, problem)
    assert "bound" in (narrator.degraded or "")
    assert report.ok
    assert len(lines) == len(problem.steps)


def test_ollama_uses_a_bound_reply_when_valid(problem, monkeypatch) -> None:
    narrator = OllamaNarrator(model="stub")
    reply = "0. Multiply out.\n1. Collect terms.\n2. Multiply out the constants."
    monkeypatch.setattr(narrator, "_call", lambda prompt: reply)
    lines, report = narrate_and_check(narrator, problem)
    assert narrator.degraded is None
    assert [pid for pid, _ in lines] == [0, 1, 2]


def test_system_prompt_forbids_unverified_numbers() -> None:
    lowered = SYSTEM_PROMPT.lower()
    assert "never state a number" in lowered
    assert "one line per step" in lowered


def test_narrator_never_receives_free_text_problem_to_parse(problem, monkeypatch) -> None:
    """It is handed steps, not the problem, so there is nothing to misparse."""
    narrator = OllamaNarrator(model="stub")
    seen: list[str] = []

    def capture(prompt: str) -> str:
        seen.append(prompt)
        return "0. a\n1. b\n2. c"

    monkeypatch.setattr(narrator, "_call", capture)
    narrator.narrate(problem)
    assert seen and problem.statement in seen[0]
    for step in problem.steps:
        assert step.text in seen[0]
