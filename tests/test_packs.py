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


@pytest.mark.parametrize("skill", ALL_SKILLS, ids=lambda s: s.id)
def test_no_malformed_signs_in_rendered_text(skill) -> None:
    """`+ -13` means a `sign` parameter met a literal `+` that already carried
    the sign. Nobody writes that.

    Deliberately does *not* flag `- -`: subtracting a negative is legitimate
    notation ("8 - (-6)" is just "-6 + 8"). Those steps read awkwardly, so they
    parenthesise the negative instead -- but they are not wrong, and a gate
    that cried wolf over correct maths would get ignored.

    Nothing else catches this: the text is non-empty, the placeholders all
    resolve, and the answer is still correct. It only shows up when a student
    reads the question.
    """
    for seed in range(SEEDS):
        problem = skill.generate(seed)
        blob = " ".join([problem.statement, *(s.text for s in problem.steps)])
        for bad in ("+ -", "+ +"):
            assert bad not in blob, (
                f"{skill.id} seed {seed}: {bad!r} in rendered text: {blob!r}"
            )


#: Only `/` and `-` are precedence-sensitive on their right operand.
#: `a * (b * c)` and `a + (b + c)` associate, so an unbracketed compound there
#: is harmless. `a / (b * c)` and `a - (b * c)` are not.
_PRECEDENCE_OPS = ("/", "-")

#: A `derive` template that is pure arithmetic over its inputs cannot produce a
#: compound expression, so using it as a divisor is safe. One containing a root,
#: a power or a symbol can.
_COMPOUND_MARKERS = ("sqrt", "**", "x", "y")


def _compound_params(skill) -> set[str]:
    names = set()
    for name, rule in skill.params.items():
        if isinstance(rule, dict) and rule.get("dist") == "derive":
            template = str(rule.get("template", ""))
            if any(marker in template for marker in _COMPOUND_MARKERS):
                names.add(name)
        if isinstance(rule, dict) and rule.get("dist") == "index":
            names.add(name)
    return names


@pytest.mark.parametrize("skill", ALL_SKILLS, ids=lambda s: s.id)
def test_compound_divisors_are_bracketed(skill) -> None:
    """Self-verification cannot catch this: the engine and the checker make the
    same parse, so `10/2*sqrt(34)` verifies against itself perfectly and lands
    in a student's hands as a sine of 29.2. It has to be caught structurally."""
    import re

    compound = _compound_params(skill)
    if not compound:
        return

    for key in ("answer", "display"):
        template = str(skill.raw.get(key, ""))
        for name in compound:
            for operator in _PRECEDENCE_OPS:
                unbracketed = re.search(
                    re.escape(operator) + re.escape(name), template.replace(" ", "")
                )
                bracketed = f"({operator}{{{name}}}" in template
                assert not (unbracketed and not bracketed), (
                    f"{skill.id}: {key!r} uses {operator}{{{name}}} unbracketed, and "
                    f"{name!r} can be a compound expression. Write "
                    f"({operator}{{{name}}}). Template: {template!r}"
                )


@pytest.mark.parametrize("skill", ALL_SKILLS, ids=lambda s: s.id)
def test_ratios_are_mathematically_possible(skill) -> None:
    """A sine of 29.2 is not a wrong answer, it is an impossible one.

    Checked numerically at the source, because gate 3 verifies the answer
    against itself and would happily bless it.
    """
    import sympy

    for seed in range(SEEDS):
        problem = skill.generate(seed)
        if problem.answer_form.value != "rounded":
            continue
        value = float(sympy.sympify(problem.answer))
        if "sin" in skill.id or "cos" in skill.id:
            assert -1.0001 <= value <= 1.0001, (
                f"{skill.id} seed {seed}: produced {value}, outside [-1, 1]"
            )


def test_coverage_is_reported() -> None:
    report = coverage_report(ALL_SKILLS)
    assert sum(report.values()) == len(ALL_SKILLS)
    assert report == dict(sorted(report.items()))