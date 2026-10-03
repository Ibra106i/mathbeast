"""The one user-editable setting the web surface has.

Deliberately a plain file rather than a database or a cookie. The point of the
line is that anyone can open it, change it, and be done -- a settings table
for a single string would be more machinery than the feature, and a cookie
would forget the edit on another machine while claiming to be the same app.

Everything here is read-only; writing lands with the editor that produces it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

#: The placeholder shown until the user writes their own. Not branding -- a
#: greeting the user owns is why the line exists.
DEFAULT_TITLE = "Coffee and Claude time?"

#: Ceiling on what the greeting may become, in characters.
#:
#: Not arbitrary: at 34px inside a 615px column, 80 characters already runs to
#: three lines and pushes the composer off centre. Longer than that and the
#: stage stops looking like the thing it was modelled on. The editor enforces
#: the same number, so the file and the page can never disagree.
MAX_TITLE = 80

#: Where settings live. Hidden and per-user because the value is a personal
#: greeting, not something a machine-wide install should share.
CONFIG_DIR = Path.home() / ".mathbeast"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_title(path: Path | None = None) -> str:
    """Return the greeting the user has set, or the placeholder.

    Three of the four failure modes are quiet on purpose: no file is the
    normal state of a fresh install, a directory instead of a file is an
    oddity nobody needs a message about, and an unreadable file falls back
    the same way a missing one does.

    The fourth -- a file that exists but is not valid JSON -- is loud. Somebody
    opened it and edited it, so they should learn the edit did not take rather
    than wonder why the title quietly reverted.
    """
    target = path or CONFIG_FILE

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DEFAULT_TITLE
    except json.JSONDecodeError as exc:
        log.warning(
            "%s is not valid JSON (%s); using the default greeting",
            target,
            exc.msg,
        )
        return DEFAULT_TITLE
    except OSError as exc:
        log.warning("could not read %s (%s); using the default greeting", target, exc)
        return DEFAULT_TITLE

    # A JSON array or string is a plausible mistake when hand-editing; only an
    # object can carry a title, so anything else falls through.
    if not isinstance(raw, dict):
        log.warning("%s does not contain a JSON object; using the default greeting", target)
        return DEFAULT_TITLE

    title = raw.get("title")
    if not isinstance(title, str):
        # Present but wrong type (a number, a list, null). Also a silent
        # fallback: the key exists, which means the file was written on
        # purpose, but there is nothing here worth reporting.
        return DEFAULT_TITLE

    title = title.strip()
    if not title:
        # Whitespace-only is how an editor leaves a field someone meant to
        # fill in later. Not a broken file.
        return DEFAULT_TITLE

    if len(title) > MAX_TITLE:
        # Clamped rather than rejected: refusing to load because a greeting
        # is 81 characters would take down the whole page over a caption.
        # It is not logged either -- every request would repeat it, and the
        # editor will not produce this state in the first place.
        return title[:MAX_TITLE]

    return title


def save_title(value: str, path: Path | None = None) -> str:
    """Write the greeting and return it as the page will show it.

    The return value is not the argument. What lands on disk is stripped and
    clamped, and what the page will render falls back to the placeholder when
    the result is empty -- so the caller gets the effective string rather than
    echoing back something that was never stored.

    Existing keys survive. A file holding other settings must not lose them
    because somebody renamed their greeting.
    """
    target = path or CONFIG_FILE

    existing: dict[str, object] = {}
    try:
        previous = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(previous, dict):
            existing = previous
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        # Starting from nothing is right for a new file. For a file that is
        # there but broken, this write is the repair -- the old contents
        # were unusable either way, so there is nothing to preserve and
        # nothing to warn about on every save.
        pass

    title = (value or "").strip()[:MAX_TITLE]

    if title:
        existing["title"] = title
    else:
        # Cleared means unset, not "the empty string is my greeting". Leaving
        # `title: ""` behind would make the file disagree with the page to
        # anyone who opened it in an editor.
        existing.pop("title", None)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        # Surfaced to the route, which turns it into a message the editor can
        # show. Swallowing it would look like a save that silently did nothing.
        log.error("could not write %s (%s)", target, exc)
        raise

    return load_title(target)
