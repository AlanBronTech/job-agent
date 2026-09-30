"""The local UI's FastAPI app: security wrapper, templates, static files.

No workflow logic lives in `web/`. Handlers build a `Workspace`, call
`jobagent.services`, and render what comes back.

Three layers keep it to Alan and his own browser (research R6):

1. `jobagent ui` binds 127.0.0.1 only, so nothing else on the network connects.
2. Every request must carry `Host: 127.0.0.1:<port>` or `localhost:<port>`.
   That defeats DNS rebinding, where a page in another tab points its own
   hostname at 127.0.0.1 and reads the UI as if it were same-origin.
3. Every POST must carry the per-start token, as a form field matching the
   cookie. Any page in the same browser can *send* a POST to localhost; without
   this, one could start a scoring run of its choosing and spend money.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData

from jobagent.services.workspace import Workspace

HERE = Path(__file__).parent
CSRF_COOKIE = "jobagent_csrf"


def create_app(
    *,
    workspace_factory: Callable[[], Workspace],
    config,
    port: int,
    token: str,
    runner=None,
    today: Callable[[], date] = date.today,
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.workspace_factory = workspace_factory
    app.state.config = config
    app.state.runner = runner
    app.state.token = token
    app.state.today = today
    app.state.templates = Jinja2Templates(directory=HERE / "templates")
    app.state.templates.env.globals["csrf_field"] = "csrf"

    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.headers.get("host") not in allowed_hosts:
            return PlainTextResponse("Forbidden: this UI only answers on localhost.", 403)
        # The URL `jobagent ui` opens carries the token once. Swap it for a
        # cookie and drop it from the address bar and the history.
        if request.method == "GET" and "t" in request.query_params:
            if not secrets.compare_digest(request.query_params["t"], token):
                return PlainTextResponse("Forbidden: stale link. Use the one `jobagent ui` opened.", 403)
            response = RedirectResponse(request.url.path, status_code=303)
            response.set_cookie(
                CSRF_COOKIE, token, httponly=True, samesite="strict", path="/"
            )
            return response
        return await call_next(request)

    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    from jobagent.web import routes

    app.include_router(routes.router)
    return app


async def checked_form(request: Request) -> FormData:
    """The POST body, after proving it came from a page this server rendered.

    Every POST handler calls this first. The cookie proves the browser opened
    the link `jobagent ui` printed; the form field proves the form was rendered
    by this server, which another site cannot read to copy.
    """
    token = request.app.state.token
    form = await request.form()
    field = form.get("csrf")
    cookie = request.cookies.get(CSRF_COOKIE)
    if not (
        isinstance(field, str)
        and cookie
        and secrets.compare_digest(field, token)
        and secrets.compare_digest(cookie, token)
    ):
        raise HTTPException(403, "Forbidden: this form did not come from the local UI.")
    return form


def workspace(request: Request) -> Workspace:
    return request.app.state.workspace_factory()


def render(request: Request, name: str, context: dict, status_code: int = 200):
    """Render a page. Every page carries the banner of finished, unseen runs (FR-016b)."""
    from jobagent.services import runs

    try:
        unseen = runs.unseen_finished(workspace(request))
    except Exception:  # the banner must never take a page down with it
        unseen = []
    context = {
        "token": request.app.state.token,
        "unseen": unseen,
        "here": request.url.path,
        **context,
    }
    return request.app.state.templates.TemplateResponse(
        request, name, context, status_code=status_code
    )
