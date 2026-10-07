# Data Model: Generation Quality

## Store (core schema v11): `job_descriptions` gains

| Column | Type | Notes |
|---|---|---|
| `role_kind` | TEXT NULL | `people_focused` \| `delivery_focused` \| `technical_lead` \| `ai_enablement`; NULL until first needed |
| `role_kind_secondary` | TEXT NULL | same vocabulary, optional |
| `role_kind_reason` | TEXT NULL | one sentence from the classifier, shown with the assessment |

An amendment clears all three (the ad changed).

## Profile

- `RoleKind` enum, the four values above.
- `exclude_for: list[RoleKind] = []` on `Story`, `Bullet`, `Role`,
  `FounderEntry`, `AiCapabilityEntry`, `EarlierRole`.
- `StoriesFile.answers: dict[QuestionType, str] = {}`, QuestionType ∈
  `summary, why_company, why_role, why_you, what_made_you_apply,
  salary_expectation, notice_period, right_to_work, why_leaving`.

## Generation contracts (model output)

- Resume selection: + `profile_refs: list[list[str]]` (one list per paragraph).
- Letter: `{"paragraphs": [[{"text": str, "cites": [str, …]}]]}`.
- Answers: `{"answers": [{"question": str, "type": QuestionType, "short": <sentences>, "long": <sentences>}]}`.
- Classifier: `{"primary": RoleKind, "secondary": RoleKind|null, "reason": str}`.
- Claim check: `{"mismatches": [{"sentence": str, "problem": str}]}`.
- Review: `{"blocking": [{"document": str, "finding": str}], "suggestions": [...]}`.

## Results

`GenerateResult` gains `role_kind`, `coverage` (must-have → where it appears or
"gap" / "weak"), `ready: bool`, `review: list[finding] | "not reviewed"`,
`claims: list[mismatch] | "not checked"`. New issue rules: `uncited claim`,
`unknown citation`, `excluded evidence`, `story reused`, `must-have missing`,
`covered weakly`, `lead not on-kind`, `contrast phrasing`, `answer over limit`,
`claim mismatch`, `review`.
