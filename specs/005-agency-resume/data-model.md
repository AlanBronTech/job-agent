# Data Model: Agency Resume

Examples are invented (Constitution VI).

## ResumeKind (new, `core/models.py`)

What is asked for at generate time.

| Value | Base | PROFILE | Model calls |
|---|---|---|---|
| `master` | chosen master, copied as is | master's | none |
| `master_profile` | copy of the chosen master | generated, ≤250 words | `generate_profile` (+ claim check) |
| `custom` | generated | two short paragraphs | `generate_resume` (+ claim check) |
| `custom_profile` | generated | ≤250 words | `generate_resume` (+ claim check) |

`master` and `master_profile` need a master: the one named, else the one
suggested; refused when the job is "not a target" and none is named.

## Resume record (existing JSON, `ws.documents.keep_record(..., "resume")`)

Gains two keys; older records lack them and read as unknown.

```json
{
  "issues": [],
  "rewrites": [],
  "coverage": [],
  "base": "em",
  "long_profile": true
}
```

`base` is a master id or `"custom"`.

## LongProfile (in memory, `core/generate.py`)

A `GeneratedText` from `build_profile(...)`: paragraphs of cited `Sentence`s,
issues, rejected drafts, `recheck`. Rendered as the PROFILE paragraphs.
Constant `LONG_PROFILE_MAX_WORDS = 250`.

## Application (existing table `applications`)

| Column | Type | Notes |
|---|---|---|
| `resume_master` | TEXT | existing (v19): master id, `custom`, NULL |
| `resume_suggested` | TEXT | existing (v19) |
| `resume_long_profile` | INTEGER | **new (v20)**: 1, 0, or NULL (before this feature, or unknown) |

Shown as `<id>+profile` or `custom+profile` when 1.

`Application.resume_long_profile: bool | None = None` in `core/models.py`.

## SentResume (existing, `services/masters.py`)

Gains `long_profile: bool | None`. Resolution rules: research R5.

## Validation rules

- Longer profile: at most 250 words (blocker); every sentence cites
  (blocker); the existing prose checks.
- The resume with it: at most 3.0 rendered pages (blocker after one
  shortening).
- The master's PROFILE heading found exactly once, with at least one body
  paragraph, or refused before any spend.
