# generate_answers — v2

Answer the free-text application questions for one job, in Alan Bron's voice.

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
  building, career development. The first evidence each answer uses comes from that evidence. AI
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

## Voice

<voice>
{voice}
</voice>

## Alan's answer bank — his own words, by question type

Where a question is of a type below, start from his answer and tailor it to
this ad. Do not contradict it. Cite it by its type (`why_leaving`).

<answer_bank>
{answer_bank}
</answer_bank>

## The questions

{questions}

Character limit per answer: {limit}

## Rules

1. **One answer per question**, in order. Classify each question as one of
   `summary`, `why_company`, `why_role`, `why_you`, `what_made_you_apply`,
   `salary_expectation`, `notice_period`, `right_to_work`, `why_leaving`, or
   `other`.
2. **Two variants each**: `short` (two or three sentences) and `long` (the
   fuller answer). Both within the character limit, which is checked.
3. **Every sentence cites what it rests on**: catalogue ids, story ids,
   explanation keys, answer-bank types, or `"ad"` for a sentence about the ad
   or the employer. A sentence that cites nothing or cites an unknown id is
   rejected; a sentence must not say more than its evidence says.
4. **A `why_company` answer uses only the ad's own words** (cite `"ad"`) or
   Alan's bank entry. Nothing about the company that the ad does not say.
5. **No story twice across the form.** One story, one answer.
6. **A question about something the profile does not evidence gets an honest
   answer** naming what he has done instead. Never fabricate, never dodge.
7. **Where `stories.explanations` covers the question, use its wording.**
8. Never state or compute a career length. No preamble, no restating the
   question.

## Output

JSON only:

{
  "answers": [
    {
      "question": "the question, exactly as asked",
      "type": "why_role",
      "short": [{"text": "...", "cites": ["recent_manager.0"]}],
      "long": [{"text": "...", "cites": ["ad"]}, {"text": "...", "cites": ["scope_disagreement"]}]
    }
  ]
}
