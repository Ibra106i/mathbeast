"""The web surface, tested with no model and no network."""

from __future__ import annotations

import pytest

from mathbeast.models import FakeBackend, Registry
from mathbeast.web import create_app

fastapi_testclient = pytest.importorskip("fastapi.testclient")


@pytest.fixture()
def client():
    registry = Registry(backend=FakeBackend(), model="fake-model")
    with fastapi_testclient.TestClient(create_app(registry)) as test_client:
        yield test_client


@pytest.fixture()
def dead_client():
    registry = Registry(backend=FakeBackend(available=False), model="")
    with fastapi_testclient.TestClient(create_app(registry)) as test_client:
        yield test_client


# --- pages ------------------------------------------------------------------


def test_root_renders_the_home_stage(client) -> None:
    """`/` is the composer, not a redirect into model statistics.

    The inspector stays reachable, but a first-time visitor should land on
    the thing they came to use.
    """
    response = client.get("/")
    assert response.status_code == 200
    assert 'class="stage"' in response.text


def test_the_stage_drawer_is_hidden_without_javascript(client) -> None:
    """`hidden` is the default, so a failed script leaves a closed menu.

    The alternative -- an open drawer -- would cover the page it was meant
    to navigate away from.
    """
    body = client.get("/").text
    assert '<aside class="drawer" id="drawer" hidden>' in body
    assert 'class="scrim" data-drawer-close hidden' in body


def test_the_inspector_is_still_reachable_from_the_root(client) -> None:
    body = client.get("/").text
    assert 'href="/inspector"' in body


@pytest.mark.parametrize("path", ["/", "/inspector"])
def test_the_document_starts_with_the_doctype(client, path) -> None:
    """Whitespace ahead of the doctype is stripped, not merely tolerated.

    The shared shell begins with a comment; without whitespace control the
    newline it sits on is emitted first.
    """
    body = client.get(path).text
    assert body.lstrip().startswith("<!DOCTYPE html>")
    assert not body.startswith((" ", "\n", "\t"))


def test_inspector_renders(client) -> None:
    response = client.get("/inspector")
    assert response.status_code == 200
    assert "Model inspector" in response.text


def test_status_bar_is_present_and_polls(client) -> None:
    body = client.get("/inspector").text
    assert 'hx-get="/api/status-fragment"' in body
    assert "every 4s" in body


def test_model_picker_lists_the_backend_model(client) -> None:
    body = client.get("/inspector").text
    assert 'value="fake-model"' in body
    assert "selected" in body


def test_unreachable_backend_reads_differently() -> None:
    """A dead server must never look like a working one."""
    registry = Registry(backend=FakeBackend(available=False), model="")
    with fastapi_testclient.TestClient(create_app(registry)) as dead:
        body = dead.get("/inspector").text
    assert "unreachable" in body.lower()
    assert "not answering" in body.lower() or "cannot reach" in body.lower()
    assert "backend unavailable" in body


def test_planned_views_say_so_rather_than_404(client) -> None:
    for view in ("ask", "practice", "coverage", "eval"):
        response = client.get(f"/{view}")
        assert response.status_code == 200
        assert "Not built yet" in response.text


def test_an_unknown_path_is_still_a_404(client) -> None:
    assert client.get("/nonsense").status_code == 404


def test_nav_marks_unbuilt_views(client) -> None:
    body = client.get("/inspector").text
    assert "soon" in body
    assert "is-planned" in body


# --- api --------------------------------------------------------------------


def test_status_api_returns_json(client) -> None:
    payload = client.get("/api/status").json()
    assert payload["available"] is True
    assert payload["name"] == "fake"
    assert payload["models"][0]["name"] == "fake-model"


def test_status_fragment_is_html_not_json(client) -> None:
    """The browser never assembles the status bar itself."""
    response = client.get("/api/status-fragment")
    assert "text/html" in response.headers["content-type"]
    assert "statusbar" in response.text


def test_selecting_a_model_updates_the_status_bar(client) -> None:
    response = client.post("/api/model", params={"model": "fake-model"})
    assert response.status_code == 200
    assert "fake-model" in response.text


def test_measure_returns_a_real_throughput_number(client) -> None:
    response = client.post("/api/measure")
    assert response.status_code == 200
    assert "tok/s" in response.text
    assert "64.0" in response.text  # 128 tokens over 2 seconds


def test_measure_shows_a_dash_when_there_is_no_model(dead_client) -> None:
    """An absent measurement must not look like zero."""
    response = dead_client.post("/api/measure")
    assert "not measured" in response.text
    assert ">0.0<" not in response.text


def test_measure_survives_a_dead_backend(dead_client) -> None:
    response = dead_client.post("/api/measure")
    assert response.status_code == 200


# --- assets -----------------------------------------------------------------


def test_htmx_is_served_locally_not_from_a_cdn(client) -> None:
    """A CDN link would break the offline promise on first load."""
    response = client.get("/static/vendor/htmx.min.js")
    assert response.status_code == 200
    assert len(response.content) > 10_000


def test_the_sse_extension_is_vendored(client) -> None:
    response = client.get("/static/vendor/sse.js")
    assert response.status_code == 200
    assert b"sse-swap" in response.content


def test_css_is_served(client) -> None:
    assert client.get("/static/mathbeast.css").status_code == 200
    assert client.get("/static/tokens.css").status_code == 200
    assert client.get("/static/layout.css").status_code == 200


def test_no_page_references_an_external_origin(client) -> None:
    for path in ("/", "/inspector", "/ask", "/practice", "/coverage", "/eval"):
        body = client.get(path).text
        assert "http://" not in body.replace("http://www.w3.org", "")
        assert "https://" not in body.replace("https://www.w3.org", "")