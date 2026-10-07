# Implementation Plan: Generation Quality

**Branch**: `003-generation-quality` | **Date**: 2026-10-07 | **Spec**: [spec.md](spec.md)

## Summary

Make the writer choose and cite, and check what it wrote, mostly in code:

- **Role kind**: one new small model call per ad, made on first need and
  stored on the ad. It drives the evidence order (prompt), the skills order
  (code) and the exclusions (code: excluded evidence is removed from what the
  writer is shown, so it cannot be used).
- **Coverage** comes free from the assessment the scorer already wrote:
  each `requirements[]` row with `met` or `partial` carries an `evidence_ref`,
  and the resume is checked to cite it.
- **Citations everywhere prose is written.** The resume selection gains refs
  for its profile paragraphs; the cover letter and answers come back as
  sentences with cited evidence ids. That gives story-reuse counts and the
  "every claim cites something" check, both in code.
- **Two paid checks, on by default**, each with its cost shown: a claim check
  (each sentence against the evidence it cites) and an independent review
  (ad + policies + documents only). Blocking findings mark the documents not
  ready.
- **Answers** gain an answer bank in the profile, a character limit and
  short/long variants; the UI's cover-letter box starts unticked.

The scoring prompt is not touched, so the eval set is unaffected. Writer
prompts change; there is no eval for the writer, so the regression check is
the worked example (invented) in tests, plus a scratch-folder regenerate of the
real ad it came from, run once with Alan's agreement.

## Technical Context

**Language/Version**: Python 3.12, `uv`. **Dependencies**: none new.

**Storage**: core schema v11 adds `role_kind`, `role_kind_secondary` and
`role_kind_reason` to `job_descriptions`. Profile schema gains `exclude_for`
on stories, bullets and entries, and an `answers` bank in `stories.yaml`.

**Model calls**: three new prompts in `prompts/`, all through `adapters/llm.py`
with call types routed from config like the others:
`classify_role` (~$0.01, reads the parsed ad only), `check_claims` (~$0.03),
`review_documents` (~$0.05). Estimates to be measured with `jobagent spend`
after the first runs (Constitution V). Expected per application with checks on:
about $0.37, under SC-006's $0.45.

**Testing**: pytest, model mocked; invented worked example (Northwind Freight,
people-focused) as the fixture for SC-001/003/004.

**Constraints**: hard rules unchanged; gap sentence, founder years and master
format unchanged (FR-014); a failed paid check never discards documents, it
marks them "not reviewed".

## Constitution Check

| Principle | Status | How |
|---|---|---|
| I. Assistive | Pass | No submission; answers are produced to paste. Company sentence only from the ad's text. |
| II. `core/` callable anywhere | Pass | Changes in `core/` are domain logic used by the CLI and UI alike: profile schema, citation and reuse checks in `validation.py`, the new contracts in `generate.py`, the role-kind columns. The two paid checks and the classifier are orchestrated in `services/`. |
| III. Enforce mechanically | Pass | Exclusions remove evidence from the writer's input and are re-checked on output; citations, reuse caps, coverage and contrast-phrasing counts are code checks. The paid checks add judgement on top; they are not the only guard. |
| IV. No network in tests | Pass | All three new calls mocked. |
| V. Money stated first | Pass | Each new call has a stated estimate above, is shown by `services.costs` before running, and is logged with `command`/`source`. |
| VI. Public repo | Pass | Invented example; Alan's answer bank lives in his gitignored profile. |

## Project Structure

```text
prompts/
  classify_role.md        NEW
  check_claims.md         NEW
  review_documents.md     NEW  (sees ad, policies, documents; never the writer prompts)
  review_policies.md      NEW  the written policies the reviewer checks against
  generate_resume.md      + role kind, must-cover list, profile_refs
  generate_cover_letter.md + role kind, JSON sentences with cites, company sentence
  generate_answers.md     + answer bank, limit, short/long, JSON with cites
jobagent/
  core/
    models.py       RoleKind enum; exclude_for on Story/Bullet/entries; AnswerBank; JD role_kind fields
    store.py        v11 columns
    roles.py        NEW pure: exclusion filtering of catalogue/stories; skills order by kind
    generate.py     new selection contract (profile_refs); letter/answers as cited sentences
    validation.py   citation check, story-reuse caps, coverage check, contrast-phrase count
  adapters/llm.py   CallType.classify, CallType.review (routes; default to LLM_DEFAULT)
  services/
    role_kind.py    NEW ensure(ws, config, ctx, jd_id): classify once, store
    checks.py       NEW claim check + review, cost-aware, failure → "not reviewed"
    documents.py    role kind before generate; checks after; ready flag
    scoring.py      role kind ensured (shown with the assessment)
    costs.py        new actions: classify, check_claims, review
  cli/ generate.py  --no-check-claims, --no-review, --limit for answers; shows readiness
  web/              generate confirm shows the extra costs; letter unticked; result shows review
```

## Complexity Tracking

| Choice | Why | Rejected |
|---|---|---|
| Letter and answers return JSON sentences with cites, not prose | The only way to count story use and require a citation per claim in code | Inline citation markers in prose: one malformed marker breaks parsing silently; free prose: cannot be checked |
| Exclusions applied to the writer's input, then re-checked on output | Removing evidence is stronger than forbidding it; the output check catches a model citing an id it was not shown | A prompt rule only: "a rule that only forbids gets satisfied by rephrasing", as CDK was on 2026-10-07 |
| Two paid checks on by default | Alan's choice (2026-10-07); together about $0.08 against an hour of hand edits | Opt-in: the checks protect most when forgotten |
