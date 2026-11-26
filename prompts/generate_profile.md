# generate_profile — v1

Write the PROFILE section of Alan Bron's resume for one job: the longer,
agency version. Everything else on the resume is one of his hand-written
master resumes and stays exactly as it is; only this section is yours.

Return the PROFILE paragraphs only, as cited sentences: no heading, no name,
no contact details.

## The job

<job_description>
{jd_json}
</job_description>

## The kind of role

<role_kind>
{role_kind}
</role_kind>

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

1. {long_profile_rules}
2. **Every claim traces to the evidence above, and says which.** Each
   sentence lists the ids it rests on in `cites`: a bullet (`role_id.0`), an
   entry, a story id, or an explanation key. A sentence about the ad or the
   kind of role sought cites `"ad"`. A sentence that cites nothing, or cites
   an id not shown above, is rejected, and a sentence must not say more than
   its cited evidence says: no merged people, no moved places, no added
   detail. Every number you write must appear there. Give durations exactly
   as the evidence gives them. Say what happened, not why it worked, unless a
   story's `causes Alan states` says why; a claim about the order of events
   comes only from a story's `sequence`. Never state or imply a line a story
   marks NOT TRUE.
3. **No gaps.** The ad's must-haves the assessment marked as gaps are listed
   only so that you never claim them, directly or by implication. Never cite
   `must_have_gaps`: it is the name of this list, not evidence.

   <must_have_gaps>
   {must_have_gaps}
   </must_have_gaps>

4. **Never state or compute a career length.** No years-of-experience
   figures in any form, no "since 2006", no decades. This is checked and
   rejected.
5. **The rest of the resume is already written.** It carries the lines
   below. The profile may point at the same strongest evidence, as a short
   summary in different words: never the same sentence or a close paraphrase
   of one, which is rejected.

   <on_page>
   {on_page}
   </on_page>

6. **Each story once.** A story (its id, any bullet tagged with it, or an
   untagged bullet on its own) is told in one paragraph only.
7. No enthusiasm as a substitute for evidence. Nothing about the employer
   beyond its name and the role. At most one "rather than" or "not X but Y"
   in the whole profile. See the banned lists in the voice above.

## Output

JSON only. Paragraphs in order, each a list of sentences:

{
  "paragraphs": [
    [
      {"text": "Engineering manager and co-founder.", "cites": ["recent_manager"]},
      {"text": "I led a team of eight engineers across two product lines.", "cites": ["recent_manager.0"]}
    ],
    [
      {"text": "Fortnightly releases on a platform used by 300 clinics, with a rollback plan for each.", "cites": ["clinic_saas.2"]}
    ],
    [
      {"text": "I am looking for a permanent engineering manager role.", "cites": ["ad"]}
    ]
  ]
}
