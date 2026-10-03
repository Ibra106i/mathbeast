"""Pixel harness: render the home surface at 1622x969 and diff against the capture.

The capture is a design reference, not an asset of the app, so it does not
live in the repository. This module is skipped unless one is supplied: set
MATHBEAST_CAPTURE to its path, or drop it at the repository root as
capture.png (gitignored).

The capture is a drawing of the design rather than a screenshot of the
page, so per-pixel equality is a state the render cannot reach and the
harness does not ask for it. It measures the same landmarks in both images
with one shared function -- the chrome icons, the composer box, the title's
ink and the mark's -- prints every delta, and asserts only the ones a phase
claims to have landed. Text width is reported and not asserted: which
typeface draws it is P19's question, not this one.

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


def _landmarks(a: np.ndarray) -> dict[str, tuple]:
    """Measure both images the same way: ink boxes, never pixels.

    Every window is wider or taller than the landmark needs, and the
    composer is found first so the title windows can stop above its top
    edge -- the composer's border is brighter than the page and would
    otherwise join the title's ink.
    """
    lum = a @ [0.299, 0.587, 0.114]
    bg = float(np.median(lum))

    # the three buttons of the chrome, top-left
    band = lum[0:56, 0:130] > bg + 35
    ys, xs = np.where(band)
    chrome = (int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max()))

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
    cols = np.unique(xs)
    run = [int(cols[0])]
    for c in cols[1:]:
        if c - run[-1] > 3:
            break
        run.append(int(c))
    rows = np.where(win[:, run[0]:run[-1] + 1].any(axis=1))[0]
    mark = (280 + int(rows.min()), 280 + int(rows.max()),
            540 + run[0], 540 + run[-1])

    # the title's letters: everything lit, starting just past the mark
    x0 = min(1140, mark[3] + 4)
    win = lum[280:title_ceiling, x0:1140] > bg + 40
    ys, xs = np.where(win)
    title = (280 + int(ys.min()), 280 + int(ys.max()),
             x0 + int(xs.min()), x0 + int(xs.max()))

    return {"chrome": chrome, "composer": composer, "mark": mark, "title": title}


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
    for name in ("chrome", "composer", "mark", "title"):
        c, g = cap[name], got[name]
        delta = tuple(gv - cv for gv, cv in zip(g, c))
        report.append(f"{name:13} {_fmt(c):24} {_fmt(g):24} {delta}")
    report.append(
        f"{'title width':13} {cap['title'][3] - cap['title'][2] + 1:<24} "
        f"{got['title'][3] - got['title'][2] + 1:<24} "
        f"reported, not asserted: the typeface is P19"
    )
    report.append(
        f"{'mark left/right':13} "
        f"x {cap['mark'][2]}..{cap['mark'][3]:<20} "
        f"x {got['mark'][2]}..{got['mark'][3]:<20} "
        f"reported, not asserted: the block is centred on the title's width"
    )
    print("\n".join(report))

    # (what is asserted, the two numbers, the tolerance in px)
    checks = [
        ("chrome icon centre",
         (cap["chrome"][0] + cap["chrome"][1]) / 2,
         (got["chrome"][0] + got["chrome"][1]) / 2, 3),
        ("composer top", cap["composer"][0], got["composer"][0], 4),
        ("composer bottom", cap["composer"][1], got["composer"][1], 4),
        ("composer left", cap["composer"][2], got["composer"][2], 4),
        ("composer right", cap["composer"][3], got["composer"][3], 4),
        ("title ink height",
         cap["title"][1] - cap["title"][0] + 1,
         got["title"][1] - got["title"][0] + 1, 3),
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
