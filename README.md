# job-agent

A personal job-application agent. It reads a job ad, scores it honestly against
your profile, tells you whether to bother applying, and — if you should —
writes a tailored resume and cover letter built only from evidence you have
already recorded.

**Assistive, not autonomous.** It never submits an application, and it never
scrapes Seek or LinkedIn. You save the ad, it does the work, you send it. The
hard rules are in `CLAUDE.md`.

---

## The loop

Five commands per application. Two of them are optional. The whole thing takes
about ten minutes, most of which is you reading the assessment.

Run them from a terminal in `~/job-agent`, or from inside Claude Code by
prefixing the line with `!` — that runs it in the session so Claude sees the
output too.

### 1. Save the ad, then ingest it

Print the job page to PDF (Chrome: Cmd-P → "Save as PDF") into
`~/job-agent-jds/`. Printing is better than copying: it captures the full
description whether or not the "…more" toggle was expanded, and it keeps the
URL, the posting age and the applicant count.

```
jobagent jd add --latest --source seek
```

`--latest` takes the ad you just saved. To pick an older one, give `--file`
enough of its name to be unambiguous — `--file acme` — rather than typing a
filename full of spaces and parentheses. A real path still works.

**What you get back:** the ad parsed into structure — title, company, location,
work type, salary, requirements, red flags — and a JD id at the end:

```
Saved page: 15,400 chars → 10,779 after removing platform furniture.
Posting: Sydney NSW·Reposted 2 weeks ago·Over 100 people clicked apply
...
Saved as JD 22.
```

**That number is the handle for everything else.** Every later command takes
it. If you lose it, `jobagent jd list` shows them all.

**What to do about it:** skim the red flags. If the parse looks wrong — a
company name that is actually the agency, a location that is a sentence — tell
Claude; that is a parser bug worth fixing, not something to work around.

### 2. Score it

```
jobagent score 22
```

This is the command that saves you days. It costs about 20 cents and takes a
minute or two.

**What you get back:** a verdict, two scores, the hard filters, every
requirement marked met / partial / gap with the profile entry that backs it,
what to lead with, and what they will push back on.

```
╭─ JD 22 · Engineering Manager · Acme ─────────────────────────────╮
│ verdict      APPLY WITH CAVEATS                                  │
│ score        62/100 hiring manager  ·  50/100 recruiter screen   │
│ target role  yes Matches target role 'Engineering Manager'...    │
╰──────────────────────────────────────────────────────────────────╯

Hard filters
  ✓ hiring status: Open, or the ad does not say it is closed.
  ✓ work type: permanent is in permanent, contract, fixed_term.
  ? location: Hybrid in Sydney NSW. The 60-minute one-way ceiling
    applies and cannot be checked from the ad.
  ? salary: No band stated; the floor is $150,000.

Requirements 4 of 7 met
  ✓ Demonstrated leadership of software engineers
      Led 15 engineers across three product lines. (easy_signs)
  ✗ Kubernetes in production
      Absent from the profile.
...
Ask before applying
  · Is the office within 60 minutes one way, and how many days on-site?
  · What is the band? The floor is $150,000.
```

**How to read it.**

- **`verdict`** is the recommendation: `apply`, `apply_with_caveats`, or
  `skip`. Most ads are `skip`. That is the tool working, not failing.
- **Two scores, not one.** `recruiter screen` is what survives a keyword pass
  by someone who is not an engineer with 200 applications to get through.
  `hiring manager` is what someone reading properly would conclude. A big gap
  between them is itself the finding.
- **Hard filters** are computed in code, not guessed by a model — salary floor,
  employment type, on-site geography, whether the ad has closed. `✗` means a
  filter you have already decided is breached, and it forces the verdict to
  `skip` no matter how well the role scores. `?` means the ad does not say and
  the answer decides it.
- **`Ask before applying`** is the list of `?` filters turned into questions.
  If a recruiter is involved, ask them before spending the day.

**What to do about it:** if the verdict is `skip`, stop — that is the point.
If you disagree, see step 3.

### 3. Generate the documents

```
jobagent generate 22 --resume --cover
```

Costs about 30 cents. If the verdict was `skip`, it refuses:

```
The assessment says skip. Wrong-shaped role: this is IT infrastructure
management, not engineering leadership of a software team.

Generating anyway is a day of work against a role the scorer has already
argued against. Pass --force if you disagree with it.
```

**`--force` overrules it and generates anyway** — and records that you
disagreed, so `jobagent eval report` can later tell you which of you was right.
That is how the tool learns your judgment rather than arguing with it.

**What you get back:** a folder, and a validation report.

```
/Users/alanbron/job-agent-out/2026-09_Acme_EngineeringManager
  · AlanBron_Resume_Acme_202609.docx
  · AlanBron_CoverLetter_Acme_202609.docx
  · assessment.md
  · job-ad.md

No validation issues.
```

- **The .docx files** are in your master resume's exact format — same fonts,
  spacing, margins, section order — because they are rendered from a template
  derived from it.
- **`assessment.md`** is why the resume was cut the way it was. Months later it
  answers "what was I thinking".
- **`job-ad.md`** is the ad as the parser read it.

**Instead of "No validation issues" you may see blockers:**

```
Blockers 2 issue(s)
  unsupported number    The figure '4711' does not appear anywhere in the
                        profile.
  banned phrase         voice.md bans 'proven track record'.

Do not send these without fixing the blockers.
```

An **unsupported number** means the claim is either invented or missing from
your profile — check which before editing, because if it is real it belongs in
`profile/roles.yaml`. A **banned phrase** or an **age signal** means the draft
broke a rule in `profile/voice.md`; the tool already regenerated once and this
is the second attempt, so fix it by hand or regenerate.

**What to do about it:** open the .docx, read it, edit what you want, send it
yourself. Ten minutes, not two hours.

### 4. Record that you applied

```
jobagent apply 22 --channel seek
```

Free and instant. `--channel` is free text and worth being specific about
— `seek`, `linkedin`, `recruiter — Jane Smith, Talent Int'l`, `referral` —
because across your first fourteen applications the channel predicted the
outcome better than the requirement match did.

### 5. Record what happened

Weeks later, when you know:

```
jobagent outcome 22 interview_1 --worth yes --why "Real EM scope, worth the day"
```

**`--worth` is the important part, and it is not "did they hire me".** It is
*knowing what you know now, was that day well spent*. Those two answers come
apart: you were offered the Easy Signs job and applying was arguably still a
mistake, because the commute that ended it was already an absolute filter in
your profile.

This is the answer key the eval harness grades the scorer against. Without it,
a case is recorded but cannot be marked.

**What you get back:** a one-line confirmation, and a nudge if you left
`--worth` off.

---

## Command reference

### Job descriptions

| Command | What it does |
|---|---|
| `jobagent jd add` | Parse an ad and save it. Prints the new JD id. |
| `jobagent jd list [-n N]` | Every ad, newest first. Where you find a JD id. |
| `jobagent jd show <jd_id>` | One ad in full, as parsed. |

`jd add` options:

- `--file, -f <path or name fragment>` — the saved ad. `.pdf`, `.mhtml`/`.mht`,
  or plain `.txt`; the format is detected, you do not declare it. A path that
  exists is used as given; anything else is matched case-insensitively against
  the filenames in `JD_DIR` (default `~/job-agent-jds`). Two matches is an
  error listing both, never a guess.
- `--latest` — the most recently saved ad in `JD_DIR`.
- `--stdin` — read the ad from a pipe instead.
- `--source <text>` — free text, e.g. `seek`, `linkedin`, `recruiter email`.
- With neither `--file` nor `--stdin`, it opens `$EDITOR` to paste into.

### Scoring

| Command | What it does |
|---|---|
| `jobagent score <jd_id>` | Assess one ad against the profile. **Costs ~$0.20.** |
| `jobagent score <jd_id> --last` | Show the last saved assessment. Free. |

An ad under 800 characters is refused before the call is made — that is
almost always a description that was collapsed when the page was saved,
and the scorer will read two sentences with the confidence it reads a
whole ad. Expand the description, save the page again, re-add it.
`--force` scores it anyway.

### Generating

`jobagent generate <jd_id>` with at least one of:

- `--resume` — a tailored resume.
- `--cover` — a cover letter.
- `--answers <path>` — a text file of application questions, one per line;
  writes `answers.md`.
- `--force` — generate even against a `skip`, and record the disagreement.

Costs roughly $0.15 per document. The job must be scored first — the
assessment is what shapes the selection.

### The pipeline

| Command | What it does |
|---|---|
| `jobagent apply <jd_id>` | Record that you applied. |
| `jobagent outcome <jd_id> <status>` | Record what became of it. |
| `jobagent status [--all]` | The pipeline. Live applications by default. |

`apply` options: `--on YYYY-MM-DD` (defaults to today), `--channel <text>`,
`--note <text>`.

`outcome` options: `--worth yes|no|unsure`, `--why <text>`, `--note <text>`.

**Valid `<status>` values**, in order of how far it got:

| Status | Meaning |
|---|---|
| `identified` | Seen it, not applied yet. A live state. |
| `applied` | Sent, nothing back yet. A live state. |
| `applied_no_reply` | Ghosted. Enough time has passed to call it. |
| `rejected_screen` | Rejected before any conversation. |
| `recruiter_call` | A recruiter spoke to you, went no further. |
| `interview_1` | First-round interview. |
| `interview_2` | Second round or beyond. |
| `offer` | Offer made. |
| `withdrew` | You pulled out. |
| `not_applied` | Saw it, decided against applying. |

The two **live states** — `identified` and `applied` — are excluded from
grading. A case that has not finished happening tells the eval harness nothing.

### Interviews

```
jobagent prep <jd_id> -i "Jane Smith, CTO" -i "Sam Lee, Eng Manager"
```

Likely questions mapped to real stories from your story bank, with the
assessment's challenge points as the hard ones — those are not predictions,
they are objections the scorer already found in the gap between the ad and your
profile. Also writes `interview-prep.md` into the application folder unless you
pass `--no-save`. Costs roughly $0.15.

### Measuring the scorer

| Command | What it does |
|---|---|
| `jobagent eval report` | Grade stored assessments against outcomes. **Free.** |
| `jobagent eval run` | Re-score every case, then grade. **Costs ~$0.19 each.** |
| `jobagent eval diff` | What changed between the last two runs. Free. |
| `jobagent eval export` | Write the case set out as reviewable YAML. Free. |

- `eval report --model claude-sonnet-5` — grade one model's runs. Without it,
  whatever was scored last wins, which matters if you have run a comparison.
- `eval report --cases <path>` — replay a fixed snapshot instead of the live
  pipeline.
- `eval diff --model claude-sonnet-5` — compare two runs of the same model.
  Use it after any prompt edit: without it the two newest runs are compared
  whatever produced them, and one budget run in between reads as a fifty-point
  prompt regression. The diff names the models it used and warns when they
  differ.
- `eval run --only <case_id>` — one case. `--yes` skips the cost prompt.

The case set builds itself from the applications you record, so it cannot go
stale through neglect.

### Housekeeping

| Command | What it does |
|---|---|
| `jobagent profile validate` | Check `profile/*.yaml` loads and cross-references. |
| `jobagent config check` | Which model each call uses, and whether keys are set. |

---

## Running low on cash

```
jobagent --budget score 22
```

`--budget` routes **every** model call to a free-tier model instead of Claude.
Set `BUDGET_MODE=true` in `.env` to make it permanent, and `BUDGET_MODEL` to
choose a different one.

Two things to know. The free tier is **20 requests a day** on
`gemini-2.5-flash`, so it is a handful of ads, not a working day — you get a
clear message when the allowance runs out rather than a confusing failure. And
the answers are measurably worse: on the same fourteen cases Claude agreed with
your judgment 10 times and Gemini 4 times. Use it to keep working when cash is
tight, not as the default.

---

## Where everything lives

| Path | What it holds |
|---|---|
| `~/job-agent-jds/` | Saved job ads. Print pages to PDF into here. |
| `~/job-agent-out/` | One folder per application: documents, assessment, ad. |
| `~/.job-agent/jobagent.db` | The store — ads, assessments, applications. |
| `profile/` | You, as data. Everything generated is built from this. |
| `prompts/` | The prompts, versioned as files so they can be diffed. |
| `evals/cases.yaml` | An exported snapshot of the eval set. Local only — it is your application history, and this repository is public. |
| `runs.jsonl` | Every model call: prompt, tokens, cost. |

Back up `~/.job-agent/jobagent.db` and `profile/` and you have lost nothing
that matters. The rest regenerates.

---

## Costs, roughly

| Action | Cost |
|---|---|
| `jd add` | ~$0.08 |
| `score` | ~$0.20 |
| `generate --resume --cover` | ~$0.30 |
| `prep` | ~$0.15 |
| Everything else | free |

About 60 cents per application end to end. `runs.jsonl` has the real figures if
you want to check.

---

## When something looks wrong

**A parse looks wrong** — wrong company, a location that is a sentence, missing
requirements. That is a parser bug. Tell Claude; the ad is kept verbatim in the
store, so it can be re-parsed without re-saving anything.

**The scorer says skip and you disagree.** Use `--force`. It is recorded, and
`eval report` will eventually tell you which of you was right. Right now the
scorer's errors all point one way — it says skip on roles you judge you fit —
so your disagreements are worth logging.

**A generated document has blockers.** Read them. An unsupported number is
either an invention (a real bug) or a gap in `profile/roles.yaml` (worth
filling in). Neither should be ignored.

**`jobagent` is not found.** It lives in `.venv/bin/jobagent` and is already on
your PATH from `~/job-agent`. From elsewhere, use the full path.

---

## Why it exists

Tailoring a resume and cover letter per application takes two to three hours.
Roughly half of that is judgement that has to stay human. The other half is
mechanical selection from a fixed set of evidence, which is exactly what an LLM
does well when it is constrained to a structured source of truth.

The measurable claim is in `evals/`: the fit scorer is graded against fourteen
real applications with known outcomes, on whether applying was worth the day
rather than on whether the employer said yes. It currently agrees with your
judgment on 10 of 14, and every one of its errors is in the same direction.
That number, and knowing which way it is wrong, is the point of the project.
