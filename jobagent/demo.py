"""A demo workspace for showing the UI to someone else: `jobagent ui --demo`.

Everything here is invented (Constitution VI): the person is profile.example's
Sam Rivera, the employers are made up, and so are the assessments. Seeding
spends nothing — the one resume is built from profile.example with a scripted
selection, through the same builder and renderer as a real run, so what opens
on screen is the real format. Paid buttons stay live: pressing one calls the
configured model against the invented profile, and the confirm page says what
it costs first, as always.

The workspace lives in its own folder (default ~/job-agent-demo), never in the
real database, output folder or run log, so a demo cannot show or touch
anything of Alan's.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from jobagent.adapters import docs
from jobagent.adapters.docx_writer import CoverLetterContent, write_cover_letter, write_resume
from jobagent.adapters.llm import LLMClient, LLMResponse, Provider
from jobagent.core import store
from jobagent.core.generate import build_resume
from jobagent.core.models import (
    Application,
    ApplicationStatus,
    ChallengePoint,
    ConstraintCheck,
    ConstraintStatus,
    FitAssessment,
    JobDescription,
    MatchStatus,
    RequirementMatch,
    RoleClassification,
    RoleKind,
    SalaryRange,
    Verdict,
    WorkArrangement,
    WorkType,
)
from jobagent.core.profile import load_profile

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PROFILE = REPO_ROOT / "profile.example"
DEFAULT_DIR = Path.home() / "job-agent-demo"


def paths(base: Path) -> dict[str, Path]:
    return {
        "profile_dir": EXAMPLE_PROFILE,
        "db_path": base / "jobagent.db",
        "runs_log_path": base / "runs.jsonl",
        "jd_dir": base / "saved-ads",
        "output_dir": base / "documents",
    }


def ensure(base: Path = DEFAULT_DIR, *, today: date | None = None) -> bool:
    """Create and seed the demo workspace if it is not there. True if seeded now."""
    p = paths(base)
    if p["db_path"].exists():
        return False
    base.mkdir(parents=True, exist_ok=True)
    p["jd_dir"].mkdir(exist_ok=True)
    p["output_dir"].mkdir(exist_ok=True)
    seed(p, today or date.today())
    return True


# --------------------------------------------------------------------------- #


def _ad(title, company, days_ago, today, *, must, resp=(), arrangement=WorkArrangement.hybrid,
        work_type=WorkType.permanent, salary=None, about="", url=None):
    text = (
        f"{title}, {company}. {about} "
        + " ".join(must) + " " + " ".join(resp)
        + " This is an invented advertisement for a demonstration."
    )
    return JobDescription(
        title=title,
        company=company,
        location="Sydney NSW",
        work_type=work_type,
        work_arrangement=arrangement,
        salary_range=SalaryRange(raw=salary) if salary else None,
        must_haves=list(must),
        responsibilities=list(resp),
        source="demo",
        source_url=url,
        raw_text=(text + " ") * 4,
        ingested_at=datetime.combine(today - timedelta(days=days_ago), datetime.min.time(),
                                     tzinfo=timezone.utc),
    )


def _fit(jd_id, verdict, overall, screen, today, *, rationale, reqs=(), constraints=(),
         challenges=(), questions=()):
    return FitAssessment(
        jd_id=jd_id,
        overall_score=overall,
        recruiter_screen_score=screen,
        verdict=verdict,
        rationale=rationale,
        target_role_match=verdict is not Verdict.skip,
        target_role_note="Engineering leadership of a software team." if verdict is not Verdict.skip
        else "Not the kind of role the profile targets.",
        requirements=[RequirementMatch(requirement=r, status=s, evidence_ref=ref, note=n)
                      for r, s, ref, n in reqs],
        constraints=[ConstraintCheck(name=n, status=s, detail=d) for n, s, d in constraints],
        challenge_points=[ChallengePoint(point=a, response=b) for a, b in challenges],
        questions_to_ask=list(questions),
        model_used="demo (invented assessment)",
        scored_at=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
    )


OK, UNKNOWN, BREACH = ConstraintStatus.ok, ConstraintStatus.unknown, ConstraintStatus.breach


def seed(p: dict[str, Path], today: date) -> None:
    profile = load_profile(p["profile_dir"])
    with store.open_store(p["db_path"]) as conn:
        # 1. The strong match, with documents generated.
        northwind = _ad(
            "Engineering Manager", "Northwind Freight", 3, today,
            about="We build route planning for regional freight carriers.",
            must=["Coaching and growing engineers through regular 1:1s",
                  "Hiring and building a healthy team culture",
                  "Partnering with product on delivery",
                  "Freight or logistics domain knowledge"],
            resp=["Lead a team of eight engineers"],
            salary="$170,000 - $190,000 + super",
            url="https://jobs.example.invalid/northwind-em",
        )
        n_id = store.add_jd(conn, northwind)
        n_fit = _fit(
            n_id, Verdict.apply, 78, 72, today,
            rationale="A people-first Engineering Manager role: coaching, hiring and team "
                      "health lead the ad, which is where the profile is strongest. The only "
                      "real gap is the freight domain.",
            reqs=[("Coaching and growing engineers through regular 1:1s", MatchStatus.met,
                   "recent_manager.0", "Ran performance and career development for 15."),
                  ("Hiring and building a healthy team culture", MatchStatus.met,
                   "startup_em.0", "Recruited, trained and led a team of 6."),
                  ("Partnering with product on delivery", MatchStatus.partial,
                   "consultancy_lead", "Owned cross-team dependencies and the client."),
                  ("Freight or logistics domain knowledge", MatchStatus.gap, None,
                   "No logistics in the profile.")],
            constraints=[("salary", OK, "$170,000 – $190,000 + super clears the floor."),
                         ("work type", OK, "Permanent."),
                         ("location", UNKNOWN, "Hybrid in Sydney; office days not stated.")],
            challenges=[("No freight domain.", "Name it as the gap; regulated payments and "
                         "superannuation work shows domain ramp-up.")],
            questions=["How many office days a week?"],
        )
        store.add_assessment(conn, n_fit)
        store.set_role_kind(conn, n_id, RoleClassification(
            primary=RoleKind.people_focused,
            reason="The must-haves lead with coaching, 1:1s and hiring."))

        # 2. Worth a look, with caveats.
        woodgrove = _ad(
            "Engineering Manager, Payments", "Woodgrove Bank", 5, today,
            must=["Leading engineers in a regulated environment",
                  "Payments platform experience", "Kubernetes in production"],
            resp=["Own delivery for the payments squad"],
        )
        w_id = store.add_jd(conn, woodgrove)
        store.add_assessment(conn, _fit(
            w_id, Verdict.apply_with_caveats, 61, 55, today,
            rationale="Regulated payments leadership fits; Kubernetes is a stated must-have "
                      "the profile does not evidence, and no salary band is given.",
            reqs=[("Leading engineers in a regulated environment", MatchStatus.met,
                   "payments_lead", "Led squads on a transaction-critical platform."),
                  ("Kubernetes in production", MatchStatus.gap, None, "Not in the profile.")],
            constraints=[("salary", UNKNOWN, "No band stated; the floor is $160,000."),
                         ("work type", OK, "Permanent.")],
            questions=["What is the band?", "How central is Kubernetes to the first year?"],
        ))
        store.set_role_kind(conn, w_id, RoleClassification(
            primary=RoleKind.delivery_focused, reason="The ad leads with squad delivery."))

        # 3. Already applied: the pipeline.
        contoso = _ad("Head of Engineering", "Contoso Health", 21, today,
                      must=["Building engineering teams from scratch", "Healthcare compliance"])
        c_id = store.add_jd(conn, contoso)
        store.add_assessment(conn, _fit(
            c_id, Verdict.apply_with_caveats, 64, 60, today,
            rationale="Team-building record fits; healthcare compliance is a gap.",
            constraints=[("salary", UNKNOWN, "No band stated.")],
        ))
        store.save_application(conn, Application(
            jd_id=c_id, status=ApplicationStatus.recruiter_call,
            applied_on=today - timedelta(days=18), channel="careers site",
            notes="Recruiter call booked.",
            updated_at=datetime.now(timezone.utc)))

        # 4–6. Skips, each for a different reason.
        litware = _ad("Senior Frontend Lead", "Litware", 2, today,
                      must=["Deep React and accessibility specialisation", "Hands-on IC work"],
                      salary="$130,000 - $145,000")
        l_id = store.add_jd(conn, litware)
        store.add_assessment(conn, _fit(
            l_id, Verdict.skip, 31, 44, today,
            rationale="A frontend specialist IC role with a band below the floor. The salary "
                      "breach decides it whatever the fit.",
            constraints=[("salary", BREACH, "Top of band $145,000 is below the $160,000 floor.")],
        ))
        tailspin = _ad("Engineering Manager", "Tailspin Toys", 4, today,
                       must=["Five days a week in the office", "Game engine experience"],
                       arrangement=WorkArrangement.onsite)
        t_id = store.add_jd(conn, tailspin)
        store.add_assessment(conn, _fit(
            t_id, Verdict.skip, 27, 35, today,
            rationale="Game-engine depth is the first must-have and is absent from the profile.",
            constraints=[("location", UNKNOWN, "On-site five days; commute unknown.")],
        ))
        fabrikam = _ad("Senior Engineering Manager", "Fabrikam Energy", 6, today,
                       must=["Managing other Engineering Managers", "Terraform and Kubernetes"])
        f_id = store.add_jd(conn, fabrikam)
        store.add_assessment(conn, _fit(
            f_id, Verdict.skip, 33, 30, today,
            rationale="A manager-of-managers role; the profile has led engineers, not managers.",
        ))
        store.save_application(conn, Application(
            jd_id=f_id, status=ApplicationStatus.not_applied,
            notes="Not applied: decided at batch review.",
            updated_at=datetime.now(timezone.utc)))

        # 7. Saved but not scored yet.
        store.add_jd(conn, _ad("Delivery Manager", "Adventure Works", 1, today,
                               must=["Agile delivery across several teams"]))

    _documents(p, profile, northwind, n_fit, today)
    (p["jd_dir"] / "Engineering Lead - Proseware (saved page).txt").write_text(
        "Engineering Lead, Proseware. An invented advertisement saved for the demo. "
        "Lead a team of six building scheduling software. Coaching, hiring and delivery. "
        * 6,
        encoding="utf-8",
    )


class _Scripted(LLMClient):
    """Answers the resume selection with fixed references. No network."""

    provider = Provider.anthropic

    def __init__(self, payload):
        super().__init__(model="demo")
        self.payload = payload

    def _complete(self, *, system, prompt, max_tokens):  # pragma: no cover
        raise NotImplementedError

    def complete_json(self, *, prompt, label=None, **kwargs):
        return self.payload, LLMResponse(text="{}", provider=self.provider, model="demo",
                                         input_tokens=0, output_tokens=0)


def _documents(p, profile, jd, fit, today) -> None:
    roles = profile.roles
    selection = {
        "tagline": "Engineering Manager  ·  Team Builder  ·  Delivery",
        "profile_paragraphs": [
            "Engineering manager who builds the team first: led a 15-person team across "
            "three product lines, recruited and onboarded 9 of them, and ran their "
            "performance and career development.",
            "Earlier, recruited and led a distributed team of 6 that delivered a full "
            "platform build in 8 months on budget.",
        ],
        "profile_refs": [["recent_manager.0"], ["startup_em.0"]],
        "highlights": [
            {"label": "Team building", "text": "Recruited and onboarded 9 people into a "
             "15-person team and ran their career development.", "source_ref": "recent_manager.0"},
            {"label": "Startup delivery", "text": "Recruited, trained and led a team of 6; "
             "full platform build in 8 months on budget.", "source_ref": "startup_em.0"},
            {"label": "Ways of working", "text": "Moved a team from ad-hoc Kanban to Scrum with "
             "review standards and CI/CD.", "source_ref": "recent_manager.2"},
        ],
        "skill_categories": list(roles.skills),
        "roles": [{"role_id": r.id, "bullet_refs": [f"{r.id}.{i}" for i in range(min(2, len(r.bullets)))]}
                  for r in roles.roles],
        "earlier_career_ids": [e.id for e in roles.earlier_career],
    }
    built = build_resume(jd, profile, fit, client=_Scripted(selection), today=today,
                         kind=RoleClassification(primary=RoleKind.people_focused, reason="demo"))
    folder = docs.application_folder(p["output_dir"], jd, when=today)
    write_resume(built.content, folder / docs.document_name("Resume", jd, when=today))
    person = roles.person
    write_cover_letter(
        CoverLetterContent(
            name=person.name,
            contact="   ·   ".join(x for x in (person.location, person.email) if x),
            date=f"{today:%-d %B %Y}",
            recipient=[jd.company],
            paragraphs=[
                "Coaching and growing a team of eight is the work I do best, and route "
                "planning for regional freight carriers is a problem I want to work on.",
                "I led a 15-person team across three product lines, recruited and onboarded "
                "9 of them, and ran their performance and career development.",
                "Before that I recruited, trained and led a distributed team of 6 that "
                "delivered a full platform build in 8 months on budget.",
                "The gap I will not paper over: I have not worked in freight or logistics.",
                "I would like to talk about the team you are building.",
            ],
        ),
        folder / docs.document_name("CoverLetter", jd, when=today),
    )
    (folder / "assessment.md").write_text(
        docs.assessment_markdown(fit, jd, built.issues, role_kind=None, coverage=built.coverage),
        encoding="utf-8",
    )
    (folder / "job-ad.md").write_text(docs.job_ad_markdown(jd), encoding="utf-8")
    (folder / "review.md").write_text(
        "# Review\n\n**Ready.** No blocking findings.\n\n## Suggestions\n\n"
        "- **cover letter**: Name the route-planning work earlier. (Invented review for the demo.)\n",
        encoding="utf-8",
    )
