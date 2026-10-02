"""CLI surface: the thing most people will actually touch."""

from __future__ import annotations

import json

import pytest

from mathbeast.cli import main


def run(capsys, *argv: str) -> str:
    assert main(list(argv)) == 0
    return capsys.readouterr().out


# --- listing and coverage ---------------------------------------------------


def test_skills_lists_the_pack(capsys) -> None:
    out = run(capsys, "skills")
    assert "0580.c1.1.squares" in out
    assert "skill(s)" in out


def test_skills_json_is_machine_readable(capsys) -> None:
    out = run(capsys, "skills", "--json")
    rows = json.loads(out)
    assert rows and all("syllabus" in row for row in rows)


def test_skills_can_filter_by_tier(capsys) -> None:
    out = run(capsys, "skills", "--tier", "extended", "--json")
    rows = json.loads(out)
    assert rows and all(row["tier"] == "extended" for row in rows)


def test_a_skill_can_be_named_by_slug(capsys) -> None:
    out = run(capsys, "skills", "pythagoras", "--json")
    rows = json.loads(out)
    assert rows and all("pythagoras" in row["id"] for row in rows)


def test_a_slug_prefix_beats_a_mid_string_match(capsys) -> None:
    """`sin` must not drag in `probability_single`.

    A plain substring search returned both, and the command then picked one at
    random -- usually the wrong one.
    """
    rows = json.loads(run(capsys, "skills", "sin", "--json"))
    assert [row["id"] for row in rows] == ["0580.c6.1.sin_angle"]


def test_an_exact_id_wins_outright(capsys) -> None:
    rows = json.loads(run(capsys, "skills", "0580.c7.1.probability_single", "--json"))
    assert len(rows) == 1


def test_coverage_groups_by_section(capsys) -> None:
    out = run(capsys, "coverage")
    assert "0580 pack:" in out
    assert "C1" in out and "C9" in out


# --- explain ----------------------------------------------------------------


def test_explain_shows_verified_working_offline(capsys) -> None:
    out = run(capsys, "explain", "expand_quadratic", "--seed", "1")
    assert "Verified answer:" in out
    assert "Explanation (offline)" in out
    assert "Grounding: grounded" in out


def test_explain_never_claims_a_model_it_did_not_use(capsys) -> None:
    out = run(capsys, "explain", "expand_quadratic", "--seed", "1")
    assert "ollama" not in out.lower().split("explanation")[0]


def test_explain_degrades_when_ollama_is_absent(capsys, monkeypatch) -> None:
    """No real socket: waiting out the real timeout would cost 4 seconds."""
    import mathbeast.cli as cli
    import mathbeast.narrate as narrate

    class Refusing(narrate.OllamaNarrator):
        def _call(self, prompt: str) -> str:
            raise ConnectionRefusedError("no server on that port")

    monkeypatch.setattr(cli, "OllamaNarrator", Refusing)
    out = run(capsys, "explain", "expand_quadratic", "--seed", "1", "--narrator", "ollama")
    assert "model unavailable" in out
    assert "Verified answer:" in out


# --- drill ------------------------------------------------------------------


def test_drill_judges_a_correct_answer(capsys, monkeypatch) -> None:
    from mathbeast.skill import load

    problem = load(
        __import__("pathlib").Path(__file__).parent.parent
        / "mathbeast" / "skills" / "0580.c1.1.squares.yaml"
    ).generate(0)
    monkeypatch.setattr("builtins.input", lambda *_: problem.answer)
    out = run(capsys, "drill", "squares", "--count", "1", "--seed", "5")
    assert "verified correct" in out


def test_drill_reports_an_incorrect_answer_without_lying(capsys, monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda *_: "999999")
    out = run(capsys, "drill", "squares", "--count", "1", "--seed", "5")
    assert "not quite" in out
    assert "0/1 verified correct" in out


def test_drill_reveals_the_answer_when_skipped(capsys, monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda *_: "")
    out = run(capsys, "drill", "squares", "--count", "1", "--seed", "5")
    assert "-> answer:" in out


def test_drill_stops_on_quit(capsys, monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda *_: "q")
    out = run(capsys, "drill", "squares", "--count", "5", "--seed", "5")
    assert "0/5 verified correct" in out


# --- bench ------------------------------------------------------------------


def test_bench_reports_a_floor_and_says_it_is_not_the_measurement(capsys) -> None:
    """It must not present the offline floor as if it were the benchmark."""
    out = run(capsys, "bench", "--per-skill", "1")
    assert "problems sampled:" in out
    assert "This is the floor, not the measurement" in out


# --- failure modes ----------------------------------------------------------


def test_an_unknown_skill_exits_cleanly() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["explain", "no-such-skill"])
    assert "no skill matches" in str(excinfo.value)


def test_a_missing_subcommand_is_an_error() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_console_is_forced_to_utf8(capsys) -> None:
    """The pack contains √, × and °; a cp1252 console would crash on them."""
    import sys

    assert getattr(sys.stdout, "encoding", "").lower().replace("-", "") in (
        "utf8",
        "utf8sig",
    )
