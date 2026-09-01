# generate_answers — v1

Answer the free-text application questions for one job, in Alan Bron's voice.

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

## Voice

<voice>
{voice}
</voice>

## The questions

{questions}

## Rules

1. **One answer per question**, in order, each under 150 words unless the
   question asks for more.
2. **Every claim traces to the evidence above**, and every number you write
   must appear there.
3. **A question about something the profile does not evidence gets an honest
   answer** naming what he has done instead and how close it is. Never
   fabricate the experience, and never dodge the question.
4. **Where `stories.explanations` covers the question, use its wording** — the
   employment gap, the stack mismatch, salary expectations, why he is leaving.
5. Never state or compute a career length.
6. Answer the question that was asked. No preamble, no restating the question.

## Output

Markdown. Each question as a `### ` heading, quoted exactly as it was asked,
with the answer beneath it. Nothing else.
