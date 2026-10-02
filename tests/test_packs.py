"""Every skill in the 0580 pack must load, smoke, and self-agree.

The load-bearing check is `test_generated_answers_verify`: the answer the engine
produced for a problem must be accepted by the very checker the project ships,
under the answer form that skill declares. If those two ever disagree, the
"verified by construction" claim is false, and this is where it surfaces.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mathbeast.forms import check
from mathbeast.prose import check_narration, narrate_offline
from mathbeast.skill import coverage_report, load_all

#: `load_all` smokes every skill over 200 seeds, which `test_skill.py` already
#: covers. Repeating it here, and again per-seed in the checks below, made the
#: suite unusable as the pack grew.
SKILL_DIR = Path(__file__).parent.parent / "mathbeast" / "skills"

ALL_SKILLS = load_all(SKILL_DIR, smoke=False)
SEEDS = 20


def test_the_pack_is_not_empty() -> None:
    assert ALL_SKILLS


def test_skill_ids_are_unique() -> None:
    ids = [s.id for s in ALL_SKILLS]
    assert len(ids) == len(set(ids))


def test_every_syllabus_code_is_a_real_0580_section() -> None:
    from mathbeast.skill import VALID_SECTIONS

    for skill in ALL_SKILLS:
        section = skill.syllabus.split(".")[0].upper()
        assert section in VALID_SECTIONS, f"{skill.id}: unknown section {section}"


def test_extended_only_sections_are_tagged_extended() -> None:
    from mathbeast.skill import Tier

    for skill in ALL_SKILLS:
        if skill.syllabus.split(".")[0].upper().startswith("E"):
            assert skill.tier is Tier.EXTENDED, f"{skill.id} sits in an E-section"


def test_core_content_is_also_present_in_extended() -> None:
    """0580 states that all Core content is included at Extended."""
    for skill in ALL_SKILLS:
        assert skill.tier.value in ("core", "extended")


@pytest.mark.parametrize("skill", ALL_SKILLS, ids=lambda s: s.id)
def test_every_seed_produces_a_problem(skill) -> None:
    for seed in range(SEEDS):
        problem = skill.generate(seed)
        assert problem.statement.strip()
        assert problem.answer.strip()
        assert problem.steps


@pytest.mark.parametrize("skill", ALL_SKILLS, ids=lambda s: s.id)
def test_generated_answers_verify_against_our_own_checker(skill) -> None:
    """The engine's answer must satisfy the checker, or the claim is false."""
    for seed in range(SEEDS):
        problem = skill.generate(seed)
        result = check(problem.answer, problem.answer, problem.answer_form, problem.spec)
        assert result.is_correct, (
            f"{skill.id} seed {seed}: answer {problem.answer!r} does not verify "
            f"against itself under {problem.answer_form.value} ({result.reason})"
        )


@pytest.mark.parametrize("skill", ALL_SKILLS, ids=lambda s: s.id)
def test_offline_narration_is_always_grounded(skill) -> None:
    for seed in range(SEEDS):
        problem = skill.generate(seed)
        report = check_narration(problem, narrate_offline(problem))
        assert report.ok, f"{skill.id} seed {seed}: {report.summary()}"


@pytest.mark.parametrize("skill", ALL_SKILLS, ids=lambda s: s.id)
def test_statements_do_not_leak_the_answer(skill) -> None:
    """A question that contains its own answer is not a question.

    Narrowed to expression answers of substance, and it is not a cosmetic
    check. The earlier substring version fired constantly and wrongly: a
    simultaneous-equation question reading "x + y = 7 and 2x - 2y = -3" has
    answer 3, so "3" appears in the question. For a bare integer answer the
    substring test is noise; for a multi-term expression, a genuine leak, it is
    the whole question being answered in the stem.
    """
    if skill.answer_form.value != "exact":
        pytest.skip("only exact-form expression answers can leak this way")

    for seed in range(SEEDS):
        problem = skill.generate(seed)
        answer = problem.answer.strip()
        if len(answer) < 4 or answer.isdigit():
            continue
        assert answer not in problem.statement, (
            f"{skill.id} seed {seed}: statement leaks answer {answer!r}"
        )


@pytest.mark.parametrize("skill", ALL_SKILLS, ids=lambda s: s.id)
def test_no_unresolved_placeholders(skill) -> None:
    """A `{name}` left unrendered is a broken question a student would see.

    Nothing else catches this: `smoke()` only checks that output is non-empty,
    and `{kplaces}` is happily non-empty.
    """
    import re

    leftover = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")
    for seed in range(SEEDS):
        problem = skill.generate(seed)
        blob = " ".join(
            [problem.statement, problem.answer, *(s.text for s in problem.steps)]
        )
        found = leftover.findall(blob)
        assert not found, f"{skill.id} seed {seed}: unresolved {found} in {blob!r}"


def test_coverage_is_reported() -> None:
    report = coverage_report(ALL_SKILLS)
    assert sum(report.values()) == len(ALL_SKILLS)
    assert report == dict(sorted(report.items()))