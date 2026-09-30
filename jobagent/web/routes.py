"""Routes for the local UI. Each one builds a Workspace, calls services, renders.

Nothing here decides anything. If a handler needs an `if` about the domain
rather than about HTTP, that `if` belongs in `jobagent.services`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from jobagent.services import listing
from jobagent.services.refusals import NoSuchAd
from jobagent.web.app import render, workspace

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
