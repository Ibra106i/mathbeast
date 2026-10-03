"""The web surface, tested with no model and no network."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from mathbeast.models import BackendStatus, FakeBackend, Registry
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


class EmptyBackend(FakeBackend):
    """A server that answers and has nothing installed."""

    def status(self) -> BackendStatus:
        return replace(super().status(), models=[], running=[])


def test_the_stage_says_the_backend_is_away_in_words(dead_client) -> None:
    """The home surface used to report this with a dot you have to hover.

    The dot carries the state in its title and the drawer's bar says it in
    full, but the drawer stays shut by default -- while you were looking at
    the composer the page said nothing at all. The colour arrives on the
    pair class rather than in the template: the contrast table measures
    `.notice-down`, the colour test measures the stylesheets, and an inline
    style would sit outside both.
    """
    body = dead_client.get("/").text
    assert 'class="notice notice-down"' in body
    assert "fake is not answering. fake backend disabled" in body
    assert "style=" not in body


def test_the_stage_says_so_when_there_are_no_models() -> None:
    """A server that answers and has nothing to run is its own state.

    The inspector says it over the empty table; the stage has no table to
    stand in for, and the composer's model readout simply vanishes when
    there is no model -- a blank where a name belongs, not a sentence.
    Down is the wrong class for it: nothing is broken, something is
    missing.
    """
    registry = Registry(backend=EmptyBackend(), model="")
    with fastapi_testclient.TestClient(create_app(registry)) as up:
        body = up.get("/").text
    assert 'class="notice"' in body
    assert "notice-down" not in body
    assert "The server is up but has no models." in body
    assert "ollama pull qwen2.5:3b" in body


def test_the_stage_is_quiet_when_the_backend_answers(client) -> None:
    """The capture is a page with a working backend.

    The pixel harness compares the home surface against the reference, and
    a notice that rendered here would fail that comparison on words the
    capture never had. The two broken states get a paragraph; the working
    one gets nothing at all.
    """
    assert "notice" not in client.get("/").text


def test_the_stage_and_the_inspector_say_the_same_thing(dead_client) -> None:
    """Two templates, one sentence each, per state.

    Duplication is fine; drift is not. "unreachable" in one place and "not
    responding" in another is how the same failure starts reading as two
    different problems, so both sentences are pinned at the rendered level
    -- which is the only level a reader sees.
    """
    away = "fake is not answering. fake backend disabled"
    for path in ("/", "/inspector"):
        assert away in dead_client.get(path).text

    registry = Registry(backend=EmptyBackend(), model="")
    with fastapi_testclient.TestClient(create_app(registry)) as up:
        bare = "The server is up but has no models."
        for path in ("/", "/inspector"):
            assert bare in up.get(path).text


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


def test_colour_lives_in_tokens_and_nowhere_else() -> None:
    """A literal that escapes the token file is a correction made in two places.

    A hex is the obvious way to do it. An rgb() written out with numbers is
    the same mistake in a form that never matches "#", which is how the
    drawer's hover, its selected row and its scrim each ended up carrying a
    value nothing could reconcile against the capture.
    """
    static = Path(__file__).resolve().parents[1] / "mathbeast" / "web" / "static"
    escape = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d|hsla?\(\s*\d")
    for path in sorted(static.glob("*.css")):
        if path.name == "tokens.css":
            continue
        found = escape.findall(path.read_text(encoding="utf-8"))
        assert not found, f"{path.name} defines colour itself: {found}"


def _static() -> Path:
    return Path(__file__).resolve().parents[1] / "mathbeast" / "web" / "static"


def _rule_body(path: Path, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", path.read_text(encoding="utf-8"))
    assert match, f"{selector} is not declared in {path.name}"
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _decl(path: Path, selector: str, prop: str) -> str:
    match = re.search(re.escape(prop) + r"\s*:\s*([^;]+);", _rule_body(path, selector))
    assert match, f"{selector} declares no {prop}"
    return match.group(1).strip()


def _stylesheets() -> str:
    return "\n".join(
        (_static() / name).read_text(encoding="utf-8") for name in ("layout.css", "mathbeast.css")
    )


def test_the_drawer_and_the_sidenav_are_one_list_twice() -> None:
    """Hover, focus, press, current and planned are styled twice.

    None of the five states is measured anywhere -- the capture shows no
    drawer open and no page other than the home surface -- which leaves
    agreement between the two shells as the only defence against the same
    state quietly meaning two different things.
    """
    for state in (":hover", ":focus-visible", ":active", ".is-current", ".is-planned"):
        drawer = _rule_body(_static() / "layout.css", ".drawer-link" + state)
        side = _rule_body(_static() / "mathbeast.css", ".navitem" + state)
        assert drawer == side, f"{state} disagrees: {drawer!r} vs {side!r}"

    # The sixth is not a state but the speed of one: a row that eases on the
    # drawer and snaps on the sidenav is the same disagreement wearing a
    # different hat, and it is the one nobody would ever report.
    assert _decl(_static() / "layout.css", ".drawer-link", "transition") == _decl(
        _static() / "mathbeast.css", ".navitem", "transition"
    )


def test_no_element_invents_a_duration_of_its_own() -> None:
    """A `120ms` written beside a transition is a number nobody can change once.

    There are two speeds and a curve, and they live in tokens.css where a
    correction lands in one place. This does not look at `transition-duration`
    in the reduced-motion block -- that one is deliberately not a token, so
    that turning motion off does not depend on the tokens being right.
    """
    for value in re.findall(r"transition:\s*([^;]+);", _stylesheets()):
        literal = re.findall(r"\b\d[\d.]*m?s\b", value)
        assert not literal, f"a transition carries its own duration: {value!r}"
        assert "var(--fast)" in value or "var(--med)" in value, value


def test_asking_for_less_motion_is_answered_once() -> None:
    """The switch lives in the stylesheet every page loads.

    layout.css is loaded after mathbeast.css on the stage, so a rule there
    without `!important` would lose to the transitions it is meant to switch
    off -- which is exactly how a preference ends up honoured on four pages
    and ignored on the one people look at.
    """
    css = (_static() / "mathbeast.css").read_text(encoding="utf-8")
    block = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*)\}\s*$", css)
    assert block, "nothing answers prefers-reduced-motion"
    assert "transition-duration: 0.01ms !important" in block.group(1)
    assert "!important" in block.group(1)


def test_everything_that_takes_focus_says_so_when_it_is_reached() -> None:
    """Focus is the only one of these states a keyboard user ever sees.

    Hover and press are preferences; a ring on focus is the difference
    between a control that can be reached and one that can only be clicked.
    Text fields keep plain `:focus` rather than `:focus-visible`, because
    clicking into a field should show you the field you are in.
    """
    css = _stylesheets()
    for selector in (
        ".chromebtn",
        ".drawer-link",
        ".navitem",
        ".brand",
        ".btn",
        "select",
        ".stage-title__text",
        ".stage-title__input",
        ".composer-input",
        ".composer",
    ):
        assert re.search(re.escape(selector) + r":focus", css), f"{selector} is silent when focused"


def test_a_span_that_is_not_a_control_does_not_pretend_to_be_one() -> None:
    """The plan once asked for hover, focus and active on the status pill.

    The pill and the backend dot are spans with text in them: no href, no
    button, no tabindex, nothing to press. The status pill does not exist
    under any name. Giving the other two a hover state would tell the reader
    something happens when they point at it, and nothing does.
    """
    css = _stylesheets()
    for selector in (".pill", ".badge", ".backenddot"):
        found = re.search(re.escape(selector) + r"(?::hover|:focus|:active)", css)
        assert not found, f"{selector} is styled as though it were a control"


def test_no_page_references_an_external_origin(client) -> None:
    for path in ("/", "/inspector", "/ask", "/practice", "/coverage", "/eval"):
        body = client.get(path).text
        assert "http://" not in body.replace("http://www.w3.org", "")
        assert "https://" not in body.replace("https://www.w3.org", "")

# --- keyboard and screen reader -----------------------------------------------


_FOCUSABLE_TAG = re.compile(r"<(a|button|input|select|textarea)\b([^>]*)>", re.IGNORECASE)
_FOCUS_ATTR = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')


def _focus_stops(body: str) -> list[tuple[str, bool]]:
    """Every control a key press can reach, in document order.

    Returns the accessible name of each stop and whether it is disabled. The
    name is taken the way a screen reader takes it -- aria-label first, then
    id -- so this test and the reader cannot end up talking about two
    different things. The drawer is cut out first: it starts `hidden`, so it
    is not in the reading order until it is opened, and what happens inside
    it is covered by the tests below.
    """
    body = re.sub(r'<aside class="drawer"[\s\S]*?</aside>', "", body)
    stops: list[tuple[str, bool]] = []
    for tag, raw in _FOCUSABLE_TAG.findall(body):
        attrs = dict(_FOCUS_ATTR.findall(raw))
        if tag.lower() == "a" and "href" not in attrs:
            continue
        name = attrs.get("aria-label") or attrs.get("id") or attrs.get("href", "")
        disabled = re.search(r"\sdisabled(\s|=|$)", raw) is not None
        stops.append((name, disabled))
    return stops


def test_the_home_surface_tabs_in_reading_order(client) -> None:
    """The bottom row arrived in one phase, and the tab order with it.

    Read by a key press rather than by eye. The order is what the markup
    happens to give you only while nothing has reordered it, so this pins
    down the shape the screen reader walks: chrome first, then the heading
    it edits, then the field, then the row of controls under it.
    """
    stops = _focus_stops(client.get("/").text)
    assert stops == [
        ("Menu", False),
        ("Back", False),
        ("Forward", False),
        ("stage-title-text", False),
        ("Ask a question", False),
        ("New question", True),
        ("Dictate", True),
        ("Choose model", True),
    ]


def test_the_drawer_keeps_the_tab_key_inside_itself() -> None:
    """The scrim already walls the pointer off from the page behind.

    The tab key needs the same wall or focus walks straight through it: one
    Tab leaves the panel, the next lands on the stage underneath, and nothing
    on screen says which of the two surfaces is answering. Focus starts on
    the first control when the panel opens, so the trap also has to pull
    focus back in when something reaches for it from outside.
    """
    js = (_static() / "mathbeast.js").read_text(encoding="utf-8")
    assert 'if (event.key !== "Tab") return;' in js
    assert "drawer.querySelectorAll(FOCUSABLE)" in js
    assert "!drawer.contains(active)" in js
    assert "event.shiftKey && active === first" in js
    assert "!event.shiftKey && active === last" in js


def test_the_drawer_hands_focus_back_to_whatever_opened_it() -> None:
    """Closing a panel by leaving focus nowhere is how a reader gets stranded.

    Escape closes it with the keyboard, and the keyboard must not end up on
    `<body>` with nothing to press. A click does not move focus in every
    browser, so the toggle itself is the fallback when there is nothing
    better to remember -- and a node that has been swapped out by then is
    dropped rather than focused, since a detached element silently ignores
    it and focus disappears entirely.
    """
    js = (_static() / "mathbeast.js").read_text(encoding="utf-8")
    assert "lastFocus = from && from !== document.body" in js
    assert "document.contains(lastFocus)" in js
    assert "if (document.contains(lastFocus)) lastFocus.focus();" in js


def test_the_status_bar_lives_in_a_region_the_fragment_does_not_own(client) -> None:
    """A polite announcement needs a region that is already on the page.

    `hx-swap="outerHTML"` replaces `#statusbar` on every poll, so a
    `role="status"` written into the fragment would arrive inside the
    previous one and nest a fresh region every four seconds. The region
    belongs to the page that keeps it, and exactly one is rendered.
    """
    for path in ("/", "/inspector"):
        body = client.get(path).text
        assert body.count('class="statusbar-slot"') == 1, path
        assert body.count('role="status"') == 1, path
        assert re.search(
            r'<div class="statusbar-slot" role="status">\s*<div class="statusbar" id="statusbar"',
            body,
        ), path

    fragment = client.get("/api/status-fragment").text
    assert "statusbar-slot" not in fragment
    assert 'role="status"' not in fragment


def test_a_poll_that_changes_nothing_does_not_rewrite_the_page() -> None:
    """Four seconds is a short time to lose focus over nothing.

    The bar polls itself whether or not the answer differs from what is on
    screen, and swapping it anyway clears the live region for no
    announcement and drops focus out of any control inside. The guard reads
    the incoming markup and calls the swap off when it is identical --
    innerHTML, because the element carries `htmx-request` for the length of
    the request, so outerHTML would differ on every poll including the
    no-op ones, and because the picker reports its choice with a `selected`
    attribute, which changes the markup without changing a word of text.
    """
    js = (_static() / "mathbeast.js").read_text(encoding="utf-8")
    assert 'document.body.addEventListener("htmx:beforeSwap"' in js
    assert 'target.classList.contains("statusbar")' in js
    assert "event.detail.serverResponse" in js
    assert "next.innerHTML === target.innerHTML" in js
    assert "event.detail.shouldSwap = false" in js


# --- contrast ------------------------------------------------------------------


#: Every rule that paints text or a field, paired with the colours it paints.
#:
#: Each entry pairs the text with the lightest backdrop that rule can actually
#: render on, because lightest is the worst case for light text and a colour
#: checked against something darker than it ever appears is not checked at
#: all. Translucent colours are composited over the entry in BASE rather than
#: assumed opaque.
PAIRS: dict[str, tuple[str, str]] = {
    ".stage": ("--text", "--bg"),
    ".chromebtn": ("--text-dim", "--bg"),
    ".chromebtn:hover": ("--text", "--wash-hover"),
    ".chromebtn:active": ("--text-dim", "--wash-current"),
    ".drawer-title": ("--text", "--surface-sunken"),
    ".drawer-link": ("--text-dim", "--surface-sunken"),
    ".drawer-link:hover": ("--text", "--wash-hover"),
    ".drawer-link.is-current": ("--text", "--wash-current"),
    ".drawer-link:active": ("--text-dim", "--wash-current"),
    ".drawer-link.is-planned": ("--text-faint", "--surface-sunken"),
    ".stage-title": ("--text", "--bg"),
    ".stage-title__text": ("--text", "--bg"),
    ".stage-title__input": ("--text", "--bg"),
    ".stage-title__error": ("--down-text", "--bg"),
    ".composer-input": ("--text", "--surface"),
    ".composer-input::placeholder": ("--text-faint", "--surface"),
    ".composer-icon": ("--text", "--surface"),
    ".composer-icon--dim": ("--text-dim", "--surface"),
    ".composer-mode": ("--text", "--surface-raised"),
    ".composer-model, .composer-tier": ("--text-dim", "--surface"),
    "html, body": ("--text", "--bg"),
    ".brand": ("--text", "--bg"),
    ".statusbar": ("--text-dim", "--bg"),
    ".pill-local": ("--accent", "--accent-soft"),
    ".pill-cpu": ("--warn", "--warn-soft"),
    ".pill-down": ("--down", "--down-soft"),
    ".muted": ("--text-dim", "--bg"),
    ".navitem": ("--text-dim", "--surface-sunken"),
    ".navitem:hover": ("--text", "--wash-hover"),
    ".navitem:active": ("--text-dim", "--wash-current"),
    ".navitem.is-current": ("--text", "--wash-current"),
    ".navitem.is-planned": ("--text-faint", "--surface-sunken"),
    ".badge": ("--text-faint", "--wash-current"),
    "h2": ("--text-dim", "--bg"),
    ".lede": ("--text-dim", "--bg"),
    ".footnote": ("--text-faint", "--bg"),
    ".notice": ("--text", "--surface-raised"),
    ".notice-down": ("--down-text", "--surface-raised"),
    ".metric-value": ("--text", "--surface"),
    ".metric-empty .metric-value": ("--text-faint", "--surface"),
    ".metric-label": ("--text-faint", "--surface"),
    ".table th": ("--text-faint", "--surface"),
    ".table .is-selected": ("--text", "--accent-faint"),
    "code": ("--text", "--surface-raised"),
    ".btn": ("--text", "--surface-raised"),
    ".btn:hover:not(:disabled)": ("--text", "--accent-soft"),
    "select": ("--text", "--surface-raised"),
}

#: Where a translucent colour sits: the lightest field each rule can land on.
#: A wash over the sunken drawer is not the same colour as the same wash over
#: the page, and the pair has to be judged on the lighter of the two.
BASE: dict[str, str] = {
    ".chromebtn:hover": "--bg",
    ".chromebtn:active": "--bg",
    ".drawer-link:hover": "--surface-sunken",
    ".drawer-link.is-current": "--surface-sunken",
    ".drawer-link:active": "--surface-sunken",
    ".pill-local": "--bg",
    ".pill-cpu": "--bg",
    ".pill-down": "--bg",
    ".navitem:hover": "--surface-sunken",
    ".navitem:active": "--surface-sunken",
    ".navitem.is-current": "--surface-sunken",
    ".badge": "--surface-sunken",
    ".table .is-selected": "--surface",
    ".btn:hover:not(:disabled)": "--surface",
}

#: Rules that paint a field and carry no text of their own -- so there is no
#: text colour to judge. WCAG 1.4.3 covers text; the 1.4.11 contrast of
#: borders, icons-as-decoration and other non-text is out of scope here.
NO_TEXT: set[str] = {
    ".backenddot",
    ".backenddot.is-down",
    ".drawer",
    ".scrim",
    ".composer",
    ".topbar",
    ".sidenav",
    ".panel",
}

_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _painted_rules() -> dict[str, dict[str, str]]:
    """Every rule in either stylesheet that paints a colour, by selector.

    Only the two sheets the page actually loads, and only rules declaring
    `color` or `background` -- a rule that paints nothing has nothing to
    judge, and a selector absent from this map is a rule the audit never
    looked at.
    """
    painted: dict[str, dict[str, str]] = {}
    for name in ("layout.css", "mathbeast.css"):
        text = re.sub(r"/\*.*?\*/", "", (_static() / name).read_text(encoding="utf-8"), flags=re.S)
        for raw, body in _RULE.findall(text):
            selector = " ".join(raw.split())
            decls: dict[str, str] = {}
            for part in body.split(";"):
                if ":" in part:
                    prop, _, value = part.partition(":")
                    decls[prop.strip()] = value.strip()
            if "color" in decls or "background" in decls:
                painted[selector] = decls
    return painted


def _tokens() -> dict[str, str]:
    css = (_static() / "tokens.css").read_text(encoding="utf-8")
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", css))


def _paint(name: str, base: str = "--bg") -> tuple[float, float, float]:
    """The colour a token renders at, with translucency laid over `base`."""
    raw = _tokens()[name].strip()
    match = re.fullmatch(r"rgb\(var\((--[\w-]+)\)(?:\s*/\s*([\d.]+))?\)", raw)
    if match:
        triple = tuple(int(n) for n in _tokens()[match.group(1)].split())
        alpha = float(match.group(2)) if match.group(2) else 1.0
    else:
        match = re.fullmatch(r"rgb\(\s*([\d ]+?)\s*(?:/\s*([\d.]+))?\)", raw)
        if match:
            triple = tuple(int(n) for n in match.group(1).split())
            alpha = float(match.group(2)) if match.group(2) else 1.0
        else:
            assert raw.startswith("#"), f"{name} is not a colour: {raw!r}"
            triple = tuple(int(raw[i : i + 2], 16) for i in (1, 3, 5))
            alpha = 1.0
    if alpha == 1.0:
        return triple  # type: ignore[return-value]
    under = _paint(base, base)
    return tuple(alpha * c + (1 - alpha) * u for c, u in zip(triple, under))  # type: ignore[return-value]


def _channel(value: float) -> float:
    value /= 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = (_channel(float(v)) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg: tuple[float, float, float], bg: tuple[float, float, float]) -> float:
    light, dark = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_the_contrast_table_covers_every_rule_that_paints_something() -> None:
    """A table only defends the rules somebody remembered to write down.

    So it is checked against the stylesheets rather than against itself: any
    rule declaring a colour and missing from the table is a rule nobody has
    looked at, and a table entry that paints nothing is a rule that has been
    renamed or removed and the audit is now quietly checking a string.
    """
    painted = _painted_rules()
    assert set(PAIRS) | NO_TEXT == set(painted), sorted(
        (set(painted) - set(PAIRS) - NO_TEXT) | ((set(PAIRS) | NO_TEXT) - set(painted))
    )
    assert not set(PAIRS) & NO_TEXT


def test_the_table_agrees_with_what_the_stylesheets_say() -> None:
    """The ratio is only useful if the pair in the table is the pair on screen.

    Both halves are read back out of the declarations so a colour changed in
    one place and forgotten in the other fails here rather than in a browser
    nobody has opened. Backgrounds declared as `none` or `transparent` fall
    through to the field underneath and are judged on that instead.
    """
    painted = _painted_rules()
    for selector, (fg, bg) in PAIRS.items():
        decls = painted.get(selector, {})
        colour = decls.get("color")
        if colour and colour.startswith("var("):
            assert colour == f"var({fg})", f"{selector}: {colour} vs table {fg}"
        background = decls.get("background")
        if background and background.startswith("var("):
            assert background == f"var({bg})", f"{selector}: {background} vs table {bg}"


@pytest.mark.parametrize("selector", sorted(PAIRS))
def test_every_colour_pair_the_page_uses_reads_clearly(selector: str) -> None:
    """WCAG 1.4.3 for text: 4.5 to 1 for anything smaller than large.

    Measured rather than eyeballed, and measured on the lightest field the
    rule can land on. Two of these sit within a few hundredths of the line
    -- the placeholder, the metric label, the table header -- so the pairs
    they sit next to are not interchangeable with them.
    """
    fg, bg = PAIRS[selector]
    base = BASE.get(selector, "--bg")
    ratio = _contrast(_paint(fg, base), _paint(bg, base))
    assert ratio >= 4.5, f"{selector}: {fg} on {bg} over {base} is {ratio:.2f}:1"


# --- narrow screens ------------------------------------------------------------
#
# The capture describes a 1622px window and nothing below it, so the desktop
# numbers are the ones compared against it and may not move. The audit run for
# this phase measured the same page at every width down to 320 and reported
# exactly where it stops fitting: a 190px nav column eating the page, a status
# row taller than the bar that clips it, and a bottom row 6px wider than a
# 320px phone. Those are the only things below the line.


def _media_blocks(path: Path) -> list[tuple[str, str]]:
    """Every `@media` block in a stylesheet: its condition and its body.

    Braces are matched by depth rather than by the first `}` -- the bodies
    hold whole rules, and a regex that stopped at the first one would hand
    back a condition with half a stylesheet attached.
    """
    text = path.read_text(encoding="utf-8")
    blocks: list[tuple[str, str]] = []
    at = 0
    while True:
        start = text.find("@media", at)
        if start < 0:
            return blocks
        brace = text.find("{", start)
        depth, i = 1, brace + 1
        while depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        blocks.append((" ".join(text[start + len("@media") : brace].split()), text[brace + 1 : i - 1]))
        at = i


def _without_media(path: Path) -> str:
    """The sheet as it applies at the capture's width: media blocks removed.

    Read off the top level so a value that exists only under a breakpoint
    cannot be mistaken for one the pixel harness will ever see.
    """
    text = path.read_text(encoding="utf-8")
    out, at = [], 0
    while True:
        start = text.find("@media", at)
        if start < 0:
            out.append(text[at:])
            return "".join(out)
        out.append(text[at:start])
        depth, i = 1, text.find("{", start) + 1
        while depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        at = i


def _declared(css: str, selector: str, prop: str) -> str:
    """One declaration of one selector, read out of stylesheet text."""
    match = re.search(re.escape(selector) + r"\s*\{([^{}]*)\}", css)
    assert match, f"{selector} is not declared where the test looked"
    decl = re.search(rf"(?<![\w-]){re.escape(prop)}\s*:\s*([^;]+);", match.group(1))
    assert decl, f"{selector} declares no {prop}"
    return decl.group(1).strip()


def test_both_sheets_agree_on_where_narrow_begins() -> None:
    """A breakpoint is one number, not two opinions.

    640px is where the composer stops being the measured 597px box: 640 minus
    the stage's own 40px of padding is 600, and below that the row can never
    be the row in the capture. One query per sheet, the same condition, and
    the stage rule paired with it is the 8px a side the 320px audit asked for
    -- 259px of bottom row against 253px of room.
    """
    for name in ("layout.css", "mathbeast.css"):
        narrow = [
            cond
            for cond, _ in _media_blocks(_static() / name)
            if cond.startswith("(max-width:")
        ]
        assert narrow == ["(max-width: 640px)"], f"{name}: {narrow}"

    stage = dict(_media_blocks(_static() / "layout.css"))["(max-width: 640px)"]
    assert _declared(stage, ".stage-main", "padding-inline") == "12px"


def test_measured_geometry_lives_outside_every_media_query() -> None:
    """The capture's numbers are the ones at 1622px, and only those.

    Each of these was read off the rendered page in the phase that measured
    it. A value living inside a breakpoint cannot move a desktop pixel, and
    one living outside it cannot answer a phone -- so the split is what keeps
    the two audits from drifting apart.
    """
    stage = _without_media(_static() / "layout.css")
    shell = _without_media(_static() / "mathbeast.css")

    assert _declared(stage, ".stage-main", "padding-inline") == "20px"
    assert _declared(stage, ".stage-main", "padding-bottom") == "126px"
    assert _declared(stage, ".stage-block", "max-width") == "var(--composer-width)"
    assert _declared(stage, ".composer", "min-height") == "var(--composer-min-height)"
    assert _declared(stage, ".composer-bar", "min-height") == "25px"
    assert _declared(shell, ".shell", "grid-template-columns") == "190px minmax(0, 1fr)"
    assert _declared(shell, ".topbar", "min-height") == "54px"
    assert _declared(shell, ".sidenav", "top") == "var(--topbar-h, 54px)"


def test_the_narrow_query_touches_only_what_the_audit_reported() -> None:
    """Below the line, only what was measured to fail may move.

    The inspector's audit reported the nav column, the sideways-scrolling
    document and the status row clipped by its bar; the stage's reported the
    padding. Anything else reaching into a media query is a desktop number
    waiting to drift, so the selectors are named rather than counted.
    """
    expected = {
        "layout.css": {".stage-main"},
        "mathbeast.css": {".shell", ".sidenav", ".navitem", ".content"},
    }
    for name, want in expected.items():
        got: set[str] = set()
        for cond, body in _media_blocks(_static() / name):
            if not cond.startswith("(max-width:"):
                continue
            for raw, _decls in _RULE.findall(body):
                got.update(sel.strip() for sel in raw.split(","))
        assert got == want, f"{name}: {sorted(got ^ want)}"


def test_the_height_the_bar_grows_to_is_handed_to_the_sticky_nav() -> None:
    """The sidenav sits under a bar whose height lives in the DOM.

    The status row wraps from one line to five across this range, so the bar
    grows with text no stylesheet can count -- measured at -11.5px above the
    top of the window at 768 with a fixed 54, and -41.8px at 360. The script
    measures what it grew to; the CSS falls back to 54, the unwrapped height,
    whenever it has not run; and the nav's own height is taken from the same
    number so it ends at the viewport rather than at a constant.
    """
    js = (_static() / "mathbeast.js").read_text(encoding="utf-8")
    assert 'document.documentElement.style.setProperty("--topbar-h"' in js
    assert "syncTopbarHeight();" in js
    css = (_static() / "mathbeast.css").read_text(encoding="utf-8")
    assert "var(--topbar-h, 54px)" in css
