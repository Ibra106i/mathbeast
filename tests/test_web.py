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


def test_the_greeting_is_the_editable_placeholder(client) -> None:
    """The default text ships, and ships as something meant to be replaced.

    It is not the product name: a greeting the user owns is the point of the
    line, so a fresh install shows the placeholder rather than our branding.
    """
    body = client.get("/").text
    assert "Coffee and Claude time?" in body
    assert 'class="stage-title"' in body
    # Decorative mark must not be announced; the h1 reads as words alone.
    assert '<span class="stage-title__mark" aria-hidden="true">' in body


def test_the_greeting_comes_from_the_user_config(client, monkeypatch, tmp_path) -> None:
    """Editing the file must change the page, not just the module.

    The route reads per request precisely so a hand edit takes effect on the
    next reload; this is the test that says it does.
    """
    from mathbeast.web import config

    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    assert "Coffee and Claude time?" in client.get("/").text

    (tmp_path / "config.json").write_text(
        '{"title": "Late night with partial fractions"}', encoding="utf-8"
    )
    body = client.get("/").text
    assert "Late night with partial fractions" in body
    assert "Coffee and Claude time?" not in body


def test_the_editor_is_told_the_ceiling_rather_than_reimplementing_it(client) -> None:
    """The field must never reject text the file would have accepted.

    Duplicating the number in JavaScript is how the two drift apart and a
    greeting silently stops saving.
    """
    from mathbeast.web.config import MAX_TITLE

    assert 'data-max-title="%d"' % MAX_TITLE in client.get("/").text


# --- the composer -----------------------------------------------------------


def test_the_composer_is_a_box_you_can_type_into(client) -> None:
    """One textarea in a form, with the capture's row beneath it.

    The pills, the send button, the attachments are all chrome bolted around
    a text field, so the field is what has to be right first. The row that
    landed under it is chrome too, and is held to the same rule the rest of
    the page is: anything the box claims to do that it cannot yet do does not
    belong in it yet.
    """
    body = client.get("/").text
    assert '<form class="composer" action="/ask" method="get">' in body
    assert 'id="composer-input"' in body
    assert 'placeholder="How can I help you today?"' in body


def test_the_composer_bar_shows_what_is_true_and_hides_what_is_not(
    client,
) -> None:
    """The bottom row is the capture's chrome, not a set of live controls.

    It is here so there is a row to compare against the reference, and every
    glyph in it is a button marked disabled. That is the whole difference
    between a control nobody has wired up yet and one that is broken: the
    first is a promise about a later phase, the second is a lie about now.
    The labels beside them are readouts rather than controls, so they stay
    plain text -- which is also why they can say what they say.
    """
    body = client.get("/").text

    assert '<div class="composer-bar">' in body
    assert '<span class="composer-mode">Chat</span>' in body
    assert '<span class="composer-tier">Medium</span>' in body
    # The model readout is the model the backend is really running, so the
    # span exists whenever one is configured rather than holding a name
    # MathBeast has no way to have.
    assert '<span class="composer-model">' in body

    for label in ("New question", "Dictate", "Choose model"):
        assert f'aria-label="{label}"' in body
    assert body.count('type="button" disabled') >= 3


def test_the_composer_sends_the_question_where_the_truth_is_told(client) -> None:
    """Its action is a view that exists and is honest about not existing.

    Pointing a form at a URL that 404s would be worse than the input not
    being there. `/ask` says plainly that it is unimplemented, and it is
    also the address the real thing will live at -- so the form does not
    need rewriting when it arrives, only the page behind it.
    """
    import re

    body = client.get("/").text
    action = re.search(r'<form class="composer" action="([^"]+)"', body).group(1)

    response = client.get(action, params={"q": "3x + 7 = 25"})

    assert response.status_code == 200
    assert "<h1>Ask</h1>" in response.text
    assert "Not built yet" in response.text


def test_the_composer_does_not_put_its_answer_where_it_could_be_lost(
    client,
) -> None:
    """The question is sent as a GET, not as a POST.

    Nothing is written: there is no session to write to, no store to write
    to, and a form that quietly posts somewhere it cannot persist would be
    the one part of this page lying about what it does.
    """
    response = client.post("/ask", data={"q": "3x + 7 = 25"})
    # /ask is declared GET-only, so a POST is refused rather than accepted
    # and forgotten.
    assert response.status_code == 405


def test_the_composer_names_itself_without_relying_on_the_placeholder(
    client,
) -> None:
    """A placeholder is a hint, not a label: it is gone the moment a single
    character is typed, and the field has to stay named after that."""
    assert 'aria-label="Ask a question"' in client.get("/").text


# --- saving the greeting ----------------------------------------------------


@pytest.fixture()
def user_config(monkeypatch, tmp_path):
    """Point the config at a temp file so a test cannot touch a real home dir."""
    from mathbeast.web import config

    target = tmp_path / ".mathbeast" / "config.json"
    monkeypatch.setattr(config, "CONFIG_FILE", target)
    return target


def test_the_greeting_saves_from_a_form_body(client, user_config) -> None:
    response = client.post("/api/title", data={"title": "Three seconds to spare"})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "title": "Three seconds to spare"}
    assert "Three seconds to spare" in client.get("/").text


def test_a_cleared_greeting_writes_nothing_and_shows_the_default(
    client, user_config
) -> None:
    """An empty string is not a greeting someone chose; it is an unset field.

    The file must not end up holding `title: ""` while the page shows the
    placeholder -- anyone opening it would wonder which one was wrong.
    """
    client.post("/api/title", data={"title": "  "})
    assert user_config.exists()
    assert "title" not in user_config.read_text(encoding="utf-8")

    assert "Coffee and Claude time?" in client.get("/").text


def test_saving_the_greeting_keeps_the_rest_of_the_file(client, user_config) -> None:
    """A file holding other settings must not lose them because somebody
    renamed a caption."""
    import json

    user_config.parent.mkdir(parents=True, exist_ok=True)
    user_config.write_text('{"theme": "dark"}', encoding="utf-8")

    client.post("/api/title", data={"title": "Still here"})

    assert json.loads(user_config.read_text(encoding="utf-8")) == {
        "theme": "dark",
        "title": "Still here",
    }


def test_an_overlong_greeting_is_clamped_and_the_response_says_so(
    client, user_config
) -> None:
    """What comes back is what will render, not what was sent."""
    from mathbeast.web.config import MAX_TITLE

    response = client.post("/api/title", data={"title": "z" * 400})
    assert response.json()["title"] == "z" * MAX_TITLE


def test_an_unwritable_config_reports_a_failure_rather_than_a_silent_save(
    client, monkeypatch, tmp_path
) -> None:
    """A save that cannot land must not answer 200 -- the editor would wipe
    the user's text and then tell them it worked."""
    from mathbeast.web import config

    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")

    def refuse(*args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(config.Path, "mkdir", refuse)
    monkeypatch.setattr(config.Path, "write_text", refuse)

    response = client.post("/api/title", data={"title": "anything"})
    assert response.status_code == 500
    assert response.json()["ok"] is False


def test_a_round_trip_shows_exactly_what_the_file_holds(client, user_config) -> None:
    """Save then read: what the page shows is what the file holds."""
    client.post("/api/title", data={"title": "  Pinned to the board  "})
    body = client.get("/").text
    assert "Pinned to the board" in body
    assert "  Pinned to the board  " not in body
    assert '"title": "Pinned to the board"' in user_config.read_text(encoding="utf-8")


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


def test_the_model_picker_its_body_actually_reaches_the_registry() -> None:
    """The picker posts a form. That is the shape the browser sends.

    The endpoint used to declare `model: str = ""`, which FastAPI reads from
    the query string, so every real click fell through to `if model:` and did
    nothing -- while the test above passed, because it sent `params=`. A test
    that exercises the transport the feature actually uses is the only kind
    that would have caught it.
    """
    registry = Registry(backend=FakeBackend(), model="fake-model")
    with fastapi_testclient.TestClient(create_app(registry)) as client:
        response = client.post("/api/model", data={"model": "other-model"})

    assert response.status_code == 200
    assert registry.model == "other-model"


def test_the_query_string_still_selects_a_model() -> None:
    """The old signature accepted a query parameter, so it stays accepted.

    Fixing the form path must not quietly break whoever wrote against the
    declaration that was there before.
    """
    registry = Registry(backend=FakeBackend(), model="fake-model")
    with fastapi_testclient.TestClient(create_app(registry)) as client:
        client.post("/api/model", params={"model": "third-model"})

    assert registry.model == "third-model"


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