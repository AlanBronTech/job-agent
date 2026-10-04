"""Routes for the local UI. Each one builds a Workspace, calls services, renders.

Nothing here decides anything. If a handler needs an `if` about the domain
rather than about HTTP, that `if` belongs in `jobagent.services`.
"""

from __future__ import annotations

import subprocess

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse, RedirectResponse

from jobagent.adapters.llm import RunContext
from jobagent.services import (
    ads,
    costs,
    documents,
    listing,
    outputs,
    readiness,
    reapply,
    runs,
    scoring,
)
from jobagent.services.refusals import (
    AdNotFound,
    BadUpload,
    NoSuchAd,
    NothingSelected,
    NotScored,
    RunInProgress,
    UnreadableAd,
)
from jobagent.web import work
from jobagent.web.app import checked_form, render, workspace

router = APIRouter()


@router.get("/")
def ad_list(request: Request, sort: str = "date"):
    sort = sort if sort in {"date", "score"} else "date"
    rows = listing.ad_rows(workspace(request), today=request.app.state.today(), sort=sort)
    return render(request, "list.html", {"nav": "ads", "rows": rows, "sort": sort})


@router.get("/ads/{jd_id:int}")
def ad_page(request: Request, jd_id: int):
    try:
        detail = listing.ad_detail(workspace(request), jd_id, today=request.app.state.today())
    except NoSuchAd:
        return render(
            request,
            "error.html",
            {"heading": "No such ad", "detail": f"There is no job description with id {jd_id}."},
            status_code=404,
        )
    ws = workspace(request)
    runs.mark_seen_for_jd(ws, jd_id)
    return render(
        request,
        "detail.html",
        {
            "nav": "ads",
            "d": detail,
            "run": runs.active_run_for(ws, jd_id) or _recent(runs.last_run_for(ws, jd_id)),
            "reapply": reapply.check(ws, jd_id, request.app.state.today()),
        },
    )


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


@router.get("/runs/{run_id}")
def run_status(request: Request, run_id: int):
    """The run fragment, polled every 2 s while running.

    When a poll finds the run finished, HX-Refresh reloads the page, which then
    shows the new state of the ad and marks the run seen.
    """
    run = runs.get_run(workspace(request), run_id)
    if run is None:
        return PlainTextResponse("No such run.", 404)
    response = render(request, "_run.html", {"run": run})
    if run.finished and request.headers.get("HX-Request"):
        response.headers["HX-Refresh"] = "true"
    return response


@router.post("/runs/{run_id}/seen")
async def run_seen(request: Request, run_id: int):
    form = await checked_form(request)
    runs.mark_seen(workspace(request), run_id)
    back = str(form.get("next") or "/")
    # Only ever back to a page of this UI.
    if not back.startswith("/") or back.startswith("//"):
        back = "/"
    return RedirectResponse(back, status_code=303)


def _recent(run):
    """A finished run is shown on its ad's page for half a day, then left to history."""
    if run is None or run.finished_at is None:
        return run
    from datetime import datetime, timedelta, timezone

    return run if datetime.now(timezone.utc) - run.finished_at < timedelta(hours=12) else None


# --------------------------------------------------------------------------- #
# Generate: confirm (free) → start (spends) → the ad page shows the run
# --------------------------------------------------------------------------- #


def _generate_choice(form) -> dict:
    questions = [
        line.strip() for line in str(form.get("questions") or "").splitlines() if line.strip()
    ]
    return {
        "resume": form.get("resume") == "1",
        "cover": form.get("cover") == "1",
        "questions": questions,
        "overrule": form.get("overrule") == "1",
        "supersede": form.get("supersede") == "1",
    }


def _generate_confirm(request: Request, jd_id: int, choice: dict, problem: str | None = None):
    """The confirmation page. Everything on it is free to compute."""
    ws = workspace(request)
    config = request.app.state.config
    today = request.app.state.today()
    try:
        plan = documents.plan(
            ws, jd_id, resume=choice["resume"], cover=choice["cover"],
            answers=bool(choice["questions"]), when=today,
        )
    except NothingSelected:
        return _back_to_ad(request, jd_id, "Choose at least one document to generate.")
    except NotScored:
        return _back_to_ad(request, jd_id, "Score this ad first: generation is shaped by the assessment.")
    except NoSuchAd:
        return render(request, "error.html", {"heading": "No such ad",
                      "detail": f"There is no job description with id {jd_id}."}, status_code=404)
    estimate = costs.estimate(
        ws, config, "generate",
        resume=choice["resume"], cover=choice["cover"], answers=bool(choice["questions"]),
    )
    return render(
        request,
        "generate_confirm.html",
        {
            "nav": "ads",
            "plan": plan,
            "choice": choice,
            "estimate": costs.describe(estimate),
            "missing": readiness.missing(ws, config, "generate"),
            "problem": problem,
        },
        status_code=409 if problem else 200,
    )


def _back_to_ad(request: Request, jd_id: int, problem: str):
    try:
        detail = listing.ad_detail(workspace(request), jd_id, today=request.app.state.today())
    except NoSuchAd:
        return render(request, "error.html", {"heading": "No such ad",
                      "detail": f"There is no job description with id {jd_id}."}, status_code=404)
    return render(request, "detail.html", {"nav": "ads", "d": detail, "problem": problem,
                                           "run": None}, status_code=409)


@router.post("/ads/{jd_id}/generate/confirm")
async def generate_confirm(request: Request, jd_id: int):
    form = await checked_form(request)
    return _generate_confirm(request, jd_id, _generate_choice(form))


@router.post("/ads/{jd_id}/generate")
async def generate_start(request: Request, jd_id: int):
    form = await checked_form(request)
    choice = _generate_choice(form)
    if form.get("confirmed") != "1":
        return _generate_confirm(request, jd_id, choice, "Nothing was started: confirm the cost first.")

    ws = workspace(request)
    config = request.app.state.config
    today = request.app.state.today()
    try:
        plan = documents.plan(
            ws, jd_id, resume=choice["resume"], cover=choice["cover"],
            answers=bool(choice["questions"]), when=today,
        )
    except (NothingSelected, NotScored, NoSuchAd):
        return _generate_confirm(request, jd_id, choice)
    # The same refusals the service would raise, checked here only so the page
    # can say so before a run exists. The service checks them again.
    if isinstance(plan.reapply, (reapply.SameJob, reapply.PossiblySame)):
        return _generate_confirm(request, jd_id, choice,
                                 "Nothing was started: this looks like a job you applied for recently.")
    if plan.needs_overrule and not choice["overrule"]:
        return _generate_confirm(request, jd_id, choice,
                                 "The assessment says skip. Tick the overrule box to generate anyway.")
    if plan.clashes and not choice["supersede"]:
        return _generate_confirm(request, jd_id, choice,
                                 "Documents already exist. Tick the box to keep them under a dated name.")
    missing = readiness.missing(ws, config, "generate")
    if missing:
        return _generate_confirm(request, jd_id, choice, "Nothing was started: " + " ".join(missing))

    ctx = RunContext(command="generate", jd_id=jd_id, source="ui")
    try:
        request.app.state.runner.start(
            ws,
            kind="generate",
            jd_id=jd_id,
            run_id=ctx.run_id,
            request={
                "title": plan.jd.title,
                "resume": choice["resume"],
                "cover": choice["cover"],
                "answers": len(choice["questions"]),
                "overrule": choice["overrule"],
                "supersede": choice["supersede"],
            },
            work=work.generate(
                ws, config, ctx, jd_id,
                resume=choice["resume"], cover=choice["cover"], questions=choice["questions"],
                overrule=choice["overrule"], supersede=choice["supersede"], today=today,
            ),
        )
    except RunInProgress:
        pass  # the ad page shows the run already going
    return RedirectResponse(f"/ads/{jd_id}", status_code=303)


@router.get("/runs/{run_id}/view")
def run_view(request: Request, run_id: int):
    """A run with no ad page to show it yet: adding an ad.

    Once it has succeeded and created the ad, go straight to the ad.
    """
    ws = workspace(request)
    run = runs.get_run(ws, run_id)
    if run is None:
        return render(request, "error.html", {"heading": "No such run", "detail": ""}, status_code=404)
    if run.finished and run.status == "succeeded" and run.jd_id:
        return RedirectResponse(f"/ads/{run.jd_id}", status_code=303)
    if run.finished:
        runs.mark_seen(ws, run_id)
    return render(request, "run_page.html", {"nav": "add", "run": run})


# --------------------------------------------------------------------------- #
# Add an ad: choose (free) → confirm (free) → start (spends)
# --------------------------------------------------------------------------- #


@router.get("/ads/new")
def add_form(request: Request, problem: str | None = None):
    ws = workspace(request)
    try:
        newest = ads.latest_ad(ws.jd_dir).name
    except AdNotFound:
        newest = None
    return render(request, "add.html", {"nav": "add", "newest": newest, "jd_dir": ws.jd_dir,
                                        "accepted": ", ".join(sorted(ads.AD_SUFFIXES)),
                                        "problem": problem},
                  status_code=409 if problem else 200)


async def _add_input(request: Request, form, ws):
    """The ad the form points at, as (AdInput, file name or None). Writes an upload into JD_DIR."""
    mode = form.get("mode")
    if mode == "paste":
        text = str(form.get("text") or "").strip()
        if not text:
            raise BadUpload("Paste the ad's text first.")
        return ads.read_ad(text=text), None
    if mode == "upload":
        upload = form.get("upload")
        if upload is None or not getattr(upload, "filename", ""):
            raise BadUpload("Choose a file first.")
        data = await upload.read(ads.MAX_UPLOAD_BYTES + 1)
        path = ads.save_upload(ws, upload.filename, data)
    elif mode == "latest":
        path = ads.latest_ad(ws.jd_dir)
    elif mode == "saved":
        path = ads.saved_ad(ws, str(form.get("name") or ""))
    else:
        raise BadUpload("Choose how to add the ad.")
    return ads.read_ad(file=path), path.name


def _add_confirm(request: Request, ad, name: str | None, source: str, problem: str | None = None):
    ws = workspace(request)
    config = request.app.state.config
    return render(
        request,
        "add_confirm.html",
        {
            "nav": "add",
            "ad": ad,
            "name": name,
            "source": source,
            "estimate": costs.describe(costs.estimate(ws, config, "add_ad")),
            "missing": readiness.missing(ws, config, "add_ad"),
            "problem": problem,
        },
        status_code=409 if problem else 200,
    )


@router.post("/ads/new/confirm")
async def add_confirm(request: Request):
    form = await checked_form(request)
    ws = workspace(request)
    try:
        ad, name = await _add_input(request, form, ws)
    except (BadUpload, AdNotFound, UnreadableAd) as refusal:
        return add_form(request, problem=str(refusal))
    return _add_confirm(request, ad, name, str(form.get("source") or ""))


@router.post("/ads/new")
async def add_start(request: Request):
    form = await checked_form(request)
    ws = workspace(request)
    config = request.app.state.config
    source = str(form.get("source") or "").strip() or None
    try:
        ad, name = await _add_input(request, form, ws)
    except (BadUpload, AdNotFound, UnreadableAd) as refusal:
        return add_form(request, problem=str(refusal))
    if form.get("confirmed") != "1":
        return _add_confirm(request, ad, name, source or "", "Nothing was started: confirm the cost first.")
    if ad.truncated:
        return _add_confirm(request, ad, name, source or "", "This capture is incomplete; nothing was started.")
    missing = readiness.missing(ws, config, "add_ad")
    if missing:
        return _add_confirm(request, ad, name, source or "", "Nothing was started: " + " ".join(missing))

    ctx = RunContext(command="jd add", source="ui")
    try:
        run = request.app.state.runner.start(
            ws, kind="add_ad", jd_id=None, run_id=ctx.run_id,
            request={"title": name or "a pasted ad", "input_key": ads.input_key(ad), "source": source},
            work=work.add_ad(ws, config, ctx, ad, source=source),
        )
    except RunInProgress as going:
        run = going.run_id
    return RedirectResponse(f"/runs/{run}/view", status_code=303)


# --------------------------------------------------------------------------- #
# Score: confirm (free) → start (spends) → the ad page shows the run
# --------------------------------------------------------------------------- #


def _score_confirm(request: Request, jd_id: int, force: bool, problem: str | None = None):
    ws = workspace(request)
    config = request.app.state.config
    try:
        jd, seen_before = scoring.load(ws, jd_id)
    except NoSuchAd:
        return render(request, "error.html", {"heading": "No such ad",
                      "detail": f"There is no job description with id {jd_id}."}, status_code=404)
    return render(
        request,
        "score_confirm.html",
        {
            "nav": "ads",
            "jd": jd,
            "history": seen_before,
            "force": force,
            "estimate": costs.describe(costs.estimate(ws, config, "score")),
            "missing": readiness.missing(ws, config, "score"),
            "reapply": reapply.check(ws, jd_id, request.app.state.today()),
            "problem": problem,
        },
        status_code=409 if problem else 200,
    )


@router.post("/ads/{jd_id}/score/confirm")
async def score_confirm(request: Request, jd_id: int):
    await checked_form(request)
    return _score_confirm(request, jd_id, force=False)


@router.post("/ads/{jd_id}/score")
async def score_start(request: Request, jd_id: int):
    form = await checked_form(request)
    force = form.get("force") == "1"
    if form.get("confirmed") != "1":
        return _score_confirm(request, jd_id, force, "Nothing was started: confirm the cost first.")
    ws = workspace(request)
    config = request.app.state.config
    try:
        jd, _ = scoring.load(ws, jd_id)
    except NoSuchAd:
        return _score_confirm(request, jd_id, force)
    # Checked again by the service; here only so the page can say so first.
    if isinstance(reapply.check(ws, jd_id, request.app.state.today()), (reapply.SameJob, reapply.PossiblySame)):
        return _score_confirm(request, jd_id, force, "Nothing was started: this looks like a job you applied for recently.")
    if jd.thin and not force:
        return _score_confirm(request, jd_id, force,
                              "Too little ad text to score. Tick the box to score it anyway.")
    missing = readiness.missing(ws, config, "score")
    if missing:
        return _score_confirm(request, jd_id, force, "Nothing was started: " + " ".join(missing))

    ctx = RunContext(command="score", jd_id=jd_id, source="ui")
    try:
        request.app.state.runner.start(
            ws, kind="score", jd_id=jd_id, run_id=ctx.run_id,
            request={"title": jd.title, "force": force},
            work=work.score(ws, config, ctx, jd_id, force=force),
        )
    except RunInProgress:
        pass
    return RedirectResponse(f"/ads/{jd_id}", status_code=303)



@router.post("/ads/{jd_id}/reapply")
async def reapply_decide(request: Request, jd_id: int):
    """Same job / different job / overrule, for one ad. Free."""
    form = await checked_form(request)
    decision = str(form.get("decision") or "")
    if decision not in {"same", "different", "overrule"}:
        return PlainTextResponse("Unknown decision.", 400)
    ws = workspace(request)
    try:
        state = reapply.check(ws, jd_id, request.app.state.today())
        reapply.decide(ws, jd_id, decision, getattr(getattr(state, "match", None), "against", ""))
    except NoSuchAd:
        return PlainTextResponse("No such ad.", 404)
    back = str(form.get("next") or f"/ads/{jd_id}")
    if not back.startswith("/") or back.startswith("//"):
        back = f"/ads/{jd_id}"
    return RedirectResponse(back, status_code=303)
