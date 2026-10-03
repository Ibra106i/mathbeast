"""The greeting config. Every case here is a way a hand-edited file goes wrong."""

from __future__ import annotations

import json
import logging

import pytest

from mathbeast.web.config import DEFAULT_TITLE, MAX_TITLE, load_title, save_title


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


# --- writing ----------------------------------------------------------------


def test_a_save_creates_the_directory_it_needs(tmp_path) -> None:
    """A fresh machine has no ~/.mathbeast, and the first save is what makes
    it. Failing here would mean editing the greeting never works once."""
    target = tmp_path / "nested" / "config.json"
    assert save_title("Written fresh", target) == "Written fresh"
    assert load_title(target) == "Written fresh"


def test_the_value_returned_is_the_one_that_will_render(tmp_path) -> None:
    """Stripped on the way in, so the caller must not echo its argument."""
    target = tmp_path / "config.json"
    assert save_title("   spaced out   ", target) == "spaced out"
    assert load_title(target) == "spaced out"


def test_saving_clears_the_key_instead_of_storing_an_empty_string(tmp_path) -> None:
    """`title: ""` in the file beside a placeholder on the page is a
    disagreement the reader has no way to resolve."""
    target = tmp_path / "config.json"
    save_title("A greeting", target)
    save_title("", target)
    assert "title" not in target.read_text(encoding="utf-8")
    assert load_title(target) == DEFAULT_TITLE


def test_a_save_that_clears_leaves_valid_json(tmp_path) -> None:
    """Wiping the last key still writes an object, not an empty file that
    the next load has to special-case."""
    target = tmp_path / "config.json"
    save_title("gone", target)
    save_title("", target)
    assert json.loads(target.read_text(encoding="utf-8")) == {}


def test_saving_does_not_eat_settings_it_does_not_know_about(tmp_path) -> None:
    target = tmp_path / "config.json"
    target.write_text('{"theme": "dark", "title": "old"}', encoding="utf-8")

    save_title("new", target)

    assert json.loads(target.read_text(encoding="utf-8"))["theme"] == "dark"


def test_saving_repairs_a_corrupt_file_rather_than_raising(tmp_path) -> None:
    """The old contents were unusable either way; refusing to write because
    they were broken would leave the file unrecoverable."""
    target = _write(tmp_path, "not json at all")
    assert save_title("recovered", target) == "recovered"
    assert load_title(target) == "recovered"


def test_a_failed_write_says_so(tmp_path) -> None:
    """Swallowing this would look exactly like a save that worked."""
    target = tmp_path / "config.json"
    target.mkdir()  # a directory where the file should be
    with pytest.raises(OSError):
        save_title("anything", target)
