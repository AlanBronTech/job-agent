# interview_prep — v1

Prepare Alan Bron for an interview for one specific job.

He is an engineering manager who has been interviewed many times. Do not
explain what a behavioural question is, do not pad, and do not write answers
for him to recite — write the outline he needs to have thought about before he
walks in.

## The job

<job_description>
{jd_json}
</job_description>

## The fit assessment

The `challenge_points` in here are **already being used as the hard questions**
— you do not need to repeat them. Read them so your questions do not duplicate
them, and so you know where the gaps are.

<assessment>
{assessment_json}
</assessment>

## Who is interviewing

{interviewers}

## The story bank — the only material you may draw on

<stories>
{stories}
</stories>

## Voice

<voice>
{voice}
</voice>

## Rules

1. **Eight to twelve questions**, ordered by how likely they are. Cover: the
   role's stated responsibilities, the technical depth the ad implies, the
   people-management substance, and one or two on why he is available.
2. **`story_ref` must be an id from the story bank above**, or `null`. A
   reference you invent sends him into a room to tell a story that does not
   exist. `null` is the honest answer when no story fits — and a question with
   no story behind it is worth surfacing, because it is the one to prepare
   hardest.
3. **`answer_outline` is what to say, in his voice** — the specifics, the
   numbers, the outcome. Not a script. Three or four sentences at most. Every
   figure must come from the story bank or the assessment.
4. **Where `stories.explanations` covers a question — the employment gap, the
   stack mismatch, salary, why he is leaving — use its wording.** Those are
   answers he has already agreed to give.
5. **`why_asked` is one line**, and says what the interviewer is actually
   testing. "They will want to know whether he has managed someone out, not
   whether he has managed" is useful. "To assess leadership" is not.
6. **`questions_to_ask` are questions for him to ask them.** The assessment's
   unresolved filters are added automatically — add what a manager should ask
   about the team, the delivery record, and what the first six months look
   like. Three or four, specific to this ad.
7. **`opening`** is two or three sentences: how he answers "tell me about
   yourself" for *this* role. Blunt and specific. Never a career length.
8. Never state or compute a career length, in any answer.

## Output

JSON only. No prose, no markdown fences.

{
  "opening": "two or three sentences",
  "questions": [
    {
      "question": "what they will ask",
      "why_asked": "one line on what is being tested",
      "story_ref": "story id or null",
      "answer_outline": "what to say, three or four sentences"
    }
  ],
  "questions_to_ask": ["what he should ask them"]
}
