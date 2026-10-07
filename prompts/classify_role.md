# classify_role — v1

Classify one job ad by the kind of role it is. The answer decides which
evidence leads a tailored resume and which stories are kept out of it, so
classify by what the ad **leads with**, not by the job title.

## The ad (parsed; the raw text is not needed)

<ad>
{ad_json}
</ad>

## The four kinds

- `people_focused` — the role is mainly about growing people: coaching,
  1:1s, career development, hiring, team health, empathy, culture. An
  Engineering Manager ad usually lands here, but not always.
- `delivery_focused` — the role is mainly about getting things shipped:
  delivery cadence, planning, process, stakeholders, programme or portfolio
  management, agile practice.
- `technical_lead` — the role is mainly about technical depth: system design,
  architecture, hands-on engineering, re-platforming, technical direction.
- `ai_enablement` — the role is mainly about bringing AI into an
  organisation or product: LLMs, agents, AI tooling adoption, ML platforms.

## Rules

1. `primary` is the kind the **first must-haves and responsibilities** ask
   for. When the ad lists several, the ones it states first and at most
   length win.
2. `secondary` is a second kind only when the ad gives it real weight — at
   least one must-have of its own. Otherwise `null`. Never repeat `primary`.
3. `reason` is one sentence naming what in the ad decided it, in plain words
   ("The must-haves lead with coaching, 1:1s and hiring.").
4. Return JSON only, no prose before or after:

```json
{"primary": "people_focused", "secondary": null, "reason": "..."}
```
