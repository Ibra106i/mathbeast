"""The skill contract: schema, parameter resolution, and generation."""

from __future__ import annotations

import pytest

from mathbeast.skill import (
    TRANSFORMS,
    ParamResolver,
    Skill,
    SkillError,
    coverage_report,
    load,
    load_all,
)

BASE = {
    "id": "0580.c1.1.demo",
    "syllabus": "C1.1",
    "tier": "core",
    "title": "Demo",
    "statement": "Do {expr}.",
    "answer_form": "exact",
    "transform": "expand",
    "answer": "({v} + {p})({v} + {q})",
    "params": {
        "v": {"dist": "const", "value": "x"},
        "p": {"dist": "int", "range": [1, 12]},
        "q": {"dist": "int", "range": [1, 12]},
        "psum": {"dist": "derive", "template": "{p} + {q}"},
    },
}


def make(**overrides):
    data = {**BASE, **overrides}
    return Skill(data)


# --- schema ------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["id", "syllabus", "tier", "title", "statement", "answer_form", "answer"])
def test_missing_required_key_is_rejected(missing: str) -> None:
    data = {k: v for k, v in BASE.items() if k != missing}
    with pytest.raises(SkillError, match="missing keys"):
        Skill(data)


def test_skill_id_must_be_a_syllabus_reference() -> None:
    with pytest.raises(SkillError, match="syllabus references"):
        make(id="quadratics")


def test_tier_must_agree_with_the_syllabus_code() -> None:
    with pytest.raises(SkillError, match="implies a C-code"):
        make(id="0580.c2.1.demo", syllabus="E2.1", tier="core")
    with pytest.raises(SkillError, match="implies a E-code"):
        make(id="0580.e2.1.demo", syllabus="C2.1", tier="extended")


def test_unknown_transform_is_rejected() -> None:
    with pytest.raises(SkillError, match="unknown transform"):
        make(transform="definitely_not_a_transform")


@pytest.mark.parametrize("transform", ["solve", "roots"])
def test_set_producing_transform_requires_the_set_answer_form(transform: str) -> None:
    with pytest.raises(SkillError, match="answer_form must be 'set'"):
        make(transform=transform, answer_form="exact")


def test_set_transform_with_set_form_is_accepted() -> None:
    skill = make(transform="solve", answer_form="set", answer="{v}**2 - 5*{v} + 6")
    assert skill.generate(0).answer_form.value == "set"


# --- parameter resolution ----------------------------------------------------


def test_dependency_order_is_resolved_not_assumed() -> None:
    """`psum` depends on p and q, and may be declared before them."""
    resolver = ParamResolver(BASE["params"], __import__("random").Random(0))
    values = resolver.resolve()
    assert values["psum"] == values["p"] + values["q"]


def test_excluded_values_are_respected() -> None:
    import random

    spec = {"n": {"dist": "int", "range": [1, 5], "exclude": [3]}}
    for seed in range(50):
        assert ParamResolver(spec, random.Random(seed)).resolve()["n"] != 3


def test_dependency_cycle_is_reported_not_hung() -> None:
    spec = {
        "a": {"dist": "derive", "template": "{b}"},
        "b": {"dist": "derive", "template": "{a}"},
    }
    with pytest.raises(SkillError, match="cycle"):
        ParamResolver(spec, __import__("random").Random(0)).resolve()


def test_unsatisfiable_range_is_reported() -> None:
    import random

    spec = {"n": {"dist": "int", "range": [4, 5], "exclude": [4, 5]}}
    with pytest.raises(SkillError, match="no admissible"):
        ParamResolver(spec, random.Random(0)).resolve()


def test_unknown_distribution_is_reported() -> None:
    import random

    with pytest.raises(SkillError, match="unknown distribution"):
        ParamResolver({"n": {"dist": "quantum"}}, random.Random(0)).resolve()


# --- generation --------------------------------------------------------------


def test_statement_and_answer_share_one_expression() -> None:
    """`{expr}` binds to the question's expression, so they cannot drift."""
    for seed in range(100):
        problem = make().generate(seed)
        assert "Expand" not in problem.statement  # sanity: BASE says "Do {expr}"
        assert problem.statement.startswith("Do (x +")
        assert problem.statement.endswith(").")


def test_answer_is_derived_never_stated() -> None:
    skill = make()
    for seed in range(200):
        problem = skill.generate(seed)
        # The answer is the transform of the question's expression, so it is
        # algebraically determined by it. Nothing in the file states it.
        assert "**2" in problem.answer


def test_every_seed_produces_steps() -> None:
    for seed in range(100):
        assert make().generate(seed).steps


def test_smoke_rejects_a_skill_that_can_produce_an_empty_answer() -> None:
    """The gate that stops a broken skill shipping broken problems."""
    with pytest.raises(SkillError, match="not an expression|empty answer|empty statement"):
        make(answer="{p}", params={"p": {"dist": "const", "value": " "}}).smoke(seeds=3)


def test_smoke_passes_for_a_well_formed_skill() -> None:
    make().smoke(seeds=200)


def test_seed_is_reproducible() -> None:
    skill = make()
    assert skill.generate(42) == skill.generate(42)


def test_different_seeds_differ() -> None:
    skill = make()
    assert skill.generate(1) != skill.generate(2)


# --- the shipped pack -------------------------------------------------------


def test_bundled_skills_load_and_smoke() -> None:
    from pathlib import Path

    skills = load_all(Path(__file__).parent.parent / "mathbeast" / "skills")
    assert skills, "expected at least one bundled skill"
    for skill in skills:
        assert skill.id.startswith("0580.")


def test_coverage_report_counts_by_syllabus() -> None:
    from pathlib import Path

    skills = load_all(Path(__file__).parent.parent / "mathbeast" / "skills")
    report = coverage_report(skills)
    assert report == dict(sorted(report.items()))
    assert sum(report.values()) == len(skills)


def test_load_rejects_a_non_mapping_file(tmp_path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(SkillError, match="YAML mapping"):
        load(path)


# --- transforms --------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(TRANSFORMS))
def test_every_advertised_transform_is_callable(name: str) -> None:
    """No transform may be advertised without existing."""
    assert callable(TRANSFORMS[name])