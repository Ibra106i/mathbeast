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

HERE = Path(__file__).parent
TEMPLATES = HERE / "templates"
STATIC = HERE / "static"

#: What the home surface greets with. Not the product name -- it is the one
#: line on the page a user is meant to overwrite, so it ships as a placeholder
#: rather than something chosen for them. The user's own text, once set,
#: takes precedence over this.
STAGE_TITLE = "Coffee and Claude time?"

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
                "stage_title": STAGE_TITLE,
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

    @app.post("/api/model", response_class=HTMLResponse)
    def api_model(request: Request, model: str = "") -> HTMLResponse:
        if model:
            reg.set_model(model)
        status = reg.backend.status()
        return templates.TemplateResponse(
            request,
            "_status_bar.html",
            {**base_context(request), "status": status, "models": status.models},
        )

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