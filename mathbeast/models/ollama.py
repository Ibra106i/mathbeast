"""Ollama backend: local models, and the only source of true throughput numbers.

Uses `urllib` from the standard library rather than `requests`, so that a base
`pip install mathbeast` needs no HTTP dependency. The `narrate` extra is for
phases that need it; phase 1 does not.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Iterator

from mathbeast.models.client import GenerationChunk
from mathbeast.models.metrics import (
    BackendStatus,
    GenerationMetrics,
    ModelInfo,
    RunningModel,
)

# 127.0.0.1, not localhost. On Windows getaddrinfo offers ::1 first, and a
# refused IPv6 connect on this machine takes two seconds before the IPv4
# address answers. status() makes three calls in a row, so "localhost" cost
# every page, every four-second poll, and every model selection six seconds
# -- long enough for a choice to look like it had not been made. Naming the
# address skips the lookup and the dead family both.
DEFAULT_URL = "http://127.0.0.1:11434"


class OllamaUnavailable(RuntimeError):
    """The server is not answering. Never a crash -- always a state to render."""


def _get_json(url: str, path: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(f"{url.rstrip('/')}{path}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, path: str, payload: dict[str, Any], timeout: float) -> dict:
    request = urllib.request.Request(
        f"{url.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_lines(url: str, path: str, payload: dict[str, Any], timeout: float) -> Iterator[dict]:
    """Stream newline-delimited JSON, the way Ollama replies when streaming."""
    request = urllib.request.Request(
        f"{url.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for line in response:
            line = line.strip()
            if line:
                yield json.loads(line.decode("utf-8"))


def _human_bytes(count: Any) -> int:
    try:
        return int(count)
    except (TypeError, ValueError):
        return 0


class OllamaBackend:
    """Talks to a local Ollama server."""

    name = "ollama"
    kind = "local"

    def __init__(self, url: str = DEFAULT_URL, timeout: float = 10.0) -> None:
        self.url = url
        self.timeout = timeout

    # -- introspection -------------------------------------------------------

    def version(self) -> str | None:
        try:
            body = _get_json(self.url, "/api/version", self.timeout)
            return str(body.get("version")) if body else None
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            return None

    def list_models(self) -> list[ModelInfo]:
        body = _get_json(self.url, "/api/tags", self.timeout)
        models: list[ModelInfo] = []
        for entry in body.get("models") or []:
            details = entry.get("details") or {}
            models.append(
                ModelInfo(
                    name=str(entry.get("name") or entry.get("model") or "?"),
                    size_bytes=_human_bytes(entry.get("size")),
                    family=str(details.get("family") or ""),
                    parameter_size=str(details.get("parameter_size") or ""),
                    quantization=str(details.get("quantization_level") or ""),
                )
            )
        return sorted(models, key=lambda m: m.name)

    def running(self) -> list[RunningModel]:
        body = _get_json(self.url, "/api/ps", self.timeout)
        models: list[RunningModel] = []
        for entry in body.get("models") or []:
            models.append(
                RunningModel(
                    name=str(entry.get("name") or "?"),
                    size_bytes=_human_bytes(entry.get("size")),
                    size_vram_bytes=_human_bytes(entry.get("size_vram")),
                )
            )
        return models

    def status(self) -> BackendStatus:
        """Never raises. An unreachable server is a state, not an exception.

        The catch is deliberately broad. This runs on every dashboard poll and
        is rendered directly to a user, so an unexpected error from an HTTP
        layer we do not control should still produce a page saying "not
        available" rather than a 500.
        """
        try:
            models = self.list_models()
            running = self.running()
            version = self.version()
        except Exception as exc:  # noqa: BLE001
            return BackendStatus(
                name=self.name,
                available=False,
                detail=f"cannot reach {self.url} ({type(exc).__name__}: {exc})",
                kind=self.kind,
            )

        if not models:
            return BackendStatus(
                name=self.name,
                available=True,
                detail="server is up but no models are installed; try `ollama pull`",
                kind=self.kind,
            )

        return BackendStatus(
            name=self.name,
            available=True,
            detail=f"ollama {version}" if version else "connected",
            kind=self.kind,
            models=models,
            running=running,
        )

    # -- generation ----------------------------------------------------------

    def generate(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Iterator[GenerationChunk]:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": True,
        }
        if system:
            payload["system"] = system
        merged = {"temperature": 0.2, **(options or {})}
        payload["options"] = merged

        try:
            for body in _post_lines(self.url, "/api/generate", payload, self.timeout):
                text = str(body.get("response") or "")
                if body.get("done"):
                    yield GenerationChunk(
                        done=True,
                        metrics=GenerationMetrics.from_ollama(body, backend=self.name, model=model),
                    )
                else:
                    yield GenerationChunk(text=text)
        except (urllib.error.URLError, OSError) as exc:
            raise OllamaUnavailable(f"{type(exc).__name__}: {exc}") from exc