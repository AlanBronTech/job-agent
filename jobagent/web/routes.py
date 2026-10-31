"""Routes for the local UI. Each one builds a Workspace, calls services, renders.

Nothing here decides anything. If a handler needs an `if` about the domain
rather than about HTTP, that `if` belongs in `jobagent.services`.
"""

from __future__ import annotations

import subprocess
from datetime import datetime

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse, RedirectResponse

from jobagent.adapters.llm import RunContext
from jobagent.core.models import ApplicationStatus, DocumentKind
from jobagent.services import (
    ads,
    batches,
    costs,
    documents,
    listing,
    outputs,
    pipeline,
    readiness,
    reapply,
    revise,
    runs,
    scoring,
    screening,
    sent,
)
from jobagent.services.refusals import (
    AdNotFound,
    BadUpload,
    NoGeneratedCopy,
    NoModel,
    NoSuchAd,
    NothingSelected,
    NotScored,
    ProfileInvalid,
    ProfileMissing,
    RunInProgress,
    SentFileUnusable,
    UnreadableAd,
)
from jobagent.web import work
from jobagent.web.app import checked_form, config_of, render, workspace

router = APIRouter()


@router.get("/")
def ad_list(request: Request, sort: str = "date"):
    sort = sort if sort in {"date", "score"} else "date"
    rows = listing.ad_rows(workspace(request), today=request.app.state.today(), sort=sort)
    return render(request, "list.html", {"nav": "ads", "rows": rows, "sort": sort})


@router.get("/ads/{jd_id:int}")
def ad_page(request: Request, jd_id: int, saved: int = 0):
    try:
        detail = listing.ad_detail(workspace(request), jd_id, today=request.app.state.today())
    except NoSuchAd:
        return render(
            request,
            "error.html",
            {"heading": "No such job", "detail": f"There is no job description with id {jd_id}."},
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
            "pipeline_saved": bool(saved),
        },
    )


@router.post("/ads/{jd_id:int}/pipeline")
async def pipeline_save(request: Request, jd_id: int):
    """Record where an application stands, and what was sent, as `apply` does. Free.

    The sent files are checked first, the status second, and copied last, so
    a refusal from either leaves nothing half-recorded.
    """
    form = await checked_form(request)
    ws = workspace(request)
    today = request.app.state.today()
    try:
        prepared = await _sent_files(form, ws, jd_id, today)
    except NoSuchAd:
        return render(request, "error.html", {"heading": "No such job",
                      "detail": f"There is no job description with id {jd_id}."}, status_code=404)
    except SentFileUnusable as exc:
        return _back_to_ad(request, jd_id, f"Not saved: {exc.path}: {exc.reason}.")
    except NoGeneratedCopy:
        return _back_to_ad(request, jd_id, "Not saved: no generated copy is kept for this job, "
                           "so there is nothing to record as sent unedited. Choose the files you sent.")
    try:
        pipeline.update_from_form(
            ws,
            jd_id,
            status=str(form.get("status") or ""),
            applied_on=str(form.get("applied_on") or ""),
            channel=str(form.get("channel") or ""),
            channel_detail=str(form.get("channel_detail") or ""),
            worth=str(form.get("worth") or ""),
            why=str(form.get("why") or ""),
            note=str(form.get("note") or ""),
            today=today,
            confirm_blockers=form.get("confirm_blockers") == "1",
            sent_files=prepared is not None,
        )
    except NoSuchAd:
        return render(request, "error.html", {"heading": "No such job",
                      "detail": f"There is no job description with id {jd_id}."}, status_code=404)
    except pipeline.OpenBlockers as exc:
        return _back_to_ad(request, jd_id, "Not saved: documents marked NOT-READY are in the "
                           "folder. Tick the box under Pipeline to record Applied anyway.",
                           extra={"pipeline_confirm": exc.files})
    except ValueError as exc:
        return _back_to_ad(request, jd_id, f"Not saved: {exc}")
    if prepared is not None:
        sent.commit(ws, prepared, sent_on=sent.sent_on_for(ws, jd_id, today),
                    today=today, now=datetime.now())
    return RedirectResponse(f"/ads/{jd_id}?saved=1#pipeline", status_code=303)


@router.post("/ads/{jd_id:int}/status")
async def status_save(request: Request, jd_id: int):
    """The Jobs page's status dropdown: the status alone, through the pipeline form's guards. Free.

    Answers with the cell, for HTMX to swap in; a refusal is shown in the row.
    """
    form = await checked_form(request)
    ws = workspace(request)
    problem = link = None
    try:
        pipeline.update_from_form(ws, jd_id, status=str(form.get("status") or ""),
                                  today=request.app.state.today())
    except NoSuchAd:
        return render(request, "error.html", {"heading": "No such job",
                      "detail": f"There is no job description with id {jd_id}."}, status_code=404)
    except pipeline.OpenBlockers:
        problem = "Not saved: documents marked NOT-READY are in the folder."
        link = f"/ads/{jd_id}#pipeline"
    except ValueError as exc:
        problem = f"Not saved: {exc}"
    row = {"jd_id": jd_id, "status": pipeline.current_status(ws, jd_id)}
    return render(request, "_status_cell.html", {"r": row, "saved": problem is None,
                                                 "problem": problem, "problem_link": link})


async def _sent_files(form, ws, jd_id: int, today):
    """The form's sent documents, checked and held, or None if it named none."""
    files = {}
    for key in ("resume", "letter"):
        upload = form.get(f"sent_{key}")
        if upload is not None and getattr(upload, "filename", ""):
            files[key] = (upload.filename, await upload.read(sent.MAX_UPLOAD_BYTES + 1))
    as_generated = form.get("sent_as_generated") == "1"
    if not files and not as_generated:
        return None
    if files and as_generated:
        raise SentFileUnusable("Sent unedited", "untick it, or choose no files")
    return sent.prepare_uploads(ws, jd_id, as_generated=as_generated, today=today, **files)


@router.post("/ads/{jd_id:int}/context")
async def context_save(request: Request, jd_id: int):
    """What Alan knows that the ad does not say. Replaces it; empty clears. Free."""
    form = await checked_form(request)
    try:
        revise.set_context(workspace(request), jd_id, str(form.get("context") or ""), datetime.now())
    except NoSuchAd:
        return render(request, "error.html", {"heading": "No such job",
                      "detail": f"There is no job description with id {jd_id}."}, status_code=404)
    return RedirectResponse(f"/ads/{jd_id}#context", status_code=303)


# --------------------------------------------------------------------------- #
# Revise: confirm (free) → start (spends) → the ad page shows the run
# --------------------------------------------------------------------------- #


def _revise_choice(form, config) -> dict:
    kind = DocumentKind.cover_letter if form.get("kind") == "cover_letter" else DocumentKind.resume
    return {
        "kind": kind,
        "note": str(form.get("note") or "").strip(),
        "replace_edits": form.get("replace_edits") == "1",
        "check_claims": form.get("check_claims") == "1" if form.get("checks_shown") else config.check_claims,
    }


def _revise_confirm(request: Request, jd_id: int, choice: dict, problem: str | None = None):
    ws = workspace(request)
    config = config_of(request)
    today = request.app.state.today()
    try:
        plan = revise.plan(ws, jd_id, choice["kind"], today)
    except NoSuchAd:
        return render(request, "error.html", {"heading": "No such job",
                      "detail": f"There is no job description with id {jd_id}."}, status_code=404)
    except NoGeneratedCopy:
        return _back_to_ad(request, jd_id, "Nothing to revise: no generated copy is kept for that "
                           "document. Revise works on documents generated from 2026-10-21 on.")
    if not choice["note"]:
        return _back_to_ad(request, jd_id, "Say what to change: a revision needs a note.")
    is_letter = choice["kind"] is DocumentKind.cover_letter
    estimate = costs.estimate(
        ws, config, "generate", resume=not is_letter, cover=is_letter, answers=False,
        check_claims=choice["check_claims"] and is_letter, review=False, jd_id=jd_id,
    )
    return render(
        request,
        "revise_confirm.html",
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


@router.post("/ads/{jd_id:int}/revise/confirm")
async def revise_confirm(request: Request, jd_id: int):
    form = await checked_form(request)
    return _revise_confirm(request, jd_id, _revise_choice(form, config_of(request)))


@router.post("/ads/{jd_id:int}/revise")
async def revise_start(request: Request, jd_id: int):
    form = await checked_form(request)
    config = config_of(request)
    choice = _revise_choice(form, config)
    if form.get("confirmed") != "1":
        return _revise_confirm(request, jd_id, choice, "Nothing was started: confirm the cost first.")
    ws = workspace(request)
    today = request.app.state.today()
    try:
        plan = revise.plan(ws, jd_id, choice["kind"], today)
    except (NoSuchAd, NoGeneratedCopy):
        return _revise_confirm(request, jd_id, choice)
    # Checked again by the service; here so the page can say so before a run exists.
    if not choice["note"]:
        return _revise_confirm(request, jd_id, choice, "Say what to change: a revision needs a note.")
    if plan.edited and not choice["replace_edits"]:
        return _revise_confirm(request, jd_id, choice,
                               "The file was edited by hand. Tick the box to keep that version and revise anyway.")
    missing = readiness.missing(ws, config, "generate")
    if missing:
        return _revise_confirm(request, jd_id, choice, "Nothing was started: " + " ".join(missing))
    label = "resume" if choice["kind"] is DocumentKind.resume else "cover letter"
    ctx = RunContext(command="revise", jd_id=jd_id, source="ui")
    try:
        request.app.state.runner.start(
            ws, kind="generate", jd_id=jd_id, run_id=ctx.run_id,
            request={"title": f"{plan.jd.title} (revising the {label})", "revise": choice["kind"].value,
                     "note": choice["note"]},
            work=work.revise(
                ws, config, ctx, jd_id, kind=choice["kind"], note=choice["note"],
                replace_edits=choice["replace_edits"], check_claims=choice["check_claims"], today=today,
            ),
        )
    except RunInProgress:
        pass
    return RedirectResponse(f"/ads/{jd_id}", status_code=303)


@router.get("/ads/{jd_id:int}/diff")
def diff_page(request: Request, jd_id: int):
    """Each sent document against its generated copy, sentence by sentence. Free."""
    ws = workspace(request)
    try:
        detail = listing.ad_detail(ws, jd_id, today=request.app.state.today())
    except NoSuchAd:
        return render(request, "error.html", {"heading": "No such job",
                      "detail": f"There is no job description with id {jd_id}."}, status_code=404)
    return render(request, "diff.html", {"nav": "ads", "d": detail})


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


def _generate_choice(form, config) -> dict:
    questions = [
        line.strip() for line in str(form.get("questions") or "").splitlines() if line.strip()
    ]
    # The two paid checks are on unless unticked on the confirm page, which is
    # the only form that carries them; arriving from the ad page they take the
    # configured default.
    from_confirm = form.get("checks_shown") == "1"
    return {
        "resume": form.get("resume") == "1",
        "cover": form.get("cover") == "1",
        "questions": questions,
        "overrule": form.get("overrule") == "1",
        "supersede": form.get("supersede") == "1",
        "limit": _limit(form.get("limit")),
        "check_claims": form.get("check_claims") == "1" if from_confirm else config.check_claims,
        "review": form.get("review") == "1" if from_confirm else config.review,
    }


def _limit(raw) -> int | None:
    """An answer character limit from the form; anything unusable is no limit."""
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        return None
    return value if value >= 50 else None


def _generate_confirm(request: Request, jd_id: int, choice: dict, problem: str | None = None):
    """The confirmation page. Everything on it is free to compute."""
    ws = workspace(request)
    config = config_of(request)
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
        return render(request, "error.html", {"heading": "No such job",
                      "detail": f"There is no job description with id {jd_id}."}, status_code=404)
    estimate = costs.estimate(
        ws, config, "generate",
        resume=choice["resume"], cover=choice["cover"], answers=bool(choice["questions"]),
        check_claims=choice["check_claims"], review=choice["review"],
        jd_id=jd_id,
    )
    checks_cost = costs.estimate(
        ws, config, "generate", cover=True, check_claims=True, review=True
    )
    return render(
        request,
        "generate_confirm.html",
        {
            "nav": "ads",
            "plan": plan,
            "choice": choice,
            "estimate": costs.describe(estimate),
            "check_cost": costs.label_cost(checks_cost, "check_claims"),
            "review_cost": costs.label_cost(checks_cost, "review_documents"),
            "missing": readiness.missing(ws, config, "generate"),
            "problem": problem,
        },
        status_code=409 if problem else 200,
    )


def _back_to_ad(request: Request, jd_id: int, problem: str, extra: dict | None = None):
    try:
        detail = listing.ad_detail(workspace(request), jd_id, today=request.app.state.today())
    except NoSuchAd:
        return render(request, "error.html", {"heading": "No such job",
                      "detail": f"There is no job description with id {jd_id}."}, status_code=404)
    return render(request, "detail.html", {"nav": "ads", "d": detail, "problem": problem,
                                           "run": None, **(extra or {})}, status_code=409)


@router.post("/ads/{jd_id}/generate/confirm")
async def generate_confirm(request: Request, jd_id: int):
    form = await checked_form(request)
    return _generate_confirm(request, jd_id, _generate_choice(form, config_of(request)))


@router.post("/ads/{jd_id}/generate")
async def generate_start(request: Request, jd_id: int):
    form = await checked_form(request)
    choice = _generate_choice(form, config_of(request))
    if form.get("confirmed") != "1":
        return _generate_confirm(request, jd_id, choice, "Nothing was started: confirm the cost first.")

    ws = workspace(request)
    config = config_of(request)
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
                "check_claims": choice["check_claims"],
                "review": choice["review"],
            },
            work=work.generate(
                ws, config, ctx, jd_id,
                resume=choice["resume"], cover=choice["cover"], questions=choice["questions"],
                overrule=choice["overrule"], supersede=choice["supersede"], today=today,
                check_claims=choice["check_claims"], review=choice["review"],
                limit=choice["limit"],
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
    newest_path = ads.newest_new_ad(ws)
    newest = newest_path.name if newest_path else None
    return render(request, "add.html", {"nav": "add", "newest": newest, "jd_dir": ws.jd_dir,
                                        "newest_source": ads.guess_source(newest or ""),
                                        "any_saved": bool(ads.ads_in(ws.jd_dir)),
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
    config = config_of(request)
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
    existing = _already_stored(ws, ad)
    if existing:
        return add_form(request, problem=existing)
    return _add_confirm(request, ad, name, str(form.get("source") or ""))


def _already_stored(ws, ad) -> str | None:
    from jobagent.core import store as core_store

    with core_store.open_store(ws.db_path) as conn:
        found = ads.already_stored(conn, ad)
    if not found:
        return None
    return (f"This ad is already in JobAgent as JD {found[0]} ({found[1]}). Nothing was started. "
            f"If the ad has changed since, amend that JD instead: jobagent jd amend {found[0]} --file ….")


@router.post("/ads/new")
async def add_start(request: Request):
    form = await checked_form(request)
    ws = workspace(request)
    config = config_of(request)
    source = str(form.get("source") or "").strip() or None
    try:
        ad, name = await _add_input(request, form, ws)
    except (BadUpload, AdNotFound, UnreadableAd) as refusal:
        return add_form(request, problem=str(refusal))
    if form.get("confirmed") != "1":
        return _add_confirm(request, ad, name, source or "", "Nothing was started: confirm the cost first.")
    if ad.truncated:
        return _add_confirm(request, ad, name, source or "", "This capture is incomplete; nothing was started.")
    existing = _already_stored(ws, ad)
    if existing:
        return add_form(request, problem=existing)
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
    config = config_of(request)
    try:
        jd, seen_before = scoring.load(ws, jd_id)
    except NoSuchAd:
        return render(request, "error.html", {"heading": "No such job",
                      "detail": f"There is no job description with id {jd_id}."}, status_code=404)
    return render(
        request,
        "score_confirm.html",
        {
            "nav": "ads",
            "jd": jd,
            "history": seen_before,
            "force": force,
            "estimate": costs.describe(costs.estimate(ws, config, "score", jd_id=jd_id)),
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
    config = config_of(request)
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
        return PlainTextResponse("No such job.", 404)
    back = str(form.get("next") or f"/ads/{jd_id}")
    if not back.startswith("/") or back.startswith("//"):
        back = f"/ads/{jd_id}"
    return RedirectResponse(back, status_code=303)


# --------------------------------------------------------------------------- #
# Batch review (spec 002, US1): parse new files, score several, skip several.
# Generate stays per ad, from each row's ad page.
# --------------------------------------------------------------------------- #


def _batch_page(
    request: Request, problem: str | None = None, confirm: dict | None = None,
    screen_confirm: dict | None = None,
):
    ws = workspace(request)
    config = config_of(request)
    today = request.app.state.today()
    new = batches.new_files(ws)
    batch_id = batches.latest(ws)
    parse_run = next(
        (r for r in runs.running(ws) if str(r.request.get("input_key", "")).startswith("batch:")),
        None,
    )
    estimate = costs.estimate(ws, config, "add_ad")
    return render(
        request,
        "batch.html",
        {
            "nav": "batch",
            "new": [p.name for p in new],
            "parse_cost": _times(estimate, len(new)) if new else None,
            "waiting": batches.waiting(ws, batch_id) if batch_id else [],
            "batch_id": batch_id,
            "rows": batches.rows(ws, batch_id, today) if batch_id else [],
            "describe": batches.describe,
            "run": parse_run,
            "problem": problem,
            "confirm": confirm,
            "screen_confirm": screen_confirm,
            "missing_parse": readiness.missing(ws, config, "add_ad"),
        },
        status_code=409 if problem else 200,
    )


def _times(estimate, count: int) -> str:
    if estimate.total_usd is None:
        return costs.describe(estimate)
    return f"About ${estimate.total_usd * count:.2f} for {count} ({costs.describe(estimate)})"


def _selected(form) -> list[int]:
    ids = []
    for value in form.getlist("jd"):
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


@router.get("/batch")
def batch_page(request: Request):
    return _batch_page(request)


@router.post("/batch/parse")
async def batch_parse(request: Request):
    form = await checked_form(request)
    if form.get("confirmed") != "1":
        return _batch_page(request, "Nothing was started: confirm the cost first.")
    ws = workspace(request)
    config = config_of(request)
    missing = readiness.missing(ws, config, "add_ad")
    if missing:
        return _batch_page(request, "Nothing was started: " + " ".join(missing))
    batch_id = batches.latest(ws)
    if batch_id is None or not batches.waiting(ws, batch_id):
        batch_id = batches.start(ws)
    if batch_id is None:
        return _batch_page(request, "Nothing new to parse.")
    ctx = RunContext(command="jd add", source="ui")
    try:
        request.app.state.runner.start(
            ws, kind="add_ad", jd_id=None, run_id=ctx.run_id,
            request={"title": f"batch {batch_id}", "input_key": f"batch:{batch_id}"},
            work=work.parse_batch(ws, config, batch_id),
        )
    except RunInProgress:
        pass
    return RedirectResponse("/batch", status_code=303)


@router.post("/batch/score/confirm")
async def batch_score_confirm(request: Request):
    form = await checked_form(request)
    ids = _selected(form)
    if not ids:
        return _batch_page(request, "Select at least one ad to score.")
    ws = workspace(request)
    config = config_of(request)
    plan = _score_plan(ws, ids, request.app.state.today())
    estimate = costs.estimate(ws, config, "score")
    return _batch_page(request, confirm={
        "ids": [i for i, _ in plan["go"]],
        "go": plan["go"],
        "refused": plan["refused"],
        "cost": _times(estimate, len(plan["go"])) if plan["go"] else None,
        "missing": readiness.missing(ws, config, "score"),
    })


@router.post("/batch/score")
async def batch_score(request: Request):
    form = await checked_form(request)
    ids = _selected(form)
    if form.get("confirmed") != "1":
        return _batch_page(request, "Nothing was started: confirm the cost first.")
    ws = workspace(request)
    config = config_of(request)
    missing = readiness.missing(ws, config, "score")
    if missing:
        return _batch_page(request, "Nothing was started: " + " ".join(missing))
    for jd_id, title in _score_plan(ws, ids, request.app.state.today())["go"]:
        ctx = RunContext(command="score", jd_id=jd_id, source="ui")
        try:
            request.app.state.runner.start(
                ws, kind="score", jd_id=jd_id, run_id=ctx.run_id,
                request={"title": title, "force": False},
                work=work.score(ws, config, ctx, jd_id, force=False),
            )
        except RunInProgress:
            continue
    return RedirectResponse("/batch", status_code=303)


@router.post("/batch/screen/confirm")
async def batch_screen_confirm(request: Request):
    """The cost of a first-pass screen over the selected ads. Spends nothing."""
    form = await checked_form(request)
    ids = _selected(form)
    if not ids:
        return _batch_page(request, "Select at least one ad to screen.")
    ws = workspace(request)
    config = config_of(request)
    return _batch_page(request, screen_confirm={
        "ids": ids,
        "cost": _times(costs.estimate(ws, config, "screen"), len(ids)),
        "missing": readiness.missing(ws, config, "screen"),
    })


@router.post("/batch/screen")
async def batch_screen(request: Request):
    """Screen the selected ads, as `jobagent screen` does. A few seconds an ad.

    Run in the request rather than in the background: it is cheap and quick,
    and the answer is what the next click depends on.
    """
    form = await checked_form(request)
    ids = _selected(form)
    if form.get("confirmed") != "1":
        return _batch_page(request, "Nothing was started: confirm the cost first.")
    ws = workspace(request)
    config = config_of(request)
    missing = readiness.missing(ws, config, "screen")
    if missing:
        return _batch_page(request, "Nothing was started: " + " ".join(missing))
    try:
        results = screening.screen_ads(ws, config, ids, source="ui")
    except (ProfileMissing, ProfileInvalid, NoModel) as exc:
        return _batch_page(request, f"Not screened: {exc}")
    failed = [r for r in results if r.decision is None]
    if failed:
        return _batch_page(request, "Screened, except: " + "; ".join(
            f"JD {r.jd_id}: {r.reason}" for r in failed))
    return RedirectResponse("/batch", status_code=303)


@router.post("/batch/skip")
async def batch_skip(request: Request):
    form = await checked_form(request)
    ws = workspace(request)
    day = request.app.state.today()
    for jd_id in _selected(form):
        try:
            pipeline.outcome(ws, jd_id, ApplicationStatus.not_applied,
                             note=f"Not applied: decided at batch review {day:%Y-%m-%d}.")
        except NoSuchAd:
            continue
    return RedirectResponse("/batch", status_code=303)


def _score_plan(ws, ids: list[int], today) -> dict:
    """Which selected ads would score, and which the free checks already refuse."""
    go, refused = [], []
    for jd_id in ids:
        try:
            jd, _ = scoring.load(ws, jd_id)
        except NoSuchAd:
            continue
        state = reapply.check(ws, jd_id, today)
        if state.kind in ("same", "possibly_same"):
            refused.append((jd_id, jd.title, "a job you applied for recently: answer on its page"))
        elif jd.thin:
            refused.append((jd_id, jd.title, "too little ad text: score it from its page with the box ticked"))
        else:
            go.append((jd_id, jd.title))
    return {"go": go, "refused": refused}


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #


@router.get("/settings")
def settings_page(request: Request, saved: int = 0):
    from jobagent.services import settings

    return render(request, "settings.html", {
        "nav": "settings",
        "s": settings.view(request.app.state.config),
        "saved": bool(saved),
    })


@router.post("/settings")
async def settings_save(request: Request):
    from jobagent.services import settings

    form = await checked_form(request)
    settings.save(request.app.state.config, settings.from_form(form))
    return RedirectResponse("/settings?saved=1", status_code=303)


# --------------------------------------------------------------------------- #
# Job alerts
# --------------------------------------------------------------------------- #


@router.get("/alerts")
def alerts_page(request: Request, show: str = "pending", fetched: str = "", error: str = ""):
    from datetime import timezone

    from jobagent.core.models import AlertDecision, AlertVerdict
    from jobagent.services import alerts

    ws, now = workspace(request), datetime.now(timezone.utc)
    alerts.match_saved_files(ws, now)
    if show == "skipped":
        rows, items = alerts.listings(ws, verdict=AlertVerdict.skip), []
    elif show == "decided":
        rows = [r for r in alerts.listings(ws) if r.decision is not None]
        # A history: the most recent decision first. Rows decided before
        # decided_at was recorded sort last.
        rows.sort(key=lambda r: r.decided_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        items = []
    else:
        show, rows, items = "pending", [], alerts.pending(ws, now)
    return render(request, "alerts.html", {
        "nav": "alerts", "show": show, "items": items, "rows": rows,
        "decisions": list(AlertDecision), "fetched": fetched, "error": error,
        "last_fetch": alerts.last_fetch(ws),
        "waiting": alerts.waiting_for_file(ws), "ready": alerts.ready_to_add(ws),
        "jd_dir": ws.jd_dir,
    })


# What each key does on the review page, and the decision it records.
REVIEW_KEYS = [
    ("i", "interested"), ("n", "not_relevant"), ("q", "not_qualified"),
    ("u", "not_interested"), ("a", "already_applied"), ("x", "expired"), ("l", "later"),
]


@router.get("/alerts/review")
def alerts_review(request: Request, flash: str = ""):
    """One suggested job at a time, decided with a key press."""
    from datetime import timezone

    from jobagent.services import alerts

    ws, now = workspace(request), datetime.now(timezone.utc)
    alerts.match_saved_files(ws, now)
    items = [i for i in alerts.pending(ws, now) if i.listing.decision is None]
    return render(request, "alerts_review.html", {
        "nav": "alerts", "item": items[0] if items else None, "left": len(items),
        "keys": REVIEW_KEYS, "flash": flash, "jd_dir": ws.jd_dir,
        "waiting": alerts.waiting_for_file(ws), "ready": alerts.ready_to_add(ws),
    })


@router.post("/alerts/fetch")
async def alerts_fetch(request: Request):
    from datetime import timezone
    from urllib.parse import quote

    from jobagent.services import alerts

    await checked_form(request)
    ws, config, now = workspace(request), config_of(request), datetime.now(timezone.utc)
    try:
        result = alerts.fetch(
            ws, address=config.gmail_address, app_password=config.gmail_app_password,
            since=alerts.default_since(ws, now.date()), now=now,
        )
    except alerts.NoMailbox:
        return RedirectResponse("/alerts?error=" + quote(
            "Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env, then restart the UI."), status_code=303)
    except (alerts.MailboxFailed, ProfileInvalid) as refusal:
        return RedirectResponse("/alerts?error=" + quote(refusal.detail), status_code=303)
    except (alerts.NoAlertRules, ProfileMissing):
        return RedirectResponse("/alerts?error=" + quote(
            "No `alerts:` section in assets.yaml, or no profile configured."), status_code=303)
    summary = (
        f"Read {result.emails} email(s): {result.listings} listing(s), {result.new} new, "
        f"{result.suggested} to look at."
        + (f" Could not read jobs from: {'; '.join(result.unread)}." if result.unread else "")
    )
    return RedirectResponse("/alerts?fetched=" + quote(summary), status_code=303)


@router.post("/alerts/{listing_id:int}/decide")
async def alerts_decide(request: Request, listing_id: int):
    from datetime import timezone

    from jobagent.core.models import AlertDecision
    from jobagent.services import alerts

    form = await checked_form(request)
    try:
        decision = AlertDecision(str(form.get("decision", "")))
    except ValueError:
        return PlainTextResponse("Unknown decision.", status_code=400)
    try:
        [row] = alerts.decide(workspace(request), [listing_id], decision,
                              note=str(form.get("note", "")), now=datetime.now(timezone.utc))
    except alerts.NoSuchListing:
        return PlainTextResponse(f"No alert listing {listing_id}.", status_code=404)
    if form.get("show") == "review":
        from urllib.parse import quote

        if decision is AlertDecision.interested:
            flash = f"Interested in {row.title}: print it to PDF (Cmd+P, Save) into the saved-ads folder. It is matched to the job by itself."
        else:
            flash = f"{row.title}: {decision.value.replace('_', ' ')}."
        return RedirectResponse("/alerts/review?flash=" + quote(flash), status_code=303)
    return RedirectResponse(f"/alerts?show={form.get('show') or 'pending'}", status_code=303)
