# Contract: service layer (`jobagent/services/`)

Shared by `cli/` and `web/`. Rules: no `print`, no `typer`, no `sys.exit`, no
`get_config()`. The first argument is always a `Workspace` (data-model §5).
Every refusal is raised **before** any model client is built. A function that
spends takes a `RunContext`, so the caller sets `command`, `source` and `run_id`.

| Function | Returns | Refusals (before spend) | CLI today |
|---|---|---|---|
| `ads.resolve(ws, *, file=None, latest=False) -> Path` | the ad file | `AdNotFound`, `Conflict` | `jd add --file/--latest` resolution |
| `ads.add(ws, ctx, *, file=None, text=None, source=None) -> AddResult` | stored JD, thin-capture warning, company history | `CaptureTruncated`, `UnreadableAd`, `NoModel` | `jd add` |
| `scoring.score(ws, ctx, jd_id, *, force=False) -> ScoreResult` | stored assessment, company history | `NoSuchAd`, `ThinAd(chars)`, `ProfileMissing`, `ProfileInvalid`, `NoModel` | `score` |
| `documents.plan(ws, jd_id, *, resume, cover, answers, when) -> GeneratePlan` | planned file names, clashes with modification times, verdict, whether an overrule is needed. **Free; spends nothing** | `NoSuchAd`, `NotScored`, `NothingSelected` | new; the CLI calls it first |
| `documents.generate(ws, ctx, jd_id, *, resume, cover, questions, overrule=False, supersede=False, overwrite=False, today, now) -> GenerateResult` | folder, files written, issues, unused entries, superseded folder | `VerdictIsSkip`, `AlreadyGenerated(folder, files)`, `SupersedeFailed`, `ProfileMissing`, `ProfileInvalid`, `NoModel` | `generate` |
| `prep.prepare(ws, ctx, jd_id, *, interviewers=(), save=True) -> PrepResult` | prep, issues, file written | `NoSuchAd`, `NotScored`, `ProfileMissing`, `NoModel` | `prep` |
| `pipeline.apply(ws, jd_id, *, on, channel, reposted_on, note)` | application | `NoSuchAd`, `BadDate` | `apply` |
| `pipeline.outcome(ws, jd_id, status, *, worth, why, note)` | application | `NoSuchAd` | `outcome` |
| `pipeline.board(ws) -> Board` | ads grouped by status, plus "documents generated, not recorded" | — | `status` (extended) |
| `outputs.documents_for(ws, jd) -> OutputFolders` | current / superseded / earlier | — | `jd delete`'s folder report |
| `runs.start_run` / `finish_run` / `unseen_finished` / `mark_seen` / `interrupt_running` | the `ui_runs` registry (data-model §1) | `RunInProgress` | new |
| `costs.estimate(ws, config, action, *, resume=False, cover=False, answers=False) -> CostEstimate` | measured mean for the routed model | — | new |

**Invariants**

- `generate` with `overrule=True` on a skip records `overrode_scorer` exactly as
  `_record_override` does today, before any spend, and failure to record never
  blocks the documents.
- `supersede` and `overwrite` are mutually exclusive. With neither set and a
  clash, `AlreadyGenerated` is raised. With `supersede`, the move happens first,
  and on failure `SupersedeFailed` is raised with the folder untouched.
- Write order is unchanged: resume, letter, answers, `assessment.md`, `job-ad.md`.
- `ads.add` writes the attribution record once the JD id exists, as today.
