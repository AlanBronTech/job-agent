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
   Every number you write must appear there. Where the evidence does not
   cover something, do not imply it, do not approximate it, and do not reach
   for an adjacent claim and hope.
4. **One honest gap sentence, about a real must-have only.** Name the biggest
   gap from this list and what compensates for it, plainly:

   <must_have_gaps>
   {must_have_gaps}
   </must_have_gaps>

   These are the ad's must-haves the assessment marked as gaps. Never admit a
   gap in something the ad lists as a nice-to-have, an example ("e.g."), or
   "ideally" / "a plus": volunteering it to a screener costs more than it
   buys. If the list is empty, write no gap sentence.
5. **Where `stories.explanations` covers something — the employment gap, the
   stack mismatch, salary — use its wording.** Those are answers Alan has
   already agreed to give. Do not invent a different one.
6. **Never state or compute a career length.** No years-of-experience figures
   in any form, no "since 2006", no decades. This is checked and rejected.
7. **One sentence about the employer, from the ad alone.** If the ad says
   what the company does — its product, customers or mission — write one
   sentence that draws on it, cite `"ad"`, and put the ad's own words you drew
   on in `quote` (verbatim, a phrase or a sentence). The quote is checked
   against the ad. If the ad says nothing about the company, write no such
   sentence: never fill it from general knowledge.
8. **The resume already says these.** The resume going with this letter
   carries the lines below. Prefer evidence it does not show. If you tell one
   of these stories again, tell it differently — what it meant, what you
   decided, what changed — never the same sentence: a copy is rejected.

   <on_resume>
   {on_resume}
   </on_resume>

9. **Each story once.** A story (or a bullet linked to it) is told in one
   paragraph only; a second paragraph citing it is rejected.
10. **Do not open by reading the ad back.** No sentence may begin "You're
   hiring", "You are looking for", "You want someone" — rejected, and every
   letter opened that way reads as a template. Open on the strongest evidence.
11. No enthusiasm as a substitute for evidence. No restating the ad back at the
   reader. No flattering the company. See the banned lists in the voice above.

## Output

JSON only. Paragraphs in order, each a list of sentences:

{
  "paragraphs": [
    [
      {"text": "Growing a team of eight engineers is the work I have done most and want to keep doing.", "cites": ["ad", "recent_manager.0"]},
      {"text": "Route planning for regional carriers is a problem I would like to work on.", "cites": ["ad"], "quote": "route planning for regional freight carriers"},
      {"text": "I recruited and onboarded nine people into a 15-person team.", "cites": ["recent_manager.0"]}
    ],
    [
      {"text": "...", "cites": ["startup_em.1", "scope_disagreement"]}
    ]
  ]
}
