# Data Model: Master Resumes

## Profile: `profile/resumes/masters.yaml` (optional)

```yaml
masters:
  - id: manager                 # unique
    label: Engineering Manager
    docx: Sam-Resume-Manager.docx   # relative to profile/resumes/
    pdf: Sam-Resume-Manager.pdf     # optional
    default: true               # exactly one
    use_for: Manager roles.
  - id: ai
    label: AI adoption lead
    docx: Sam-Resume-AI.docx
    role_kinds: [ai_enablement]
    use_for: AI adoption roles.
    not_for: Roles that require shipped production LLM systems.
  - id: contract
    label: Contract engineer
    docx: Sam-Resume-Contract.docx
    work_types: [contract, fixed_term]
    use_for: Contracts only.
```

Unknown keys are refused. `MasterResume` is the same with `docx`/`pdf`
resolved to absolute paths that exist.

## Profile: `never_in_documents`

`never_in_documents: bool = false` on `Story` and `Bullet`. A bullet linked to
such a story goes with it.

## Store (schema v19): `applications` gains

| Column | Type | Notes |
|---|---|---|
| `resume_master` | TEXT NULL | a master's id, or `custom`; NULL before 2026-11-16 or when nothing was recorded |
| `resume_suggested` | TEXT NULL | the suggested master's id, or `not_a_target`; NULL when there was no registry |

## Not stored

`MasterChoice` is computed on every view from the ad, its role kind and the
registry; it is not persisted. Only what went, and what was suggested at that
moment, are.
