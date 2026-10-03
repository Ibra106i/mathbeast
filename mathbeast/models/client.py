"""The backend interface, plus a fake so the test suite never needs Ollama.

`FakeBackend` is not a testing convenience bolted on afterwards. Without it the
moment this lands, `pytest` starts failing on any machine that isn't running a
4B model, and the metrics maths becomes untestable in CI. The contract has to be
exercisable without hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol

from mathbeast.models.metrics import (
    BackendStatus,
    GenerationMetrics,
    ModelInfo,
    RunningModel,
)


@dataclass(frozen=True)
class GenerationChunk:
    """One piece of a streaming response.

    `metrics` is only populated on the final chunk, because that is when the
    server has counted anything.
    """

    text: str = ""
    done: bool = False
    metrics: GenerationMetrics | None = None


class ModelBackend(Protocol):
    """One way of running a language model."""

    name: str
    kind: str

    def status(self) -> BackendStatus:
        """Whether this backend answers, plus what it can run."""

    def generate(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Iterator[GenerationChunk]:
        """Stream a completion."""


def measure(
    backend: ModelBackend,
    model: str,
    *,
    prompt: str = "Count from one to twenty, separated by spaces.",
    max_tokens: int = 64,
    timeout: float = 60.0,
) -> GenerationMetrics | None:
    """Run a short generation purely to get a throughput number.

    Returns None if the backend produced nothing measurable, so a caller can
    show a dash rather than inventing a zero.
    """
    last: GenerationMetrics | None = None
    try:
        for chunk in backend.generate(
            model,
            prompt,
            options={"num_predict": max_tokens},
        ):
            if chunk.metrics is not None:
                last = chunk.metrics
    except Exception:  # noqa: BLE001 - the dashboard must survive a dead backend
        return None
    return last


@dataclass
class FakeBackend:
    """Deterministic stand-in for CI and for `pytest` on any machine."""

    name: str = "fake"
    kind: str = "local"
    model_name: str = "fake-model"
    #: Seconds spent "generating". Set to 0 to simulate a dead server.
    completion_seconds: float = 2.0
    prompt_tokens: int = 24
    completion_tokens: int = 128
    reply: str = "one two three four five six seven eight nine ten"
    available: bool = True

    def status(self) -> BackendStatus:
        return BackendStatus(
            name=self.name,
            available=self.available,
            detail="" if self.available else "fake backend disabled",
            kind=self.kind,
            models=[ModelInfo(name=self.model_name, size_bytes=4_000_000_000)],
            running=[RunningModel(name=self.model_name, size_vram_bytes=4_000_000_000)],
        )

    def generate(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Iterator[GenerationChunk]:
        if not self.available:
            raise ConnectionError("fake backend is marked unavailable")

        # Three chunks, so streaming behaviour is exercised rather than assumed.
        words = self.reply.split()
        step = max(1, len(words) // 3)
        pieces = [" ".join(words[:step]), " ".join(words[step:-1]), words[-1]]
        for piece in pieces:
            yield GenerationChunk(text=piece)

        yield GenerationChunk(
            done=True,
            metrics=GenerationMetrics(
                backend=self.name,
                model=model,
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
                prompt_seconds=self.prompt_seconds,
                completion_seconds=self.completion_seconds,
                total_seconds=self.prompt_seconds + self.completion_seconds,
            ),
        )

    @property
    def prompt_seconds(self) -> float:
        return self.completion_seconds / 4


@dataclass
class Registry:
    """Which backend to use, and which model within it."""

    backend: ModelBackend
    model: str
    extras: dict[str, ModelBackend] = field(default_factory=dict)

    def set_backend(self, name: str) -> None:
        if name == self.backend.name:
            return
        if name not in self.extras:
            raise KeyError(f"no backend named {name!r}")
        self.extras[self.backend.name] = self.backend
        self.backend = self.extras.pop(name)

    def set_model(self, model: str) -> None:
        self.model = model