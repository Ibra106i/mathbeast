"""The greeting config. Every case here is a way a hand-edited file goes wrong."""

from __future__ import annotations

import json
import logging

import pytest

from mathbeast.web.config import DEFAULT_TITLE, MAX_TITLE, load_title


def _write(tmp_path, payload):
    target = tmp_path / "config.json"
    target.write_text(payload, encoding="utf-8")
    return target


def _write_json(tmp_path, value):
    return _write(tmp_path, json.dumps(value))


# --- the happy path ---------------------------------------------------------


def test_a_fresh_install_shows_the_placeholder(tmp_path) -> None:
    """No file is the normal case, not a failure to report."""
    assert load_title(tmp_path / "config.json") == DEFAULT_TITLE


def test_the_placeholder_is_the_documented_text() -> None:
    assert DEFAULT_TITLE == "Coffee and Claude time?"


def test_a_configured_title_wins(tmp_path) -> None:
    target = _write_json(tmp_path, {"title": "Right then, calculus."})
    assert load_title(target) == "Right then, calculus."


def test_surrounding_whitespace_is_not_part_of_the_title(tmp_path) -> None:
    target = _write_json(tmp_path, {"title": "  Bring snacks  "})
    assert load_title(target) == "Bring snacks"


# --- ways a hand-edited file breaks ----------------------------------------


def test_invalid_json_falls_back_and_says_so(tmp_path, caplog) -> None:
    """Someone edited it, so they should learn the edit did not take.

    Silently reverting would have them wondering why their change vanished.
    """
    target = _write(tmp_path, '{"title": "no trailing brace"')
    with caplog.at_level(logging.WARNING):
        assert load_title(target) == DEFAULT_TITLE
    assert any("not valid JSON" in r.message for r in caplog.records)


def test_an_empty_file_falls_back(tmp_path) -> None:
    assert load_title(_write(tmp_path, "")) == DEFAULT_TITLE


@pytest.mark.parametrize("payload", ["[]", '"just a string"', "42", "null"])
def test_a_non_object_top_level_falls_back(tmp_path, payload, caplog) -> None:
    """A plausible slip when hand-editing, and worth a message."""
    with caplog.at_level(logging.WARNING):
        assert load_title(_write(tmp_path, payload)) == DEFAULT_TITLE
    assert any("does not contain a JSON object" in r.message for r in caplog.records)


def test_a_missing_title_key_falls_back(tmp_path) -> None:
    assert load_title(_write_json(tmp_path, {"theme": "dark"})) == DEFAULT_TITLE


@pytest.mark.parametrize("value", [7, True, ["x"], None])
def test_a_non_string_title_falls_back(tmp_path, value) -> None:
    """The key exists, so the file was written on purpose -- but there is
    nothing here worth reporting."""
    assert load_title(_write_json(tmp_path, {"title": value})) == DEFAULT_TITLE


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_an_empty_title_falls_back(tmp_path, value) -> None:
    """How an editor leaves a field someone meant to fill in later."""
    assert load_title(_write_json(tmp_path, {"title": value})) == DEFAULT_TITLE


def test_an_unreadable_path_falls_back(tmp_path) -> None:
    """A directory where the file should be must not take the page down."""
    target = tmp_path / "config.json"
    target.mkdir()
    assert load_title(target) == DEFAULT_TITLE


# --- the ceiling ------------------------------------------------------------


def test_an_absurdly_long_title_is_clamped_not_rejected(tmp_path) -> None:
    """Refusing to load over a 90-character greeting would break the page
    for the sake of a caption."""
    target = _write_json(tmp_path, {"title": "x" * 500})
    result = load_title(target)
    assert len(result) == MAX_TITLE
    assert result == "x" * MAX_TITLE


def test_the_ceiling_allows_a_realistic_greeting(tmp_path) -> None:
    """The clamp must not bite the length it exists to permit."""
    target = _write_json(tmp_path, {"title": "a" * MAX_TITLE})
    assert load_title(target) == "a" * MAX_TITLE
