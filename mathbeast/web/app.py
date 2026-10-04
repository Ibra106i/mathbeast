"""The web app. One surface: `mathbeast serve` starts it, and that is it.

The factory takes a registry rather than building one, so the tests can inject
`FakeBackend` and never need Ollama. That is the whole reason this module takes
a dependency at all rather than reaching for a global.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from mathbeast.models import Registry, build_registry, measure
from mathbeast.web.config import MAX_TITLE, load_title, save_title

HERE = Path(__file__).parent
TEMPLATES = HERE / "templates"
STATIC = HERE / "static"

#: Views that exist. Anything not listed here renders as an honest stub rather
#: than a 404, because a nav item that leads nowhere is worse than one that
#: says it isn't built yet.
IMPLEMENTED_VIEWS = {"inspector"}
PLANNED_VIEWS = ("ask", "practice", "coverage", "eval")


def create_app(registry: Registry | None = None) -> FastAPI:
    reg = registry or build_registry()

    app = FastAPI(title="MathBeast", docs_url=None, redoc_url=None)
    app.state.registry = reg
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES))

    def base_context(request: Request) -> dict[str, Any]:
        return {
            "request": request,
            "backend_name": reg.backend.name,
            "backend_kind": reg.backend.kind,
            "model": reg.model,
            "views": PLANNED_VIEWS,
            "implemented": IMPLEMENTED_VIEWS,
        }

    # -- pages ---------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def index(request: Request) -> HTMLResponse:
        """The home surface: title and composer, full stop.

        It used to redirect to the inspector, which meant the first thing a new
        user saw was a table of model statistics. That is the right page for
        someone checking a backend, and the wrong one for someone here to solve
        a problem.
        """
        status = reg.backend.status()
        return templates.TemplateResponse(
            request,
            "stage.html",
            {
                **base_context(request),
                "status": status,
                "models": status.models,
                # Read per request, not once at startup: editing the file by
                # hand is a supported way to change this, and a value cached
                # behind a running server would not show up until it restarted.
                "stage_title": load_title(),
                # Reaches the field as a data attribute so the editor can
                # never reject text the file would have taken.
                "max_title": MAX_TITLE,
                # Nothing on the stage is a "view", so no nav item is current.
                "current": "",
            },
        )

    @app.get("/inspector", response_class=HTMLResponse)
    def inspector(request: Request) -> HTMLResponse:
        status = reg.backend.status()
        return templates.TemplateResponse(
            request,
            "inspector.html",
            {
                **base_context(request),
                "status": status,
                "models": status.models,
                "running": status.running,
                "current": "inspector",
            },
        )

    @app.get("/{view}", response_class=HTMLResponse)
    def planned(request: Request, view: str) -> HTMLResponse:
        if view not in PLANNED_VIEWS:
            return HTMLResponse("<h1>404</h1>", status_code=404)
        # The status bar lives in the base template, so every view needs a
        # status whether or not it cares about one.
        status = reg.backend.status()
        return templates.TemplateResponse(
            request,
            "planned.html",
            {
                **base_context(request),
                "status": status,
                "models": status.models,
                "view": view,
                "current": view,
            },
        )

    # -- api -----------------------------------------------------------------

    @app.get("/api/status")
    def api_status() -> JSONResponse:
        return JSONResponse(reg.backend.status().to_dict())

    @app.get("/api/status-fragment", response_class=HTMLResponse)
    def api_status_fragment(request: Request) -> HTMLResponse:
        """The status bar, polled.

        A fragment rather than JSON so the browser never has to assemble the
        status bar out of fields: the server owns what it looks like.
        """
        status = reg.backend.status()
        return templates.TemplateResponse(
            request,
            "_status_bar.html",
            {
                **base_context(request),
                "status": status,
                "models": status.models,
            },
        )

    async def posted(request: Request, key: str) -> str:
        """One field from a posted form, falling back to the query string.

        A body, not a query string: that is what htmx sends for
        `<form hx-post>`. Reading one needs python-multipart, hence its place
        in the web extra -- Starlette raises before it ever looks at the
        content type, so leaving it out makes every POST here fail.

        The query fallback is not decoration. `POST /api/model` was declared
        as a plain query parameter, so that is the only shape its test ever
        exercised, and a caller written against that signature would have
        started failing the moment the form path was fixed. Accepting both
        keeps it working and costs one branch.
        """
        value = (await request.form()).get(key)
        if value is None:
            value = request.query_params.get(key)
        return str(value) if value is not None else ""

    @app.post("/api/model", response_class=HTMLResponse)
    async def api_model(request: Request) -> HTMLResponse:
        """Switch the model, and answer both pickers in one response.

        The drawer's select swaps the status bar; the composer's select sits
        outside it and swaps a readout, so the fragment carries the bar and
        an out-of-band span carries the readout. Each caller asks only for
        the target it owns and gets the other one for free.
        """
        model = await posted(request, "model")
        if model:
            reg.set_model(model)
        status = reg.backend.status()
        return templates.TemplateResponse(
            request,
            "_model_picked.html",
            {**base_context(request), "status": status, "models": status.models},
        )

    @app.post("/api/title")
    async def api_title(request: Request) -> JSONResponse:
        """Save the greeting the home surface greets with.

        JSON rather than an HTML fragment because the editor owns this
        interaction: it swaps the heading for an input and back itself, and
        all it needs from the server is what actually got stored. The rest of
        the surface hands markup over to the server; here the swap is a
        focus-management problem, and splitting that across a template and a
        client script would be worse than either alone.
        """
        try:
            title = save_title(await posted(request, "title"))
        except OSError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        return JSONResponse({"ok": True, "title": title})

    @app.post("/api/measure", response_class=HTMLResponse)
    def api_measure(request: Request) -> HTMLResponse:
        """Measure throughput by actually generating something.

        Deliberately not a calculation: a tok/s figure invented from a table
        would be the exact kind of confident wrong number this project is
        against. If no model is selected or the backend is down, the fragment
        renders a dash.
        """
        metrics = measure(reg.backend, reg.model) if reg.model else None
        return templates.TemplateResponse(
            request,
            "_metrics.html",
            {**base_context(request), "metrics": metrics},
        )

    return app


app = create_app()