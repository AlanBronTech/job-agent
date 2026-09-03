# generate_resume — v2

Select and order profile content for one specific job advertisement.

**You do not write the resume. You choose what goes in it.** Every bullet is
copied verbatim from the catalogue below by its reference — you return
references, never bullet text. A reference you invent fails a lookup and the
generation is rejected, so use only references that appear below.

You write prose in exactly two places: the tagline, and the two PROFILE
paragraphs. Both are checked against the profile afterwards — every number in
them must already appear in the catalogue, and the voice rules apply.

## The job

<job_description>
{jd_json}
</job_description>

## The fit assessment for this job

Already computed. `emphasise` is what to lead with, `requirements` shows what
is met and what is a gap, `challenge_points` is what they will push on. Select
to answer the met requirements and to blunt the challenge points.

<assessment>
{assessment_json}
</assessment>

## The catalogue — the only content that may appear

<catalogue>
{catalogue}
</catalogue>

Skill category keys available: {skills}

## Voice

<voice>
{voice}
</voice>

## Rules

1. **Two pages maximum.** That is roughly 20-24 role bullets in total across
   all roles, plus the highlights. Cut, do not cram — a bullet that does not
   answer something in this ad is taking space from one that does.
2. **Reverse chronological, all of it.** The catalogue lists roles newest
   first; keep that order. Do not promote an older role because it fits better
   — promote its bullets within the role instead, and lead the PROFILE
   paragraphs with it.
3. **Every role in the catalogue appears**, with 1-4 bullets each. A role
   dropped entirely reads as a gap in the record. A weakly relevant role gets
   one bullet, not zero.
4. **Order bullets within a role by relevance to this ad**, strongest first.
5. **Five CAREER HIGHLIGHTS.** Each is a short bold label, then the claim. The
   claim may condense the source bullet but may not add to it: every number in
   it must appear in the bullet you cite as `source_ref`. Label style, from the
   master resume: "AI in production", "Built and sold", "Early bet that paid",
   "Enterprise product", "Startup delivery".
6. **Eight skill categories, ordered with the most relevant first.** Return the
   keys, not the values.
7. **PROFILE is two short paragraphs.** The first says what he is and the
   single strongest thing he has done that matters to *this* ad. The second
   says what he is doing now and where it points. Blunt, factual, specific. No
   adjectives that could be said of anyone.
8. **The tagline** is three short phrases separated by "  ·  ", pitched at this
   ad. The master's is "Engineering Leader  ·  Co-Founder  ·  AI Adoption &
   Delivery".
9. **Never state or compute a career length.** No years-of-experience figures,
   no "since 2006", no decades. Role dates are added by the renderer; you do
   not write them.
10. **`earlier_career_ids`** — all of them, in catalogue order, unless one is
    genuinely irrelevant to this ad. **Closed founder ventures go here too**,
    interleaved in catalogue order; each renders as one dated line. An entry
    marked `[ongoing]` has no line — it is not employment history. Cite it in
    the highlights instead.
11. **`roles` accepts ids from the Roles section only.** Founder ventures and
    AI-capability entries are not roles. Their bullets are still yours to use
    as a highlight `source_ref`, which is where the master resume puts the
    strongest of them.

## Output

JSON only. No prose, no markdown fences.

{
  "tagline": "string",
  "profile_paragraphs": ["first paragraph", "second paragraph"],
  "highlights": [
    {"label": "short bold label", "text": "the claim", "source_ref": "easy_signs.1"}
  ],
  "skill_categories": ["key", "key", "key", "key", "key", "key", "key", "key"],
  "roles": [
    {"role_id": "easy_signs", "bullet_refs": ["easy_signs.1", "easy_signs.0"]}
  ],
  "earlier_career_ids": ["id", "id"]
}
