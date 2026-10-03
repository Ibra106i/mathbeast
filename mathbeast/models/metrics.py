"""Generation metrics, and the exact definition of tokens per second.

The important decision here is what tokens-per-second is *not*.

Ollama's streaming mode emits chunks as they are ready, and a chunk is not a
token -- it can hold several, or part of one. Counting chunks per second gives
a number that looks like throughput and is not, and on a fast local model it
overstates speed badly enough to be misleading on a dashboard whose whole job is
to tell the truth about the machine.

So tok/s is computed from the counts Ollama reports at the end of a request:
`eval_count / (eval_duration / 1e9)`. That is measured by the server, in the
same units, and it is the figure worth publishing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GenerationMetrics:
    """What one generation actually cost."""

    backend: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    #: Seconds. Ollama reports nanoseconds; normalised on the way in.
    prompt_seconds: float = 0.0
    completion_seconds: float = 0.0
    total_seconds: float = 0.0
    load_seconds: float = 0.0

    @property
    def tokens_per_second(self) -> float:
        """Generation speed, tokens per second.

        Deliberately guarded: a zero or missing duration must not raise, because
        this is called on every dashboard poll and a crash there is worse than
        an absent number.
        """
        if self.completion_seconds <= 0:
            return 0.0
        return self.completion_tokens / self.completion_seconds

    @property
    def prompt_tokens_per_second(self) -> float:
        if self.prompt_seconds <= 0:
            return 0.0
        return self.prompt_tokens / self.prompt_seconds

    @property
    def is_measured(self) -> bool:
        """False when the backend gave us nothing to measure from.

        The dashboard shows a dash rather than a zero, because "0 tok/s" and
        "not measured" mean very different things to someone deciding whether to
        pull a bigger model.
        """
        return self.completion_tokens > 0 and self.completion_seconds > 0

    @classmethod
    def from_ollama(
        cls,
        body: dict[str, Any],
        *,
        backend: str = "ollama",
        model: str = "",
    ) -> "GenerationMetrics":
        """Build metrics from an Ollama `/api/generate` response tail.

        All of Ollama's durations are nanoseconds.
        """

        def seconds(key: str) -> float:
            raw = body.get(key) or 0
            try:
                return float(raw) / 1e9
            except (TypeError, ValueError):
                return 0.0

        def count(key: str) -> int:
            raw = body.get(key) or 0
            try:
                return int(raw)
            except (TypeError, ValueError):
                return 0

        return cls(
            backend=backend,
            model=str(body.get("model") or model),
            prompt_tokens=count("prompt_eval_count"),
            completion_tokens=count("eval_count"),
            prompt_seconds=seconds("prompt_eval_duration"),
            completion_seconds=seconds("eval_duration"),
            total_seconds=seconds("total_duration"),
            load_seconds=seconds("load_duration"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "prompt_seconds": round(self.prompt_seconds, 4),
            "completion_seconds": round(self.completion_seconds, 4),
            "total_seconds": round(self.total_seconds, 4),
            "load_seconds": round(self.load_seconds, 4),
            "tokens_per_second": round(self.tokens_per_second, 2),
            "prompt_tokens_per_second": round(self.prompt_tokens_per_second, 2),
            "is_measured": self.is_measured,
        }


@dataclass(frozen=True)
class ModelInfo:
    """A model the backend is willing to run."""

    name: str
    size_bytes: int = 0
    family: str = ""
    parameter_size: str = ""
    quantization: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "size_bytes": self.size_bytes,
            "size_gb": round(self.size_bytes / 1e9, 2),
            "family": self.family,
            "parameter_size": self.parameter_size,
            "quantization": self.quantization,
        }


@dataclass(frozen=True)
class RunningModel:
    """A model currently resident in memory."""

    name: str
    size_bytes: int = 0
    size_vram_bytes: int = 0

    @property
    def on_gpu(self) -> bool:
        """Ollama reports 0 VRAM when a model is loaded entirely in RAM."""
        return self.size_vram_bytes > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "size_bytes": self.size_bytes,
            "size_gb": round(self.size_bytes / 1e9, 2),
            "size_vram_bytes": self.size_vram_bytes,
            "size_vram_gb": round(self.size_vram_bytes / 1e9, 2),
            "on_gpu": self.on_gpu,
        }


@dataclass
class BackendStatus:
    """Whether the backend answers, and what to say if it does not."""

    name: str
    available: bool
    detail: str = ""
    kind: str = "local"
    models: list[ModelInfo] = field(default_factory=list)
    running: list[RunningModel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "detail": self.detail,
            "kind": self.kind,
            "models": [m.to_dict() for m in self.models],
            "running": [r.to_dict() for r in self.running],
        }