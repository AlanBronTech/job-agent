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

**Write one hard question for every `challenge_point` in here.** Each is a gap
the scorer found between this ad and the profile, and each is a question he will
be asked. Phrase it the way an interviewer would ask it out loud — not as the
topic the scorer named it by — and mark it `"hard": true`.

The `response` on a challenge point is written *about* him, for him to read. Do
not copy it. Write the answer he would say, in the first person, to the rules
below.

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

1. **Eight to twelve questions**, ordered by how likely they are. Cover: every
   `challenge_point` (marked `hard`), the role's stated responsibilities, the
   technical depth the ad implies, the people-management substance, and one or
   two on why he is available.
2. **`story_ref` must be an id from the story bank above**, or `null`. A
   reference you invent sends him into a room to tell a story that does not
   exist. `null` is the honest answer when no story fits — and a question with
   no story behind it is worth surfacing, because it is the one to prepare
   hardest.
3. **`answer_outline` is what to say, in his voice** — the specifics, the
   numbers, the outcome. Not a script. Three or four sentences at most. Every
   figure must come from the story bank or the assessment. Write it as he would
   say it: "I have not used either framework", never "he has not used either
   framework". It is read minutes before he walks into a room.
   Never name a profile field in it. `stories.explanations.why_leaving_current`
   is where an answer came from, not something a reader should ever see.
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
   **Do not restate a question the assessment already asks, in any wording.**
   Rephrasing one is worse than repeating it: a duplicate is obvious and a
   rephrasing is not, and the list is read as a checklist in a room.
7. **`opening`** is two or three sentences: how he answers "tell me about
   yourself" for *this* role. Blunt and specific. Never a career length.
8. Never state or compute a career length, in any answer.

## Output

JSON only. No prose, no markdown fences.

`hard` is required on every question: `true` for the ones answering a
`challenge_point`, `false` otherwise. It decides which section of the document
a question is printed in, and omitting it files a hard question as small talk.

{
  "opening": "two or three sentences",
  "questions": [
    {
      "question": "what they will ask",
      "why_asked": "one line on what is being tested",
      "story_ref": "story id or null",
      "answer_outline": "what to say, three or four sentences",
      "hard": true
    }
  ],
  "questions_to_ask": ["what he should ask them"]
}
