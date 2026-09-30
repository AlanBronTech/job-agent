"""Routes for the local UI. Each one builds a Workspace, calls services, renders.

Nothing here decides anything. If a handler needs an `if` about the domain
rather than about HTTP, that `if` belongs in `jobagent.services`.
"""

from __future__ import annotations

import subprocess

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from jobagent.services import listing, outputs
from jobagent.services.refusals import NoSuchAd
from jobagent.web.app import checked_form, render, workspace

router = APIRouter()


@router.get("/")
def ads(request: Request, sort: str = "date"):
    sort = sort if sort in {"date", "score"} else "date"
    rows = listing.ad_rows(workspace(request), today=request.app.state.today(), sort=sort)
    return render(request, "list.html", {"nav": "ads", "rows": rows, "sort": sort})


@router.get("/ads/{jd_id}")
def ad(request: Request, jd_id: int):
    try:
        detail = listing.ad_detail(workspace(request), jd_id, today=request.app.state.today())
    except NoSuchAd:
        return render(
            request,
            "error.html",
            {"heading": "No such ad", "detail": f"There is no job description with id {jd_id}."},
            status_code=404,
        )
    return render(request, "detail.html", {"nav": "ads", "d": detail})


# Plain form POSTs answered with 204: the browser stays on the page, and the
# document opens in Word or the folder in Finder on this machine.


@router.post("/ads/{jd_id}/documents/open")
async def open_document(request: Request, jd_id: int):
    form = await checked_form(request)
    return _desktop(
        lambda: outputs.open_document(
            workspace(request), jd_id, str(form.get("folder", "")),
            str(form.get("name", "")), request.app.state.today(),
        )
    )


@router.post("/ads/{jd_id}/documents/reveal")
async def reveal_folder(request: Request, jd_id: int):
    form = await checked_form(request)
    return _desktop(
        lambda: outputs.reveal_folder(
            workspace(request), jd_id, str(form.get("folder", "")), request.app.state.today()
        )
    )


def _desktop(action) -> Response:
    try:
        action()
    except (NoSuchAd, FileNotFoundError, ValueError):
        return PlainTextResponse("Not a document listed for this ad.", 404)
    except subprocess.CalledProcessError as exc:
        return PlainTextResponse(f"Could not open it: {exc}", 500)
    return Response(status_code=204)
