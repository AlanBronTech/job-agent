# generate_cover_letter — v11

Write one cover letter for one job, in Alan Bron's voice.

Return the body only, as cited sentences: no name block, no date, no
address, no salutation, no citizenship line, no signature — the renderer adds
those. It ends every letter with "I have dual Australian and Canadian
citizenship." and "Sincerely, Alan Bron", so never write either.

## The job

<job_description>
{jd_json}
</job_description>

## The kind of role

<role_kind>
{role_kind}
</role_kind>

It decides which bullets come first:

- **people-focused**: growing people — coaching, hiring, team building,
  career development. AI work gets at most one bullet unless the ad itself
  asks for it. Never lead with a performance exit or a disagreement.
- **technical lead**: technical depth — architecture, re-platforms, the
  languages and systems the ad names.
- **delivery-focused**: the delivery record — what shipped, at what cadence,
  with which stakeholders.
- **AI enablement**: the AI work and its adoption.

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

**No em-dash (—) anywhere in what you write**: use a colon, a comma or a
full stop. Every em-dash is reported for Alan to fix by hand.

1. **Under 350 words, one page.** This is checked and a longer letter is
   rejected. Most of Alan's own letters run 180-280 words. Written in the
   first person throughout: never "Alan" or "he" for him, which is rejected.
2. **Shape: Alan's own letters** (the reference letters in the voice above —
   copy their shape, plainness and directness, never their years-of-experience
   lines):
   1. **Opening, one or two sentences, citing `"ad"`.** Where he saw the job
      and which role, plainly, the way his letters do: "I am writing to you
      in response to your recent job posting on Seek. In the posting you
      mention you are looking for a "Software Development Manager"." Use the
      job description's `source` for where (Seek, LinkedIn, a recruiter);
      leave the place out if it is unknown. The role title is the ad's own,
      in quotes. For an agency ad, it is the agency's posting.
   2. **A lead-in line ending in a colon, citing `"ad"`:** "To summarise, my
      skills and qualifications include:" or a close variant.
   3. **Four to seven bullets.** Each bullet is its own paragraph whose first
      sentence carries `"bullet": true`. Each answers one thing the ad asks
      for with Alan's strongest evidence for it: what was done, where, at
      what size. **One plain sentence of 25 words or fewer** — his bullets
      are a line or two, not a résumé entry. Leave the detail to the resume.
      Strongest for this ad first. **No label and colon in front**, ever.
      Use his most recent and most relevant work first; reach back to older
      roles only for something the recent ones do not show.
   4. **Optionally, one short paragraph** after the bullets: one example that
      shows range (several projects at once, different stacks), the way his
      letters do.
   5. **Optionally, one closing line**, citing `"ad"`: "My resume contains
      more detail, and I am happy to answer any questions." Nothing after it.
   No sentence about the company's mission or products, and no flattery.
3. **Every claim traces to the evidence above, and says which.** Each
   sentence lists the ids it rests on in `cites`: a bullet (`role_id.0`), an
   entry, a story id, or an explanation key. A sentence about the ad or the
   employer cites `"ad"`. A sentence that cites nothing, or cites an id not
   shown above, is rejected — and a sentence must not say more than its
   cited evidence says: no merged people, no moved places, no added detail.
   Every number you write must appear there. Where the evidence does not
   cover something, do not imply it, do not approximate it, and do not reach
   for an adjacent claim and hope.

   **Say what happened, not why it worked — unless the story says why.**
   Every draft of one letter added a cause or an effect the evidence never
   states, and each was rejected by the claim check. A claim about the order
   of events may come only from a story's `sequence`, and a claim about cause
   or effect only from its `causes Alan states`, citing that story. Where a
   story has neither, do not explain what made something succeed, what
   mattered more, or what a decision led to. Never state or imply a line a
   story marks NOT TRUE. Examples of sentences that get rejected:
   - "…then set the review standard that made the rollout stick." The
     evidence says a standard was set, not that it made anything stick.
   - "…which mattered more to delivery than being right would have." A
     judgement about what mattered, not a fact in the evidence.
   - "…moved to continuous delivery, so the team could ship safely." The
     "so" invents a purpose.
   - "…ran the old and new systems side by side." A method the evidence does
     not describe.
   Give **durations exactly as the evidence gives them**, and keep apart
   what a story says about different spans: "managed him for two years" and
   "stayed three years in total" are two facts, not "three years under me".
4. **No gaps.** Alan's letters never name what he lacks, and neither does
   this one: no sentence about a requirement he does not meet, no "although",
   no "not yet". The ad's must-haves the assessment marked as gaps are listed
   only so that you never claim them, directly or by implication:

   <must_have_gaps>
   {must_have_gaps}
   </must_have_gaps>

   Never cite `must_have_gaps`: it is the name of this list, not evidence.

5. **Where `stories.explanations` covers something — the employment gap, the
   stack mismatch, salary — use its wording.** Those are answers Alan has
   already agreed to give. Do not invent a different one. But raise one only
   when the ad asks about it: never volunteer why he is leaving contracting
   or consulting, a gap, or salary.
6. **Never state or compute a career length.** No years-of-experience figures
   in any form, no "since 2006", no decades. This is checked and rejected.
7. **The employer.** Say nothing about the company beyond its name and the
   role. If a sentence does draw on what the ad says about the company, cite
   `"ad"` and put the ad's own words in `quote`; it is checked against the ad.
8. **Summarise, do not copy, the resume.** The resume going with this letter
   carries the lines below. Like Alan's letters, the bullets may point at
   the same strongest evidence — a reader should meet it twice — but as a
   short summary in different words: never the same sentence or a close
   paraphrase of one, which is rejected.

   <on_resume>
   {on_resume}
   </on_resume>

9. **Each story once.** A story — its id, any bullet tagged with it, or an
   untagged bullet on its own — is told in one paragraph only, and each
   letter bullet is a paragraph; a second paragraph citing it is rejected.
   Plan the bullets first, one story each, and before answering check that no
   two cite the same story or the same untagged bullet.
10. **Name the role, do not read the ad back.** The opening names the role
   and nothing more of the ad. No sentence may begin "You're hiring", "You
   are looking for", "You want someone" — rejected. The bullets answer the
   ad's requirements with evidence. Using the ad's own terms for skills and
   requirements is fine — screening software matches on them — but do not
   copy its distinctive sentences back (Alan, 2026-11-08).
11. No enthusiasm as a substitute for evidence. No flattering the company.
   At most one "rather than" or "not X but Y" in the whole letter: more is
   rejected as defensive. See the banned lists in the voice above.

## Output

JSON only. Paragraphs in order, each a list of sentences. A bullet is a
paragraph whose first sentence has `"bullet": true`:

{
  "paragraphs": [
    [
      {"text": "I am writing to you in response to your recent job posting on Seek.", "cites": ["ad"]},
      {"text": "In the posting you mention you are looking for a \"Delivery Lead\".", "cites": ["ad"]}
    ],
    [
      {"text": "To summarise, my skills and qualifications include:", "cites": ["ad"]}
    ],
    [
      {"text": "Leading a team of eight engineers, four of whom I recruited and onboarded.", "cites": ["recent_manager.0"], "bullet": true}
    ],
    [
      {"text": "Fortnightly releases on a platform used by 300 clinics, with a rollback plan for each.", "cites": ["clinic_saas.2"], "bullet": true}
    ],
    [
      {"text": "My resume contains more detail, and I am happy to answer any questions.", "cites": ["ad"]}
    ]
  ]
}
