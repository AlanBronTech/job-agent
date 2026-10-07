"""The worked example for spec 003, invented throughout (Constitution VI).

A people-focused Engineering Manager ad at "Northwind Freight", the documents
that were first generated for it — each fault the spec's Why section lists —
and a technical-lead ad and an ad with no company description for contrast.
Evidence ids refer to `profile.example/`.

    recent_manager.0   leadership, hiring: the people evidence that should lead
    recent_manager.3   linked to `underperformer`, excluded for people_focused
    startup_em.1       linked to `scope_disagreement`, the over-used story
"""

from __future__ import annotations

from datetime import datetime, timezone

from jobagent.adapters.llm import LLMClient, LLMResponse, Provider
from jobagent.core.models import (
    FitAssessment,
    JobDescription,
    MatchStatus,
    RequirementMatch,
    RoleClassification,
    RoleKind,
    Verdict,
    WorkArrangement,
    WorkType,
)

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)

NORTHWIND_ABOUT = "We build route planning for regional freight carriers."

NORTHWIND_TEXT = (
    "Engineering Manager, Northwind Freight. "
    f"{NORTHWIND_ABOUT} "
    "You will coach and grow a team of eight engineers, run regular 1:1s, "
    "lead with empathy, and address underperformance with care. "
    "You will hire, build a healthy team culture, and partner with product "
    "on delivery. Experience with distributed systems is a plus."
)


def northwind(jd_id: int = 1) -> JobDescription:
    return JobDescription(
        id=jd_id,
        title="Engineering Manager",
        company="Northwind Freight",
        location="Melbourne VIC",
        work_type=WorkType.permanent,
        work_arrangement=WorkArrangement.hybrid,
        must_haves=[
            "Coaching and growing engineers through regular 1:1s",
            "Hiring and building a healthy team culture",
            "Addressing underperformance with care",
            "Partnering with product on delivery",
        ],
        responsibilities=["Lead a team of eight engineers"],
        nice_to_haves=["Distributed systems"],
        raw_text=NORTHWIND_TEXT,
        ingested_at=T0,
    )


def contoso(jd_id: int = 2) -> JobDescription:
    """Technical lead: architecture first."""
    return JobDescription(
        id=jd_id,
        title="Principal Engineer",
        company="Contoso Rail",
        work_type=WorkType.permanent,
        work_arrangement=WorkArrangement.hybrid,
        must_haves=[
            "System design and architecture of transaction-critical platforms",
            "Leading incremental re-platforms without outages",
        ],
        responsibilities=["Own the target architecture"],
        raw_text="Principal Engineer at Contoso Rail. Own the target architecture.",
        ingested_at=T0,
    )


def fabrikam(jd_id: int = 3) -> JobDescription:
    """No company description at all."""
    return JobDescription(
        id=jd_id,
        title="Engineering Manager",
        company="Fabrikam Logistics",
        work_type=WorkType.permanent,
        work_arrangement=WorkArrangement.hybrid,
        must_haves=["Leading a team of engineers"],
        raw_text="Engineering Manager. Lead a team of engineers. Apply now.",
        ingested_at=T0,
    )


PEOPLE = RoleClassification(
    primary=RoleKind.people_focused,
    reason="The must-haves lead with coaching, 1:1s and empathy.",
)
TECHNICAL = RoleClassification(
    primary=RoleKind.technical_lead,
    reason="The must-haves lead with system design and re-platforming.",
)


def northwind_assessment(jd_id: int = 1) -> FitAssessment:
    """Four must-haves: three evidenced in profile.example, one gap."""
    return FitAssessment(
        jd_id=jd_id,
        overall_score=74,
        recruiter_screen_score=68,
        verdict=Verdict.apply,
        rationale="Invented rationale: a people-leadership role.",
        target_role_match=True,
        target_role_note="Engineering Manager.",
        requirements=[
            RequirementMatch(
                requirement="Coaching and growing engineers through regular 1:1s",
                status=MatchStatus.met,
                evidence_ref="recent_manager.0",
                note="Ran performance and career development for 15.",
            ),
            RequirementMatch(
                requirement="Hiring and building a healthy team culture",
                status=MatchStatus.met,
                evidence_ref="startup_em.0",
                note="Recruited and trained a team of 6.",
            ),
            RequirementMatch(
                requirement="Partnering with product on delivery",
                status=MatchStatus.partial,
                evidence_ref="consultancy_lead",
                note="Owned cross-team dependencies.",
            ),
            RequirementMatch(
                requirement="Freight domain knowledge",
                status=MatchStatus.gap,
                note="No logistics in the profile.",
            ),
        ],
        scored_at=T0,
    )


# The documents first generated for Northwind, with every fault in the Why
# section: the resume opens on the managed exit and an AI highlight, one story
# (scope_disagreement) appears four times, the letter states an acquisition
# the profile does not hold and merges two people into one.
ORIGINAL_RESUME = """\
PROFILE
Engineering leader who resolved a sustained performance problem ending in a
managed exit, and who argued against premature scope then delivered anyway.

CAREER HIGHLIGHTS
AI in production — Introduced agentic coding tooling into production.
Disagree and commit — Advised against over-scoping, then delivered.

EXPERIENCE
Engineering Manager (Contract) · Example Startup
- Advised against over-scoping ahead of validated demand, then committed and
  delivered when the stakeholders chose otherwise.
"""

ORIGINAL_LETTER = """\
After the acquisition of Example Startup I led the integration. I advised
against over-scoping and committed when overruled. The developer and the
team lead I coached were the same person, and both improved.
"""


class RoutedClient(LLMClient):
    """A fake that answers each prompt label from a script.

    `payloads[label]` is one JSON payload, or a list consumed in order (the
    last one repeats). Prompts are recorded per label so a test can check what
    the model was shown.
    """

    provider = Provider.anthropic

    def __init__(self, payloads: dict[str, object]):
        super().__init__(model="fake-model")
        self.payloads = payloads
        self.prompts: dict[str, list[str]] = {}

    def _complete(self, *, system, prompt, max_tokens):  # pragma: no cover
        raise NotImplementedError

    def complete_json(self, *, prompt, label=None, **kwargs):
        self.prompts.setdefault(label, []).append(prompt)
        script = self.payloads[label]
        if isinstance(script, list):
            payload = script.pop(0) if len(script) > 1 else script[0]
        else:
            payload = script
        if isinstance(payload, Exception):
            raise payload
        return payload, LLMResponse(
            text="{}", provider=self.provider, model=self.model,
            input_tokens=1, output_tokens=1,
        )
