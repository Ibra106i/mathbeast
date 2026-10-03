"""The metrics contract and the backends, tested with no model in sight."""

from __future__ import annotations

import json
import urllib.error

import pytest

from mathbeast.models import (
    BackendStatus,
    FakeBackend,
    GenerationMetrics,
    ModelInfo,
    OllamaBackend,
    OllamaUnavailable,
    RunningModel,
    build_registry,
    measure,
)
from mathbeast.models.client import Registry


# --- tok/s is the exact count, not a chunk rate -----------------------------


def test_tokens_per_second_uses_server_counts() -> None:
    """eval_count / eval_duration, in seconds. Not chunks."""
    metrics = GenerationMetrics(
        backend="ollama",
        model="m",
        completion_tokens=300,
        completion_seconds=10.0,
    )
    assert metrics.tokens_per_second == 30.0


def test_metrics_are_read_from_an_ollama_response_tail() -> None:
    body = {
        "model": "qwen2.5:3b",
        "done": True,
        "eval_count": 412,
        "eval_duration": 6_000_000_000,  # nanoseconds
        "prompt_eval_count": 88,
        "prompt_eval_duration": 400_000_000,
        "total_duration": 6_500_000_000,
        "load_duration": 100_000_000,
    }
    metrics = GenerationMetrics.from_ollama(body)
    assert metrics.completion_tokens == 412
    assert metrics.completion_seconds == pytest.approx(6.0)
    assert metrics.prompt_seconds == pytest.approx(0.4)
    assert metrics.total_seconds == pytest.approx(6.5)
    assert metrics.tokens_per_second == pytest.approx(68.67, rel=1e-3)


def test_a_chunk_rate_would_not_be_the_same_number() -> None:
    """Why the distinction matters enough to be in a comment and a test.

    Four tokens in four chunks over one second is 4 tok/s. Ollama reports
    eval_duration over the whole response, which is slower, and that slower
    number is the real one.
    """
    measured = GenerationMetrics(completion_tokens=4, completion_seconds=1.0)
    assert measured.tokens_per_second == 4.0
    # A chunk counter would divide by elapsed wall time including the wait for
    # the model to load, inflating the figure. We never see that number.
    assert measured.total_seconds == 0.0


def test_unmeasured_metrics_report_zero_rather_than_raising() -> None:
    """The dashboard polls this constantly; it must never throw."""
    empty = GenerationMetrics(backend="ollama", model="m")
    assert empty.tokens_per_second == 0.0
    assert empty.is_measured is False


def test_is_measured_distinguishes_zero_from_absent() -> None:
    assert GenerationMetrics(completion_tokens=0, completion_seconds=5.0).is_measured is False
    assert GenerationMetrics(completion_tokens=9, completion_seconds=0.0).is_measured is False
    assert GenerationMetrics(completion_tokens=9, completion_seconds=1.0).is_measured is True


def test_malformed_backend_counts_do_not_raise() -> None:
    metrics = GenerationMetrics.from_ollama(
        {"eval_count": "many", "eval_duration": None, "done": True}
    )
    assert metrics.completion_tokens == 0
    assert metrics.tokens_per_second == 0.0


def test_metrics_serialise_for_the_dashboard() -> None:
    payload = GenerationMetrics(
        backend="ollama", model="m", completion_tokens=10, completion_seconds=2.0
    ).to_dict()
    assert payload["tokens_per_second"] == 5.0
    assert payload["is_measured"] is True
    json.dumps(payload)  # must be directly renderable


# --- the fake ---------------------------------------------------------------


def test_fake_backend_yields_chunks_then_metrics() -> None:
    backend = FakeBackend()
    chunks = list(backend.generate("m", "count"))
    assert len(chunks) > 1
    # Only the last chunk is done, and only it carries metrics. An earlier
    # chunk claiming metrics would mean the dashboard could render a
    # throughput number for a generation that had not finished.
    assert all(not c.done for c in chunks[:-1])
    assert all(c.metrics is None for c in chunks[:-1])
    assert chunks[-1].done
    assert chunks[-1].metrics is not None
    assert chunks[-1].metrics.tokens_per_second == 64.0  # 128 tokens / 2s


def test_measure_works_against_the_fake() -> None:
    metrics = measure(FakeBackend(), "m")
    assert metrics is not None
    assert metrics.is_measured
    assert metrics.tokens_per_second == 64.0


def test_measure_returns_none_when_the_backend_is_dead() -> None:
    """A dead backend must produce a dash in the UI, not an exception."""
    assert measure(FakeBackend(available=False), "m") is None


def test_fake_status_is_populated() -> None:
    status = FakeBackend().status()
    assert status.available
    assert status.models and status.running
    assert status.models[0].name == "fake-model"


# --- registry ---------------------------------------------------------------


def test_registry_prefers_exact_backend_names() -> None:
    registry = Registry(backend=FakeBackend(), model="m", extras={"ollama": FakeBackend(name="ollama")})
    registry.set_backend("fake")
    assert registry.backend.name == "fake"


def test_registry_rejects_an_unknown_backend() -> None:
    registry = Registry(backend=FakeBackend(), model="m")
    with pytest.raises(KeyError):
        registry.set_backend("nope")


def test_build_registry_survives_a_dead_ollama() -> None:
    """Startup must not explode when nothing is listening."""
    registry = build_registry(url="http://127.0.0.1:1", timeout=0.2)
    assert registry.backend.name == "ollama"
    assert registry.model == ""


# --- ollama parsing, without a server ---------------------------------------



def _route(monkeypatch, **by_path):
    """Patch `_get_json` with one function that routes on the path.

    Two things to get right. `_get_json` already returns a *dict*, so the
    replacement must too, not a response object. And patching the same
    attribute three times does not give per-path behaviour -- the last
    assignment simply wins, which is how this test first failed against
    /api/version.
    """
    import mathbeast.models.ollama as module

    def fake_get(url, path, timeout):
        if path not in by_path:
            raise AssertionError(f"unexpected path {path!r}")
        value = by_path[path]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(module, "_get_json", fake_get)


def test_models_are_read_from_api_tags(monkeypatch) -> None:
    _route(
        monkeypatch,
        **{
            "/api/tags": {
                "models": [
                    {
                        "name": "qwen2.5:3b",
                        "size": 4_400_000_000,
                        "details": {
                            "family": "qwen2",
                            "parameter_size": "3.1B",
                            "quantization_level": "Q4_K_M",
                        },
                    },
                    {"name": "llama3.2:1b", "size": 1_300_000_000, "details": {}},
                ]
            }
        },
    )
    models = OllamaBackend().list_models()
    assert [m.name for m in models] == ["llama3.2:1b", "qwen2.5:3b"]
    assert models[1].parameter_size == "3.1B"
    assert models[1].quantization == "Q4_K_M"
    assert models[1].size_bytes == 4_400_000_000


def test_running_models_report_vram(monkeypatch) -> None:
    _route(
        monkeypatch,
        **{"/api/ps": {"models": [{"name": "qwen2.5:3b", "size": 4_400_000_000, "size_vram": 0}]}},
    )
    running = OllamaBackend().running()
    assert running[0].size_vram_bytes == 0
    assert running[0].on_gpu is False, "0 VRAM means it is in RAM, not on the GPU"


def test_a_dead_server_is_a_state_not_an_exception(monkeypatch) -> None:
    _route(monkeypatch, **{"/api/tags": urllib.error.URLError("connection refused")})
    status = OllamaBackend().status()
    assert status.available is False
    assert "cannot reach" in status.detail


def test_no_models_installed_is_reported_clearly(monkeypatch) -> None:
    _route(
        monkeypatch,
        **{"/api/tags": {"models": []}, "/api/ps": {"models": []}, "/api/version": {"version": "0.5"}},
    )
    status = OllamaBackend().status()
    assert status.available is True
    assert "ollama pull" in status.detail


def test_status_never_raises_whatever_happens(monkeypatch) -> None:
    import mathbeast.models.ollama as module

    def explode(url, path, timeout):
        raise RuntimeError("something entirely unexpected")

    monkeypatch.setattr(module, "_get_json", explode)
    status = OllamaBackend().status()
    assert isinstance(status, BackendStatus)
    assert status.available is False


def test_generation_yields_metrics_only_on_the_final_chunk(monkeypatch) -> None:
    import mathbeast.models.ollama as module

    lines = [
        {"response": "a "},
        {"response": "b"},
        {
            "response": "",
            "done": True,
            "eval_count": 10,
            "eval_duration": 1_000_000_000,
            "model": "m",
        },
    ]

    def fake_lines(url, path, payload, timeout):
        for line in lines:
            yield line

    monkeypatch.setattr(module, "_post_lines", fake_lines)
    chunks = list(OllamaBackend().generate("m", "hi"))
    assert [c.text for c in chunks[:-1]] == ["a ", "b"]
    assert chunks[-1].done
    assert chunks[-1].metrics.tokens_per_second == 10.0


def test_generation_raises_a_typed_error_when_ollama_is_down(monkeypatch) -> None:
    import mathbeast.models.ollama as module

    def refuse(url, path, payload, timeout):
        raise urllib.error.URLError("down")
        yield {}  # pragma: no cover - makes this a generator

    monkeypatch.setattr(module, "_post_lines", refuse)
    with pytest.raises(OllamaUnavailable):
        list(OllamaBackend().generate("m", "hi"))


def test_model_info_serialises() -> None:
    payload = ModelInfo(name="m", size_bytes=1_500_000_000).to_dict()
    assert payload["size_gb"] == 1.5
    json.dumps(payload)


def test_running_model_serialises() -> None:
    payload = RunningModel(name="m", size_vram_bytes=2_000_000_000).to_dict()
    assert payload["size_vram_gb"] == 2.0
    assert payload["on_gpu"] is True
    json.dumps(payload)