"""The narrator: the only component permitted to be wrong.

Everything else in MathBeast is code. This is the part that talks to a model,
so it is deliberately small, optional, and always checked.

Three rules:

1. The narrator never sees the problem as free text. It receives the engine's
   verified steps and is asked to explain *those*, so there is no
   word-problem parsing for it to get wrong.
2. Its output is structurally bound: one utterance per step, tagged with that
   step's id. See `prose.py`.
3. It is optional. With no model installed, `OfflineNarrator` restates the
   verified steps and is correct by construction. A project whose whole pitch
   is that it works without an LLM should mean it.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from mathbeast.prose import Claim, NarrationReport, check_narration
from mathbeast.skill import Problem

DEFAULT_OLLAMA_URL = "http://localhost:11434"


class Narrator(Protocol):
    name: str

    def narrate(self, problem: Problem) -> list[tuple[int, str]]:
        ...


class OfflineNarrator:
    """Restates the engine's verified steps. Needs no model, cannot invent."""

    name = "offline"

    def narrate(self, problem: Problem) -> list[tuple[int, str]]:
        return [(step.index, step.text) for step in problem.steps]


SYSTEM_PROMPT = """\
You explain worked mathematics to a student.

You will be given numbered steps. Each step was computed and verified by a
computer algebra system. Your only job is to say, in one short sentence, what
each step does and why.

Rules you must follow:
- Reply with one line per step, and nothing else.
- Each line must start with its step number, a period, then your sentence.
- Never state a number, expression or result that does not appear in that step.
- Never claim a method was used unless that step used it.
- Do not add steps, do not skip steps, do not add commentary.

Example reply:
0. This substitutes the value into the expression.
1. This simplifies the squared term first.
"""


class OllamaNarrator:
    """Explains verified steps using a local Ollama model.

    Never raises: if the server is unreachable, the model misbehaves, or its
    reply cannot be parsed into the required line-per-step shape, the offline
    narrator takes over and `degraded` says so. A tutor that crashes because a
    background daemon is down is worse than one that explains plainly.
    """

    def __init__(
        self,
        model: str = "qwen2.5:3b",
        url: str = DEFAULT_OLLAMA_URL,
        timeout: float = 120.0,
    ) -> None:
        self.name = f"ollama:{model}"
        self.model = model
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.degraded: str | None = None

    def _prompt(self, problem: Problem) -> str:
        lines = "\n".join(
            f"{step.index}. {step.text}" for step in problem.steps
        )
        return f"Question: {problem.statement}\n\nSteps:\n{lines}\n\nReply:"

    def narrate(self, problem: Problem) -> list[tuple[int, str]]:
        self.degraded = None
        try:
            raw = self._call(self._prompt(problem))
        except Exception as exc:  # noqa: BLE001 - any failure degrades
            self.degraded = f"{type(exc).__name__}: {exc}"
            return OfflineNarrator().narrate(problem)

        parsed = _parse_lines(raw, problem)
        if parsed is None:
            self.degraded = "reply could not be bound to the verified steps"
            return OfflineNarrator().narrate(problem)
        return parsed

    def _call(self, prompt: str) -> str:
        import urllib.error
        import urllib.request

        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "system": SYSTEM_PROMPT,
                "stream": False,
                "options": {"temperature": 0.2},
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            f"{self.url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return str(body.get("response", ""))


_LINE_RE = re.compile(r"^\s*(\d+)\s*[.)-]?\s+(.*\S)\s*$")


def _parse_lines(raw: str, problem: Problem) -> list[tuple[int, str]] | None:
    """Turn a model reply into exactly one (step_id, text) per verified step.

    Returns None if the reply cannot be bound to the steps -- wrong count,
    wrong ids, or nothing usable. The caller then degrades rather than
    guessing, because an unbound narration is exactly the failure this project
    exists to prevent.
    """
    parsed: list[tuple[int, str]] = []
    for line in raw.splitlines():
        match = _LINE_RE.match(line)
        if not match:
            continue
        step_id, text = int(match.group(1)), match.group(2)
        parsed.append((step_id, text))

    expected = [step.index for step in problem.steps]
    if [pid for pid, _ in parsed] != expected:
        return None
    if any(not text.strip() for _, text in parsed):
        return None
    return parsed


def narrate_and_check(narrator: Narrator, problem: Problem) -> tuple[
    list[tuple[int, str]], NarrationReport
]:
    """Narrate a problem and immediately check what came back."""
    lines = narrator.narrate(problem)
    return lines, check_narration(problem, lines)


__all__ = [
    "Claim",
    "Narrator",
    "OfflineNarrator",
    "OllamaNarrator",
    "narrate_and_check",
]
