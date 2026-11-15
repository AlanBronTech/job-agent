"""The master-resume registry: which hand-written resumes exist, and what each is for.

Alan keeps a small set of approved master resumes and sends one per ad
instead of composing a new resume every time (REVIEW-2026-11-14). They live in
`<profile>/resumes/`, gitignored with the rest of the profile, and
`masters.yaml` in that folder lists them. This module only loads and checks
that list. Choosing a master for an ad is a separate step.

The registry is optional. Without it there are no masters and `generate`
works as before; a custom resume stays available either way.

Pure logic: raises `ProfileError` with a message meant for a human, so the CLI
and the web UI report a bad registry the same way they report a bad profile.
"""

from __future__ import annotations

import re
from pathlib import Path

from jobagent.core.models import (
    JobDescription,
    MasterChoice,
    MasterResume,
    MastersFile,
    RoleClassification,
    RoleKind,
    Seniority,
    WorkType,
)
from jobagent.core.profile import ProfileError, _load_yaml, _parse_model

RESUMES_DIR = "resumes"
MASTERS_FILE = "masters.yaml"


def load_masters(profile_dir: str | Path) -> list[MasterResume]:
    """The masters listed in `<profile_dir>/resumes/masters.yaml`, in file order.

    Returns an empty list when there is no registry. Raises `ProfileError`
    when there is one and it is wrong: bad YAML, an unknown key or value, a
    duplicate id, not exactly one default, or a document that is not there.
    """
    folder = Path(profile_dir) / RESUMES_DIR
    path = folder / MASTERS_FILE
    if not path.exists():
        return []

    parsed: MastersFile = _parse_model(MastersFile, _load_yaml(path), MASTERS_FILE)
    entries = parsed.masters
    if not entries:
        raise ProfileError(f"{MASTERS_FILE}: lists no masters. Add one, or delete the file.")

    errors: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.id in seen:
            errors.append(f"id {entry.id!r} is used twice")
        seen.add(entry.id)
        if not entry.docx.lower().endswith(".docx"):
            errors.append(f"{entry.id}: docx must name a .docx file, got {entry.docx!r}")
        if entry.pdf is not None and not entry.pdf.lower().endswith(".pdf"):
            errors.append(f"{entry.id}: pdf must name a .pdf file, got {entry.pdf!r}")
        for name in (entry.docx, entry.pdf):
            if name is not None and not (folder / name).is_file():
                errors.append(f"{entry.id}: {name} is not in {folder}")

    defaults = [e.id for e in entries if e.default]
    if len(defaults) != 1:
        found = ", ".join(defaults) if defaults else "none"
        errors.append(f"exactly one master must be the default (found: {found})")

    if errors:
        raise ProfileError(
            f"{MASTERS_FILE}: {len(errors)} problem(s):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    return [
        MasterResume(
            **entry.model_dump(exclude={"docx", "pdf"}),
            docx=folder / entry.docx,
            pdf=folder / entry.pdf if entry.pdf else None,
        )
        for entry in entries
    ]


# --------------------------------------------------------------------------- #
# Choosing a master for an ad
# --------------------------------------------------------------------------- #

# What the title says the job is, in whole words ("Engineering" is not
# "engineer"). Manager beats everything: "Engineering Manager / Squad Tech
# Lead" is a manager's job. A hands-on word beats "lead" unless the title names
# a team or tech lead: "Lead AI Engineer" is a senior engineer, "Engineering
# Team Lead" is not.
_MANAGER = re.compile(r"\b(manager|head|director|chief|cto|cio|vp|vice president)\b")
_TEAM_LEAD = re.compile(r"\b(team|tech|technical|squad)\s+lead(er)?\b")
_LEAD = re.compile(r"\b(lead|leader)\b")
_HANDS_ON = re.compile(r"\b(engineer|developer|programmer|architect|scientist)\b")
_DELIVERY = re.compile(r"\b(project|program|programme|delivery|scrum master)\b")
_AI = re.compile(r"\b(ai|artificial intelligence|genai)\b")
_ADOPTION = re.compile(r"\b(adoption|enablement)\b")

_CONTRACT_TYPES = {WorkType.contract, WorkType.fixed_term}


def title_shape(jd: JobDescription) -> str:
    """'manager', 'lead', 'hands_on' or 'other', from the title and seniority."""
    title = jd.title.casefold()
    if _MANAGER.search(title):
        return "manager"
    if _TEAM_LEAD.search(title):
        return "lead"
    if jd.seniority in (Seniority.manager, Seniority.director):
        return "manager"
    if _HANDS_ON.search(title):
        return "hands_on"
    if _LEAD.search(title):
        return "lead"
    return "other"


def _kind(jd: JobDescription, classification: RoleClassification | None) -> RoleKind | None:
    """The stored primary kind; for an ad never classified, AI adoption read
    off the title ("AI & Digital Tools Adoption Lead"), else nothing."""
    if classification is not None:
        return classification.primary
    title = jd.title.casefold()
    if _AI.search(title) and _ADOPTION.search(title):
        return RoleKind.ai_enablement
    return None


def select_master(
    jd: JobDescription,
    classification: RoleClassification | None,
    masters: list[MasterResume],
) -> MasterChoice | None:
    """The master to send for this ad, with the reason. None without masters.

    Computed in Python from the title, the work type and the stored role kind:
    no model call. Advice only: Alan can override it or ask for a custom
    resume. The rules, in order (Alan, 2026-11-16):

    1. A role kind with its own master takes it, unless the title is plainly
       hands-on: an AI-adoption role takes the AI master.
    2. A hands-on engineering title takes the contract master on a contract.
       A permanent one is not a target; one whose terms the ad does not state
       is not a target until they are known.
    3. A delivery or project role takes the default: it has no master.
    4. A management role takes the default, contract or not.
    5. Any other contract takes the contract master.
    6. Everything else takes the default, including Team Lead roles until
       Alan decides which master they get.
    """
    if not masters:
        return None
    default = next(m for m in masters if m.default)
    kind = _kind(jd, classification)
    by_kind = next((m for m in masters if kind is not None and kind in m.role_kinds), None)
    by_terms = next((m for m in masters if jd.work_type in m.work_types), None)
    shape = title_shape(jd)
    delivery_title = bool(_DELIVERY.search(jd.title.casefold()))
    delivery = delivery_title or (kind is RoleKind.delivery_focused and shape != "lead")

    def chose(master: MasterResume, why: str) -> MasterChoice:
        return MasterChoice(master=master, reason=f"{master.label}: {why}")

    def no(why: str) -> MasterChoice:
        return MasterChoice(not_a_target=True, reason=why)

    if by_kind is not None and shape != "hands_on":
        return chose(by_kind, f"the role is {kind.value.replace('_', ' ')}.")

    if shape == "hands_on":
        if by_terms is not None:
            return chose(by_terms, f"a hands-on role, {jd.work_type.value.replace('_', '-')}.")
        if jd.work_type is WorkType.permanent:
            return no("A permanent hands-on engineering role: not a target "
                      "(Alan applies for those on contract only).")
        if jd.work_type in _CONTRACT_TYPES:
            return no(f"A hands-on {jd.work_type.value.replace('_', '-')} role, "
                      "and no master covers that.")
        return no("A hands-on engineering role whose terms the ad does not "
                  "state: a target only if it is a contract, so ask first.")

    if delivery:
        return chose(default, "a delivery or project role, which has no master of its own.")
    if shape == "manager":
        if jd.work_type in _CONTRACT_TYPES:
            return chose(default, "a management role on a contract; the contract "
                         "master is for hands-on contracts.")
        return chose(default, "a manager role.")
    if by_terms is not None:
        return chose(by_terms, f"a {jd.work_type.value.replace('_', '-')} role.")
    if shape == "lead":
        return chose(default, "a Team Lead role, not a contract. Which master Team "
                     "Lead roles get is still to be decided; the default meanwhile.")
    return chose(default, "the default.")


def describe_choice(choice: MasterChoice) -> str:
    """One line for a person: the choice, why, and the file to send."""
    if choice.not_a_target:
        return f"Not a target. {choice.reason}"
    if choice.master is None:
        return choice.reason
    send = choice.master.pdf or choice.master.docx
    return f"{choice.reason} Send {send.name}."
