# Voice — EXAMPLE PROFILE (anonymised)

Generated cover letters and application answers must read as though the
candidate wrote them. The rules below are enforced, not advisory: generated
output is validated against the banned list and regenerated on a hit.

The real version of this file lives outside the repository at
`$PROFILE_DIR/voice.md`.

## Register

Blunt, factual, engineering voice. Short declarative sentences. Specifics over
adjectives. A claim without a number, a name, or a concrete outcome is filler
and gets cut.

Assume the reader is a hiring manager who has read forty letters today and is
looking for a reason to stop reading. Give them a reason to keep going in the
first two sentences: what was built, at what scale, and why it maps to their
problem.

## Structure of a cover letter

1. One sentence: the role, and the single strongest reason to have a
   conversation.
2. Two or three short paragraphs, each anchored on one concrete piece of
   evidence from `roles.yaml` or `stories.yaml`, mapped to a stated
   requirement in the job description.
3. One honest sentence naming the biggest gap, and what compensates for it.
   Naming it first removes it as a screening objection; leaving it unnamed
   means someone else decides what it means.
4. One-line close. No pleading, no "I look forward to hearing from you at your
   earliest convenience".

Under 350 words. One page.

## Output filters — enforced at generation

Never state, imply, or calculate:

- Graduation years, date of birth, or age
- Total years of experience, in any form ("over N years", "N+ years",
  "three decades")
- The year any pre-2015 role started or ended
- Anything from a profile entry marked `visibility: scorer_only`

These are absent from the profile data by design. This section is the second
layer, not the first — if a generation attempt produces one of them, the
profile has leaked something it should not contain and that is the bug to fix.

## Banned phrases — automatic regeneration

- I am thrilled / excited / delighted / passionate about
- perfect fit / ideal candidate / dream role
- proven track record (unless immediately followed by the proof)
- results-driven, detail-oriented, team player, go-getter
- leverage (as a verb), synergy, best-in-class, cutting-edge, world-class
- I would love the opportunity to
- your esteemed company / renowned organisation
- In today's fast-paced world
- delve, tapestry, testament to, navigate the landscape, at the forefront of
- Any sentence beginning "As a seasoned professional"
- Any sentence whose only content is enthusiasm

## Banned moves

- Restating the job advertisement back at the reader
- Claiming enthusiasm as a substitute for evidence
- Flattering the company's mission or products
- Apologising for a gap, an age, or a missing technology
- Listing technologies without saying what was built with them
- Opening with "I am writing to apply for"

## Handling the things that get screened out

**Career length.** Never mentioned, never hinted at, never computed. Lead with
recent work so the reading order puts current capability first.

**Technology stack mismatch.** Name it, then map it. Example shape: "Your stack
is .NET; mine is predominantly Java/Spring and PHP/Laravel. Both are the same
problems in different syntax — here is the specific case where I moved between
them." Stack fit is raised as a screening objection more often than as a
hiring one, and pre-empting it in writing converts better than waiting to be
asked.

**Employment gaps.** Framed factually, as a period with named deliverables.
Three sentences. No grievance, no speculation about anyone's motives.

## Reference letters

Paste two to four real cover letters the candidate was genuinely happy with,
in full, below. They are used as few-shot examples and they matter more than
every rule above — the rules describe the voice, the samples demonstrate it.

Keep them recent. A sample that no longer reflects how the candidate writes
will drag every generation toward an outdated register.

### Example 1
TODO — paste in full

### Example 2
TODO — paste in full

### Example 3
TODO — paste in full