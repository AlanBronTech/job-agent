# Research: Generation Quality

## R1. Role kind

**Decision**: `prompts/classify_role.md` gets the parsed ad (title, must-haves,
responsibilities, nice-to-haves; not the raw text) and returns
`{"primary": kind, "secondary": kind|null, "reason": "<one sentence>"}` with
kind ∈ `people_focused | delivery_focused | technical_lead | ai_enablement`.
`services.role_kind.ensure` calls it once per ad, stores it (schema v11) and
returns the stored value thereafter. Called from `scoring.score` (shown with
the assessment) and `documents.generate`/`plan`. Its own call type routes from
`LLM_CLASSIFY`, defaulting to `LLM_DEFAULT`, so a cheaper model can be set.

**Rationale**: clarification Q1. The parsed fields carry the signal (must-haves
leading with coaching/1:1s vs. architecture/system design); the raw text
doubles the tokens for nothing.

## R2. Exclusions

**Decision**: `exclude_for: list[RoleKind]` on `Story`, `Bullet` and the four
entry types. `core.roles.filter_for(profile, kinds)` returns a profile view
with excluded stories, bullets (including bullets whose `linked_story` is
excluded) and entries removed. The writer is built from that view; prep is
not. The output is then re-checked: any citation of an excluded id is a
blocker. Both primary and secondary kinds apply (spec edge case).

**Rationale**: the strongest form of "never use" is "never shown"; the check
catches a model citing from memory of the id format.

## R3. Weighting by kind

**Decision**: per-kind guidance lives in the writer prompts (what leads the
profile paragraph and highlights, how much AI material). Two parts are code:
the skills table order (`core.roles.SKILL_ORDER[kind]`, e.g. people_focused →
leadership, delivery, then technical) and a lead check: the first highlight's
cited evidence must carry a tag from the kind's set (people_focused:
`leadership`, `hiring`, `coaching`; technical_lead: `architecture`,
`replatforming`, …), reported as a warning, not a blocker, because tags are
coarse.

## R4. Coverage

**Decision**: from the stored assessment, each `requirements[]` row with status
`met` or `partial` and an `evidence_ref` is "evidenced". The resume selection
must cite that ref, its entry, or a bullet within it, in a highlight or a role
bullet. Missing → blocker "must-have not on the resume", and the list is passed
to the selection prompt as must-cover up front. Only a skills-table hit →
warning "covered weakly". No new call.

## R5. Citations and reuse

**Decision**:
- Resume selection contract adds `profile_refs: list[list[str]]`, one list per
  profile paragraph.
- Letter and answers return `{"paragraphs": [[{"text": "...", "cites": ["id", …]}]]}`
  (answers: per question, `short` and `long` in the same shape). A sentence
  about the ad or the employer cites `"ad"`. Every sentence must cite something;
  every cited id must be in the writer's citable set (R2-filtered) or be
  `"ad"`, a story id, or an explanations key.
- Story reuse: map each cited id to its story (a story id itself, or a bullet's
  `linked_story`). Resume: ≤2 uses, never profile + bullet together. Letter:
  ≤1. One form's answers together: ≤1 per story.
- The letter text is rebuilt from the sentences for rendering, so the docx is
  unchanged in format.

## R6. Claim check (paid)

**Decision**: `prompts/check_claims.md` gets each sentence with the text of the
evidence it cites and returns mismatches: `{"sentence", "problem"}`
(overstated, merged people, wrong place, unsupported detail). Mismatches are
blockers. Runs after the code checks pass, once per letter and once per
answer set. On failure or timeout: documents written, marked "claims not
checked".

## R7. Independent review (paid)

**Decision**: `prompts/review_documents.md` receives the parsed ad, the
policies (`prompts/review_policies.md`: the hard rules, voice.md's banned
list, the age-signal policy, the standing decisions, the exclusion list for
this kind) and the rendered text of each document; never the writer prompts
or the profile's scorer notes. Returns `{"blocking": [...], "suggestions":
[...]}`. Blocking → `GenerateResult.ready = False`. On failure: "not
reviewed". The review's findings are written to `review.md` in the
application folder.

## R8. Defensive phrasing

**Decision**: add to `profile/voice.md`'s banned list (Alan's file, with his
agreement): "not a claim", "not advisory", "full management authority", "this
ad is asking for", "your ad asks for … in practice". Plus a code check in
`validation.py`: more than one "not X but Y" / "not just X" construction per
document → warning.

## R9. Answers

**Decision**: `stories.yaml` gains `answers:` mapping question type → Alan's
text (`summary, why_company, why_role, why_you, what_made_you_apply,
salary_expectation, notice_period, right_to_work, why_leaving`). `generate
--answers FILE [--limit N]` classifies each question to a type inside the same
call, starts from the bank entry, returns short and long variants within the
limit (checked in code), and writes `answers.md`. Questions about the company
may cite only `"ad"`.

## R10. Costs and switches

`services.costs` gains actions `classify`, `check_claims`, `review`. Config
`CHECK_CLAIMS=true`, `REVIEW=true`; CLI `--no-check-claims`, `--no-review`;
the UI's generate confirm shows each with its cost and a box to switch it off.
