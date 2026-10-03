"""Model backends. `urllib` only -- no HTTP dependency in the base install."""

from mathbeast.models.client import (
    FakeBackend,
    GenerationChunk,
    ModelBackend,
    Registry,
    measure,
)
from mathbeast.models.metrics import (
    BackendStatus,
    GenerationMetrics,
    ModelInfo,
    RunningModel,
)
from mathbeast.models.ollama import DEFAULT_URL, OllamaBackend, OllamaUnavailable

__all__ = [
    "DEFAULT_URL",
    "BackendStatus",
    "FakeBackend",
    "GenerationChunk",
    "GenerationMetrics",
    "ModelBackend",
    "ModelInfo",
    "OllamaBackend",
    "OllamaUnavailable",
    "Registry",
    "RunningModel",
    "build_registry",
    "measure",
]


def build_registry(
    *, url: str = DEFAULT_URL, model: str = "", timeout: float = 10.0
) -> Registry:
    """Local Ollama by default, plus the fake so tests and demos never need it.

    The cloud backend arrives in a later phase and is deliberately absent here
    rather than stubbed to look present.
    """
    backend = OllamaBackend(url=url, timeout=timeout)
    chosen = model
    if not chosen:
        try:
            models = backend.list_models()
        except Exception:  # noqa: BLE001 - a dead server must not block startup
            models = []
        chosen = models[0].name if models else ""
    return Registry(backend=backend, model=chosen, extras={"fake": FakeBackend()})