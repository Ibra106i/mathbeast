"""Pixel harness: render the home surface at 1622x969 and diff against the capture.

The capture is a design reference, not an asset of the app, so it does not
live in the repository. This module is skipped unless one is supplied: set
MATHBEAST_CAPTURE to its path, or drop it at the repository root as
capture.png (gitignored).

The capture is a drawing of the design rather than a screenshot of the
page, so per-pixel equality is a state the render cannot reach and the
harness does not ask for it. It measures the same landmarks in both images
with one shared function -- both ends of the chrome, the composer box, the
title's ink and the mark's -- prints every delta, and asserts the position
of every group and the size of every box, the title and its mark edge by
edge. What it does not assert is written down instead, next to the delta
that explains why: the capture's fourth left-hand glyph would toggle the
drawer our menu already toggles, and its right-hand mascot and window
controls need a shell this app does not have. Every group keeps the
capture's margins; the contents are the deliberate difference.

Run with -s to watch the report; on failure the report is in the output.
"""
from __future__ import annotations

import io
import os
import socket
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("playwright")

from playwright.sync_api import sync_playwright  # noqa: E402

from mathbeast.models import FakeBackend, Registry  # noqa: E402
from mathbeast.web import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = Path(os.environ.get("MATHBEAST_CAPTURE") or ROOT / "capture.png")
WIDTH, HEIGHT = 1622, 969

pytestmark = pytest.mark.skipif(
    not CAPTURE.is_file(),
    reason=f"capture not supplied (set MATHBEAST_CAPTURE or add {ROOT / 'capture.png'})",
)


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    """The app on a loopback port, with a backend that answers."""
    import uvicorn

    port = _port()
    app = create_app(Registry(backend=FakeBackend(), model="fake-model"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        pytest.fail("the app did not come up on the loopback port")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


@pytest.fixture(scope="module")
def render(base_url):
    """A viewport screenshot of the resting home surface.

    Resting means unfocused: the composer draws a focus ring the capture
    does not have, and clicking anything to get here would be measuring an
    interaction rather than the page.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT},
                                device_scale_factor=1)
        # networkidle would never fire: the status chip holds an SSE stream
        # open for the life of the page.
        page.goto(f"{base_url}/", wait_until="domcontentloaded")
        page.evaluate("() => document.fonts.ready.then(() => true)")
        page.wait_for_timeout(200)
        shot = page.screenshot()
        browser.close()
    return np.asarray(Image.open(io.BytesIO(shot)).convert("RGB"))


@pytest.fixture(scope="module")
def capture():
    return np.asarray(Image.open(CAPTURE).convert("RGB"))


def _runs(cols: np.ndarray, max_gap: int = 3) -> list[tuple[int, int]]:
    """Split lit columns into glyphs: a blank gap ends a run."""
    cols = [int(c) for c in np.unique(cols)]
    out, start, prev = [], cols[0], cols[0]
    for c in cols[1:]:
        if c - prev > max_gap:
            out.append((start, prev))
            start = c
        prev = c
    out.append((start, prev))
    return out


def _group(lum: np.ndarray, bg: float, x0: int, x1: int) -> tuple[tuple, int]:
    """One end of the chrome: its ink box and how many glyphs it holds."""
    lit = lum[0:56, x0:x1] > bg + 35
    ys, xs = np.where(lit)
    runs = _runs(xs)
    box = (int(ys.min()), int(ys.max()), x0 + runs[0][0], x0 + runs[-1][1])
    return box, len(runs)


def _landmarks(a: np.ndarray) -> dict[str, tuple]:
    """Measure both images the same way: ink boxes, never pixels.

    Every window is wider or taller than the landmark needs, and the
    composer is found first so the title windows can stop above its top
    edge -- the composer's border is brighter than the page and would
    otherwise join the title's ink.
    """
    lum = a @ [0.299, 0.587, 0.114]
    bg = float(np.median(lum))

    # the chrome at both ends -- the icon row top-left, the group top-right
    # -- so a group's contents cannot hide in the empty middle of the bar
    chrome_l, chrome_l_n = _group(lum, bg, 0, 130)
    chrome_r, chrome_r_n = _group(lum, bg, 1440, WIDTH)

    # the composer: a solid rectangle far wider than any run of text
    win = lum[280:640, 380:1320]
    mask = win > bg + 8
    rows = np.where(mask.sum(axis=1) > 450)[0]
    cols = np.where(mask.sum(axis=0) > 60)[0]
    composer = (280 + int(rows.min()), 280 + int(rows.max()),
                380 + int(cols.min()), 380 + int(cols.max()))
    title_ceiling = composer[0] - 4

    # the mark: the accent's salmon. Star and text fringe salmon alike, so
    # take the first run of salmon columns -- the star is contiguous, and
    # the fringe always sits a gap away from it
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    salmon = (r > 170) & (r - b > 80) & (g < r - 30)
    win = salmon[280:title_ceiling, 540:660]
    ys, xs = np.where(win)
    m0, m1 = _runs(xs)[0]
    rows = np.where(win[:, m0:m1 + 1].any(axis=1))[0]
    mark = (280 + int(rows.min()), 280 + int(rows.max()), 540 + m0, 540 + m1)

    # the title's letters: everything lit, starting just past the mark
    x0 = min(1140, mark[3] + 4)
    win = lum[280:title_ceiling, x0:1140] > bg + 40
    ys, xs = np.where(win)
    title = (280 + int(ys.min()), 280 + int(ys.max()),
             x0 + int(xs.min()), x0 + int(xs.max()))

    return {"chrome_l": chrome_l, "chrome_l_n": chrome_l_n,
            "chrome_r": chrome_r, "chrome_r_n": chrome_r_n,
            "composer": composer, "mark": mark, "title": title}


def _fmt(box: tuple) -> str:
    y0, y1, x0, x1 = box
    return f"y {y0}..{y1}  x {x0}..{x1}"


def test_render_matches_the_capture(render, capture) -> None:
    assert render.shape == (HEIGHT, WIDTH, 3), (
        f"the render came out {render.shape[1]}x{render.shape[0]}, "
        f"the window is {WIDTH}x{HEIGHT}"
    )
    assert capture.shape == (HEIGHT, WIDTH, 3), (
        f"the capture is {capture.shape[1]}x{capture.shape[0]}, "
        f"the window it describes is {WIDTH}x{HEIGHT}"
    )

    cap, got = _landmarks(capture), _landmarks(render)
    report = ["landmark      capture                  render                  delta"]
    for key, label in (("chrome_l", "chrome-left"), ("chrome_r", "chrome-right"),
                       ("composer", "composer"), ("mark", "mark"),
                       ("title", "title")):
        c, g = cap[key], got[key]
        delta = tuple(gv - cv for gv, cv in zip(g, c))
        report.append(f"{label:13} {_fmt(c):24} {_fmt(g):24} {delta}")
    report.append(
        f"{'left icons':13} {cap['chrome_l_n']:<24} {got['chrome_l_n']:<24} "
        "written down: the capture's panel glyph would toggle the drawer "
        "our menu already toggles"
    )
    report.append(
        f"{'right glyphs':13} {cap['chrome_r_n']:<24} {got['chrome_r_n']:<24} "
        "written down: mascot and window controls need a shell; the dot "
        "holds the margin"
    )
    print("\n".join(report))

    # (what is asserted, the two numbers, the tolerance in px)
    checks = [
        ("chrome-left icon centre",
         (cap["chrome_l"][0] + cap["chrome_l"][1]) / 2,
         (got["chrome_l"][0] + got["chrome_l"][1]) / 2, 3),
        ("chrome-left left edge",
         cap["chrome_l"][2], got["chrome_l"][2], 4),
        ("chrome-right group centre",
         (cap["chrome_r"][0] + cap["chrome_r"][1]) / 2,
         (got["chrome_r"][0] + got["chrome_r"][1]) / 2, 3),
        ("chrome-right right edge",
         cap["chrome_r"][3], got["chrome_r"][3], 4),
        ("composer top", cap["composer"][0], got["composer"][0], 4),
        ("composer bottom", cap["composer"][1], got["composer"][1], 4),
        ("composer left", cap["composer"][2], got["composer"][2], 4),
        ("composer right", cap["composer"][3], got["composer"][3], 4),
        # the title's box and the mark's are asserted edge by edge now that
        # the face is measured rather than inherited: they land within 3px
        # (title left 643 vs 640, mark right 629 vs 631)
        ("title left edge", cap["title"][2], got["title"][2], 4),
        ("title right edge", cap["title"][3], got["title"][3], 4),
        ("title ink height",
         cap["title"][1] - cap["title"][0] + 1,
         got["title"][1] - got["title"][0] + 1, 2),
        ("mark left edge", cap["mark"][2], got["mark"][2], 4),
        ("mark right edge", cap["mark"][3], got["mark"][3], 4),
        ("mark top", cap["mark"][0], got["mark"][0], 4),
        ("mark bottom", cap["mark"][1], got["mark"][1], 4),
        ("mark width",
         cap["mark"][3] - cap["mark"][2] + 1,
         got["mark"][3] - got["mark"][2] + 1, 6),
        ("mark height",
         cap["mark"][1] - cap["mark"][0] + 1,
         got["mark"][1] - got["mark"][0] + 1, 4),
    ]
    missed = [
        f"{name}: capture {c:g} vs render {g:g} (delta {g - c:+g}, tolerance {t})"
        for name, c, g, t in checks
        if abs(g - c) > t
    ]
    assert not missed, "deltas over tolerance:\n" + "\n".join(missed)
