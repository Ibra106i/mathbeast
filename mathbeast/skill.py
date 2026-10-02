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


def _t_solve_ineq(expr):
    """Solve `expr <= 0` over the reals. Pairs with AnswerForm.INTERVAL.

    Uses `solve_univariate_inequality` with an explicit `Le`, rather than
    `solve_inequalities`: the latter is not exported at the top level of SymPy
    1.14 and its import path has moved before. This returns an Interval such as
    (-oo, 6], which `_format_answer` renders as `[-inf, 6]` and `_to_interval`
    reads back.
    """
    return sympy.solve_univariate_inequality(
        sympy.Le(expr, 0), sympy.Symbol("x"), relational=False
    )


def _t_powsimp(expr):
    """Combine like powers: 2**3 * 2**4 -> 2**7. E2.1 index laws."""
    return sympy.powsimp(expr, force=True)


def _t_complete_square(expr):
    """Rewrite `x**2 + b*x` as `(x + b/2)**2 - (b/2)**2`.

    Returns a string rather than a SymPy object: SymPy has no printer for
    "completed square" form, and expanding the result would undo the whole
    point. The string is still parseable by the checker, so a student answer
    verifies against it.
    """
    x = sympy.Symbol("x")
    expanded = sympy.expand(expr)
    linear = sympy.Poly(expanded, x).coeff_monomial(x)
    if linear == 0:
        return sympy.sstr(sympy.factor(expanded))
    half = sympy.nsimplify(linear / 2)
    completed = sympy.factor(expanded + half**2)
    return f"{sympy.sstr(completed)} - {sympy.sstr(half**2)}"


def _t_solve_system_x(value):
    """Solve a two-equation linear system and return x alone.

    `value` is a list of two equations, e.g. `answer: "[x + y - 5, x - y - 1]"`.
    Solving for a single unknown rather than returning the ordered pair keeps
    the answer order-free, which is what the `set` answer form can check.
    """
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise SkillError("solve_system_x expects two equations, e.g. '[x + y - 5, x - y - 1]'")
    x, y = sympy.symbols("x y")
    solutions = sympy.solve(list(value), [x, y])
    if isinstance(solutions, dict):
        # SymPy returns a bare dict rather than a single-element list in some
        # cases; normalise before indexing.
        solutions = [solutions]
    if not solutions or x not in solutions[0]:
        raise SkillError("the simultaneous equations have no unique solution for x")
    return solutions[0][x]


def _t_diff(expr):
    return sympy.diff(expr, sympy.Symbol("x"))


def _t_integrate(expr):
    return sympy.integrate(expr, sympy.Symbol("x"))


def _t_sqrt(expr):
    return sympy.sqrt(expr)


def _t_sort_set(value):
    """Order a list of values ascending. Pairs with AnswerForm.SET.

    Answer templates for ordering questions are list literals such as
    `[3, 1, 2]`, so this transform receives a Python list rather than an
    expression. Transforms are not required to take expressions.
    """
    if not isinstance(value, (list, tuple)):
        raise SkillError("sort_set expects a list, e.g. answer: '[3, 1, 2]'")
    return sorted(value)


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
    "solve_system_x": _t_solve_system_x,
    "complete_square": _t_complete_square,
    "solve_ineq": _t_solve_ineq,
    "powsimp": _t_powsimp,
    "exact": _t_eval,
    "numeric": _t_numeric,
    "diff": _t_diff,
    "integrate": _t_integrate,
    "sqrt": _t_sqrt,
    "sort_set": _t_sort_set,
}

#: Transforms that produce a list of values, so the skill's answer form must be SET.
_SET_TRANSFORMS = {"solve", "roots", "sort_set"}


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
    #: The unevaluated question expression. `expr_from` is parsed with
    #: `evaluate=True`, so `14**2` would collapse to `196` and lose the input
    #: that a narration is entitled to mention.
    expr_raw: str = ""


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
                if self._deps_of(rule) <= self.values.keys():
                    self.values[name] = self._apply(rule)
                    pending.pop(name)
                    progressed = True
            if not pending:
                return self.values
            if not progressed:
                raise SkillError(
                    f"parameter dependency cycle or missing value: "
                    f"{sorted(pending)} depend on "
                    f"{sorted(set().union(*(self._deps_of(r) for r in pending.values())) - self.values.keys())}"
                )
        raise SkillError("could not resolve parameters")

    @staticmethod
    def _deps_of(rule: Any) -> set[str]:
        """Parameters a rule depends on, including non-template references.

        A `sign` rule that reads `from: b` depends on `b`, but the name appears
        as a plain value rather than inside braces, so template scanning alone
        would let it resolve too early and disagree with `b`.
        """
        deps = _deps(str(rule))
        if isinstance(rule, dict) and "from" in rule:
            deps.add(str(rule["from"]))
        return deps

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
        if dist == "sign":
            # Renders a number as "+ 11" or "- 11" for display only. Without
            # it a negative constant reaches a student as "8x + -11".
            # `from` reads an already-bound parameter; `of` draws a fresh one.
            if "from" in rule:
                inner = self.values[rule["from"]]
            else:
                inner = self._apply(rule["of"])
            try:
                inner = sympy.sympify(inner)
            except (sympy.SympifyError, TypeError, ValueError):
                raise SkillError(f"sign needs a number, got {inner!r}") from None
            if not inner.is_number:
                raise SkillError(
                    f"sign needs a number, got {inner!r}; it is for display "
                    "constants such as 'x + 5', not for expressions"
                )
            template = rule["minus"] if inner < 0 else rule.get("plus", "+ {}")
            return template.format(abs(inner))
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
        #
        # `display` overrides how the question is *written*. It matters for two
        # reasons. `13^2` is Python's bitwise xor, not a square, so a display
        # string must not be parsed as maths. And canonicalising destroys the
        # question: SymPy renders `15*x + 8*x` as `23*x`, which is the answer,
        # so a skill asking "simplify 15x + 8x" would otherwise state its own
        # answer.
        #
        # So `display` substitutes parameters and stops -- it is literal text.
        # `{expr}`, absent an explicit display, is the canonicalised expression.
        if "display" in self.raw:
            values["expr"] = _substitute(str(self.raw["display"]), values)
        else:
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
                expr_raw=raw_answer,
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
                    expr_raw=raw_answer,
                ),
            )

        return Problem(
            skill_id=self.id,
            syllabus=self.syllabus,
            tier=self.tier,
            title=self.title,
            statement=statement,
            answer_form=self.answer_form,
            # `spec` may reference parameters, e.g. `spec: "{sf}sf"` for a
            # rounding question. It has to be resolved per-problem, not read
            # off the raw file.
            spec=_substitute(self.spec, values) if self.spec else self.spec,
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


_INFINITY_TEXT = {sympy.oo: "inf", -sympy.oo: "-inf"}


def _endpoint_is_open(interval, side: str) -> bool:
    """Whether an interval's `left`/`right` endpoint is open.

    SymPy renamed these attributes across versions (`left_closed` ->
    `left_open`), and it silently forces the endpoint at infinity to be open
    regardless of what you pass -- which is correct, since `[-oo, 6]` and
    `(-oo, 6]` are the same set. Read whichever attribute this version has.
    """
    if hasattr(interval, f"{side}_open"):
        return bool(getattr(interval, f"{side}_open"))
    if hasattr(interval, f"{side}_closed"):
        return not bool(getattr(interval, f"{side}_closed"))
    return False


def _format_answer(value: Any) -> str:
    """Render an answer as text a student would type."""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_format_answer(v) for v in value)
    if isinstance(value, float):
        return f"{value:.10g}"
    # Intervals are rendered in the same notation a student is taught, so that
    # `Interval(-oo, 6]` prints as `[-inf, 6]` and round-trips through the
    # interval answer form.
    if isinstance(value, sympy.Interval):
        left = "(" if _endpoint_is_open(value, "left") else "["
        right = ")" if _endpoint_is_open(value, "right") else "]"
        lo = _INFINITY_TEXT.get(value.start, _format_answer(value.start))
        hi = _INFINITY_TEXT.get(value.end, _format_answer(value.end))
        return f"{left}{lo}, {hi}{right}"
    if isinstance(value, sympy.Basic):
        if value.is_Float:
            return f"{float(value):.10g}"
        # 0.03742 parses to an exact Rational, which reads as 1871/50000 rather
        # than the decimal the question used. Show it as a decimal when its
        # denominator has no prime factors other than 2 and 5.
        if value.is_Rational and not value.is_Integer:
            if set(sympy.factorint(value.q)) <= {2, 5}:
                return f"{float(value):.10g}"
        return sympy.sstr(value)
    return str(value)


# --- loading ----------------------------------------------------------------


def load(path: Path) -> Skill:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        # Name the file. A bare ScannerError during collection points at the
        # test module rather than the skill, which sends you looking in the
        # wrong place entirely.
        raise SkillError(f"{path.name}: invalid YAML -- {exc}") from None
    if not isinstance(data, dict):
        raise SkillError(f"{path}: skill files must be a YAML mapping")
    return Skill(data, source=path)


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