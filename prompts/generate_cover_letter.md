# generate_cover_letter — v2

Write one cover letter for one job, in Alan Bron's voice.

Return the body only, as cited sentences: no name block, no date, no
address, no salutation, no signature — the renderer adds those.

## The job

<job_description>
{jd_json}
</job_description>

## The kind of role

<role_kind>
{role_kind}
</role_kind>

What leads depends on it:

- **people-focused**: lead with growing people — coaching, hiring, team
  building, career development. The opening sentence and the first evidence paragraph come from that evidence. AI
  work gets at most one clause unless the ad itself asks for it. Never open
  on a performance exit or a disagreement.
- **technical lead**: lead with technical depth — architecture, re-platforms,
  system design decisions and their trade-offs.
- **delivery-focused**: lead with the delivery record — what shipped, at what
  cadence, with which stakeholders.
- **AI enablement**: lead with AI work in production and its adoption.

Evidence the profile excludes for this kind of role has already been removed
from what you are shown. Do not refer to it from memory.

## The fit assessment

<assessment>
{assessment_json}
</assessment>

## Evidence — the only facts you may use

<catalogue>
{catalogue}
</catalogue>

<stories>
{stories}
</stories>

## Voice — follow this exactly

<voice>
{voice}
</voice>

## Rules

1. **Under 350 words.** One page. This is checked and a longer letter is
   rejected.
2. **Structure**, per voice.md: one sentence naming the role and the single
   strongest reason to have a conversation; two or three short paragraphs each
   anchored on one concrete piece of evidence mapped to a stated requirement in
   the ad; one honest sentence naming the biggest gap and what compensates for
   it; a one-line close.
3. **Every claim traces to the evidence above, and says which.** Each
   sentence lists the ids it rests on in `cites`: a bullet (`role_id.0`), an
   entry, a story id, or an explanation key. A sentence about the ad or the
   employer cites `"ad"`. A sentence that cites nothing, or cites an id not
   shown above, is rejected — and a sentence must not say more than its
   cited evidence says: no merged people, no moved places, no added detail.
   Every number you write must appear there. If the ad asks for something the evidence does not contain,
   name it as the gap — do not imply it, do not approximate it, and do not
   reach for an adjacent claim and hope.
4. **The gap sentence is not optional and is not softened.** The assessment's
   `requirements` marked `gap` and its `challenge_points` are where it comes
   from. Naming it plainly is the point: it is what makes the rest credible.
5. **Where `stories.explanations` covers something — the employment gap, the
   stack mismatch, salary — use its wording.** Those are answers Alan has
   already agreed to give. Do not invent a different one.
6. **Never state or compute a career length.** No years-of-experience figures
   in any form, no "since 2006", no decades. This is checked and rejected.
7. No enthusiasm as a substitute for evidence. No restating the ad back at the
   reader. No flattering the company. See the banned lists in the voice above.

## Output

JSON only. Paragraphs in order, each a list of sentences:

{
  "paragraphs": [
    [
      {"text": "You are hiring an Engineering Manager to grow a team of eight.", "cites": ["ad"]},
      {"text": "I recruited and onboarded nine people into a 15-person team.", "cites": ["recent_manager.0"]}
    ],
    [
      {"text": "...", "cites": ["startup_em.1", "scope_disagreement"]}
    ]
  ]
}
