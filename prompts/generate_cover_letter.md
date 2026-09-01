# generate_cover_letter — v1

Write one cover letter for one job, in Alan Bron's voice.

Return the body text only: no name block, no date, no address, no signature —
the renderer adds those. Start at the salutation's next line and stop at the
last sentence.

## The job

<job_description>
{jd_json}
</job_description>

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
3. **Every claim traces to the evidence above.** Every number you write must
   appear there. If the ad asks for something the evidence does not contain,
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

The letter body as plain text. No JSON, no markdown, no headings, no fences.
