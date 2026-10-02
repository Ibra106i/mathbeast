"""The skill contract: how a problem, its answer and its steps are constructed.

The load-bearing idea: a skill never *states* an answer. It states a question
and an audited `transform`, and the engine computes the answer by applying that
transform. Correctness is therefore structural -- there is no answer in the file
to get wrong.

This is also the answer to "how do community contributions avoid becoming an
RCE vector?". Skill files are data. The logic lives in `TRANSFORMS`, which is
small, reviewed, and covered by tests. A good-first-issue contribution is
YAML, not Python.

Skill IDs are Cambridge 0580 syllabus references, so "does this pack cover the
syllabus?" is a mechanical question rather than an opinion.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import sympy
import yaml

from mathbeast.forms import AnswerForm
from mathbeast.verify import ParseRejected, normalise, to_expr

# --- audited transform vocabulary -------------------------------------------


def _t_expand(expr):
    return sympy.expand(expr)


def _t_collect(expr):
    """Collect like terms, the C2.1 'simplify 6x + 2x' style question."""
    return sympy.collect(sympy.expand(expr), sympy.Symbol("x"))


def _t_factor(expr):
    return sympy.factor(expr)


def _t_simplify(expr):
    return sympy.simplify(expr)


def _t_solve(expr):
    """Solve expr = 0. Pairs with AnswerForm.SET."""
    return sympy.solve(expr, sympy.Symbol("x"))


def _t_roots(expr):
    return sympy.solve(expr, sympy.Symbol("x"))


def _t_eval(expr):
    return sympy.nsimplify(expr)


def _t_numeric(expr, digits: int = 12):
    return sympy.N(expr, digits)


def _t_diff(expr):
    return sympy.diff(expr, sympy.Symbol("x"))


def _t_integrate(expr):
    return sympy.integrate(expr, sympy.Symbol("x"))


def _t_sqrt(expr):
    return sympy.sqrt(expr)


def _t_substitute(expr, var: str = "x", value=2):
    return expr.subs(sympy.Symbol(var), value)


#: The only functions a skill may name. Everything here is deterministic,
#: side-effect free, and unit tested in `tests/test_transforms.py`.
TRANSFORMS: dict[str, Callable[[Any], Any]] = {
    "expand": _t_expand,
    "collect": _t_collect,
    "factor": _t_factor,
    "simplify": _t_simplify,
    "solve": _t_solve,
    "roots": _t_roots,
    "exact": _t_eval,
    "numeric": _t_numeric,
    "diff": _t_diff,
    "integrate": _t_integrate,
    "sqrt": _t_sqrt,
}

#: Transforms that produce a list of values, so the skill's answer form must be SET.
_SET_TRANSFORMS = {"solve", "roots"}


class SkillError(ValueError):
    """A skill file is invalid. Never raised for a bad student answer."""


class Tier(Enum):
    CORE = "core"
    EXTENDED = "extended"


@dataclass(frozen=True)
class Step:
    """One verified working step. The narrator may only elaborate on these."""

    index: int
    operation: str
    text: str
    expr_from: str = ""
    expr_to: str = ""


@dataclass(frozen=True)
class Problem:
    skill_id: str
    syllabus: str
    tier: Tier
    title: str
    statement: str
    answer_form: AnswerForm
    spec: str | None
    answer: str
    steps: tuple[Step, ...]
    seed: int
    meta: dict[str, Any] = field(default_factory=dict)

    def answer_text(self) -> str:
        value = self.answer
        return value


# --- parameter distributions ------------------------------------------------

_REF = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _substitute(template: str, values: dict[str, Any]) -> str:
    return _REF.sub(lambda m: str(values.get(m.group(1), m.group(0))), template)


def _render(template: str, values: dict[str, Any]) -> str:
    """Substitute parameters, then render to readable mathematical text."""
    filled = _substitute(template, values)
    try:
        expr = sympy.sympify(filled)
    except (sympy.SympifyError, SyntaxError, TypeError):
        return filled
    return sympy.sstr(expr)


class ParamResolver:
    """Resolves parameters in dependency order.

    A `derive` parameter may reference already-bound parameters, so resolution
    is a fixed-point loop rather than a single pass. A dependency cycle is a
    skill bug and is reported as such.
    """

    def __init__(self, spec: dict[str, Any], rng: random.Random) -> None:
        self.spec = spec
        self.rng = rng
        self.values: dict[str, Any] = {}

    def resolve(self) -> dict[str, Any]:
        pending = dict(self.spec)
        for _ in range(len(self.spec) + 2):
            progressed = False
            for name, rule in list(pending.items()):
                if not isinstance(rule, dict):
                    pending.pop(name)
                    self.values[name] = rule
                    progressed = True
                    continue
                if _deps(str(rule)) <= self.values.keys():
                    self.values[name] = self._apply(rule)
                    pending.pop(name)
                    progressed = True
            if not pending:
                return self.values
            if not progressed:
                raise SkillError(
                    f"parameter dependency cycle or missing value: "
                    f"{sorted(pending)} depend on {sorted(set().union(*(_deps(str(r)) for r in pending.values())) - self.values.keys())}"
                )
        raise SkillError("could not resolve parameters")

    def _apply(self, rule: dict[str, Any]) -> Any:
        dist = rule.get("dist")
        if dist == "const":
            return rule["value"]
        if dist == "int":
            low, high = rule.get("range", [1, 12])
            exclude = set(rule.get("exclude", []))
            options = [n for n in range(int(low), int(high) + 1) if n not in exclude]
            if not options:
                raise SkillError(f"no admissible integers in {rule}")
            return self.rng.choice(options)
        if dist == "choice":
            return self.rng.choice(rule["options"])
        if dist == "derive":
            filled = _substitute(rule["template"], self.values)
            try:
                return sympy.sympify(filled)
            except (sympy.SympifyError, SyntaxError, TypeError) as exc:
                raise SkillError(f"could not derive {rule!r}: {exc}") from None
        raise SkillError(f"unknown distribution {dist!r}")


def _deps(text: str) -> set[str]:
    return set(_REF.findall(text))


# --- the skill --------------------------------------------------------------


_REQUIRED = ("id", "syllabus", "tier", "title", "statement", "answer_form", "answer")


class Skill:
    """A loaded, validated skill. Call `generate(seed)` for problems."""

    def __init__(self, data: dict[str, Any], source: Path | None = None) -> None:
        self.source = source
        self.raw = data
        self._validate_schema(data)
        self.id: str = data["id"]
        self.syllabus: str = data["syllabus"]
        self.tier = Tier(data["tier"])
        self.title: str = data["title"]
        self.answer_form = AnswerForm(data["answer_form"])
        self.spec = data.get("spec")
        self.transform: str = data.get("transform", "simplify")
        self.params: dict[str, Any] = data.get("params", {}) or {}
        self.step_templates: list[str] = data.get("steps", []) or []
        self.rationale: str = data.get("rationale", "")

        if self.transform not in TRANSFORMS:
            raise SkillError(f"{self.id}: unknown transform {self.transform!r}")
        if self.transform in _SET_TRANSFORMS and self.answer_form is not AnswerForm.SET:
            raise SkillError(
                f"{self.id}: transform {self.transform!r} yields a list of values, "
                f"so answer_form must be 'set', not {self.answer_form.value!r}"
            )

    # -- validation ----------------------------------------------------------

    def _validate_schema(self, data: dict[str, Any]) -> None:
        missing = [k for k in _REQUIRED if k not in data]
        if missing:
            raise SkillError(f"{data.get('id', '<no id>')}: missing keys {missing}")
        if not re.match(r"^0580\.[ce]\d+", str(data["id"])):
            raise SkillError(
                f"{data['id']}: skill ids must be syllabus references like 0580.c1.2"
            )
        if data["tier"] not in ("core", "extended"):
            raise SkillError(f"{data['id']}: tier must be 'core' or 'extended'")
        prefix = {"core": "C", "extended": "E"}[data["tier"]]
        if not str(data["syllabus"]).upper().startswith(prefix):
            raise SkillError(
                f"{data['id']}: tier {data['tier']!r} implies a {prefix}-code, "
                f"but syllabus is {data['syllabus']!r}"
            )

    # -- generation ----------------------------------------------------------

    def generate(self, seed: int | None = None) -> Problem:
        rng = random.Random(seed)
        values = ParamResolver(self.params, rng).resolve()

        raw_answer = _substitute(str(self.raw["answer"]), values)

        try:
            # `to_expr`, not `sympify`: it does implicit multiplication (so
            # `(x + 3)(x + 5)` is a product, not a call on an Add) and it
            # enforces the same allowlist a student answer must pass.
            answer_expr = to_expr(raw_answer)
        except (ParseRejected, SyntaxError, TypeError, AttributeError, KeyError) as exc:
            raise SkillError(f"{self.id}: answer is not an expression: {exc}") from None

        # `{expr}` in a statement resolves to the question's own expression, so a
        # skill states the expression once. Otherwise the statement and the
        # answer can drift apart silently -- author writes (x+3)(x+5) in one
        # place and (x+4)(x+6) in the other, and every problem ships wrong.
        values["expr"] = _render(str(self.raw["answer"]), values)
        statement = _render(self.raw["statement"], values)

        answer_value = TRANSFORMS[self.transform](answer_expr)
        answer_text = _format_answer(answer_value)

        steps = tuple(
            Step(
                index=i,
                operation=self.transform,
                text=_render(template, values),
                expr_from=sympy.sstr(answer_expr),
                expr_to=sympy.sstr(answer_value),
            )
            for i, template in enumerate(self.step_templates)
        )
        if not steps:
            steps = (
                Step(
                    index=0,
                    operation=self.transform,
                    text=self.rationale or f"Work in from {answer_text}.",
                    expr_from=sympy.sstr(answer_expr),
                    expr_to=sympy.sstr(answer_value),
                ),
            )

        return Problem(
            skill_id=self.id,
            syllabus=self.syllabus,
            tier=self.tier,
            title=self.title,
            statement=statement,
            answer_form=self.answer_form,
            spec=self.spec,
            answer=answer_text,
            steps=steps,
            seed=seed if seed is not None else -1,
            meta={k: sympy.sstr(v) for k, v in values.items()},
        )

    def smoke(self, seeds: int = 200) -> None:
        """Refuse to ship a skill that can produce a broken problem.

        The equivalent of a generator that cannot ship a bad problem: if any
        seed produces an unparseable or empty answer, the skill is rejected.
        """
        from mathbeast.verify import normalise

        for seed in range(seeds):
            problem = self.generate(seed)
            if not problem.answer.strip():
                raise SkillError(f"{self.id}: seed {seed} produced an empty answer")
            if not problem.statement.strip():
                raise SkillError(f"{self.id}: seed {seed} produced an empty statement")
            try:
                normalise(problem.answer)
            except Exception as exc:  # noqa: BLE001
                raise SkillError(
                    f"{self.id}: seed {seed} produced an unverifiable answer "
                    f"{problem.answer!r} ({exc})"
                ) from None
            if not problem.steps:
                raise SkillError(f"{self.id}: seed {seed} produced no steps")


def _format_answer(value: Any) -> str:
    """Render an answer as text a student would type."""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(sympy.sstr(v) for v in value)
    if isinstance(value, sympy.Basic):
        if value.is_Float:
            return f"{float(value):.10g}"
        return sympy.sstr(value)
    return str(value)


# --- loading ----------------------------------------------------------------


def load(path: Path) -> Skill:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SkillError(f"{path}: skill files must be a YAML mapping")
    skill = Skill(data, source=Path(path))
    return skill


def load_all(directory: Path, *, smoke: bool = True) -> list[Skill]:
    """Load every skill in a directory, newest schema first."""
    skills = [load(p) for p in sorted(Path(directory).glob("*.yaml"))]
    if smoke:
        for skill in skills:
            skill.smoke()
    return skills


def coverage_report(skills: list[Skill]) -> dict[str, int]:
    """Count skills per syllabus reference, for tracking pack completeness."""
    report: dict[str, int] = {}
    for skill in skills:
        report[skill.syllabus] = report.get(skill.syllabus, 0) + 1
    return dict(sorted(report.items()))