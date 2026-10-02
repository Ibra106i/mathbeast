"""Command line interface.

Drill mode uses no model at all. That is deliberate: the lowest-friction way to
try this project should not require installing a 4B-parameter model first, and
the barrier to running something is what decides whether anyone runs it.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from mathbeast.forms import check
from mathbeast.narrate import OfflineNarrator, OllamaNarrator, narrate_and_check
from mathbeast.skill import Problem, Skill, load_all
from mathbeast.verify import Verdict

SKILL_DIR = Path(__file__).parent / "skills"


def _use_utf8() -> None:
    """Windows consoles default to cp1252, which cannot print a radical sign.

    The pack contains `√`, `×` and `°`, so this is not optional on Windows.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _load() -> list[Skill]:
    return load_all(SKILL_DIR, smoke=False)


def _slug(skill: Skill) -> str:
    """The part of the id after the syllabus code: `0580.c6.1.sin_angle` -> `sin_angle`."""
    return skill.id.split(".")[-1].lower()


def _select(skills: list[Skill], wanted: str | None, tier: str | None) -> list[Skill]:
    chosen = skills
    if wanted:
        exact = [s for s in skills if s.id == wanted]
        if exact:
            return exact

        query = wanted.lower()
        # Match the slug before falling back to a substring, ranked in that
        # order. A plain substring search made `explain sin` match
        # `probability_single` as well, so the command silently picked one of
        # two and usually got the wrong one.
        prefix = [s for s in skills if _slug(s).startswith(query)]
        if prefix:
            return prefix

        loose = [s for s in skills if query in s.id.lower() or query in s.title.lower()]
        if loose:
            return loose
        raise SystemExit(f"no skill matches {wanted!r}. Try `mathbeast skills`.")

    if tier:
        chosen = [s for s in chosen if s.tier.value == tier]
    return chosen


# --- commands ---------------------------------------------------------------


def cmd_skills(args: argparse.Namespace) -> int:
    skills = _select(_load(), args.skill, args.tier)
    if args.json:
        print(json.dumps([{"id": s.id, "syllabus": s.syllabus, "tier": s.tier.value,
                           "title": s.title} for s in skills], indent=2))
        return 0
    for skill in sorted(skills, key=lambda s: s.id):
        print(f"{skill.id:<44} {skill.tier.value:<8} {skill.title}")
    print(f"\n{len(skills)} skill(s).")
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    skills = _load()
    by_section: dict[str, list[Skill]] = {}
    for skill in skills:
        by_section.setdefault(skill.syllabus.split(".")[0].upper(), []).append(skill)

    print(f"0580 pack: {len(skills)} skills\n")
    for section in sorted(by_section):
        items = sorted(by_section[section], key=lambda s: s.id)
        core = sum(1 for s in items if s.tier.value == "core")
        ext = len(items) - core
        print(f"  {section:<5} {len(items):>3} skill(s)   core {core}, extended {ext}")
        for skill in items:
            print(f"          {skill.id:<44} {skill.title}")
    return 0


def _render_problem(problem: Problem, number: int, total: int) -> None:
    print()
    print(f"--- {number}/{total}  [{problem.syllabus}] {problem.title}")
    print(f"    {problem.statement}")
    hint = problem.spec
    if hint:
        print(f"    (give your answer to {hint})")


def _judge(problem: Problem, given: str) -> bool:
    result = check(problem.answer, given, problem.answer_form, problem.spec)
    label = {
        Verdict.PROVEN_EQUAL: "correct",
        Verdict.PROVEN_DIFFERENT: "not quite",
        Verdict.UNKNOWN: "could not be checked",
        Verdict.UNPARSEABLE: "could not be understood",
    }[result.verdict]
    print(f"    -> {label}: {result.reason}")
    if result.is_correct:
        return True
    # Never assert wrongness we did not prove. UNKNOWN says so plainly.
    if result.verdict is Verdict.UNKNOWN:
        print("       (the checker ran out of road, not that you were wrong)")
    return False


def cmd_drill(args: argparse.Namespace) -> int:
    skills = _select(_load(), args.skill, args.tier)
    rng = random.Random(args.seed)
    skill = rng.choice(skills)
    correct = 0

    for index in range(1, args.count + 1):
        problem = skill.generate(rng.randrange(10**6))
        _render_problem(problem, index, args.count)
        try:
            given = input("    your answer: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if given.lower() in ("q", "quit", "exit"):
            break
        if given:
            correct += bool(_judge(problem, given))
        else:
            print(f"    -> answer: {problem.answer_display}")

    print(f"\n{correct}/{args.count} verified correct.")
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    skills = _select(_load(), args.skill, args.tier)
    rng = random.Random(args.seed)
    skill = rng.choice(skills)
    problem = skill.generate(args.problem_seed if args.problem_seed is not None
                            else rng.randrange(10**6))

    print(f"\n{problem.statement}")
    print(f"\nVerified answer: {problem.answer_display}")

    narrator = (
        OllamaNarrator(model=args.model)
        if args.narrator == "ollama"
        else OfflineNarrator()
    )
    lines, report = narrate_and_check(narrator, problem)

    print(f"\nExplanation ({narrator.name}):")
    for step_id, text in lines:
        print(f"  {step_id}. {text}")

    print(f"\nGrounding: {report.summary()}")
    if report.unsupported:
        print(
            "\nThe narrator stated something the engine did not verify. The "
            "answer above is still proven; the wording is not."
        )
    degraded = getattr(narrator, "degraded", None)
    if degraded:
        print(f"(model unavailable, {degraded}; showing verified steps instead)")
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    """Measure unsupported-claim rate. Refuses to invent a table it cannot support."""
    skills = _load()
    sample: list[Problem] = []
    for skill in skills:
        for seed in range(args.per_skill):
            sample.append(skill.generate(seed))

    offline = OfflineNarrator()
    rates = []
    for problem in sample:
        _, report = narrate_and_check(offline, problem)
        rates.append(report.unsupported_rate)

    print(f"problems sampled: {len(sample)}")
    print(f"offline narrator unsupported-claim rate: {sum(rates)/len(rates):.4f}")
    print()
    print("This is the floor, not the measurement. The interesting comparison --")
    print("raw model vs chain-of-thought vs verified narration -- needs a model.")
    print("Run `mathbeast bench --model qwen2.5:3b` with Ollama running to get it.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mathbeast", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("skill", nargs="?", help="skill id, or any part of one")
        p.add_argument("--tier", choices=["core", "extended"])
        p.add_argument("--seed", type=int, default=None)

    p_skills = sub.add_parser("skills", help="list the pack")
    common(p_skills)
    p_skills.add_argument("--json", action="store_true")
    p_skills.set_defaults(func=cmd_skills)

    p_cov = sub.add_parser("coverage", help="syllabus coverage report")
    p_cov.set_defaults(func=cmd_coverage)

    p_drill = sub.add_parser("drill", help="practice, with no model involved")
    common(p_drill)
    p_drill.add_argument("--count", type=int, default=5)
    p_drill.set_defaults(func=cmd_drill)

    p_explain = sub.add_parser("explain", help="show the verified working")
    common(p_explain)
    p_explain.add_argument("--narrator", choices=["offline", "ollama"], default="offline")
    p_explain.add_argument("--model", default="qwen2.5:3b")
    p_explain.add_argument("--problem-seed", type=int, default=None)
    p_explain.set_defaults(func=cmd_explain)

    p_bench = sub.add_parser("bench", help="measure unsupported-claim rate")
    p_bench.add_argument("--per-skill", type=int, default=5)
    p_bench.add_argument("--model", default="qwen2.5:3b")
    p_bench.set_defaults(func=cmd_bench)

    return parser


def main(argv: list[str] | None = None) -> int:
    _use_utf8()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
