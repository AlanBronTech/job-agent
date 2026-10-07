# job-agent

A personal job-application agent. It reads a job ad, scores it honestly against
your profile, tells you whether to bother applying, and — if you should —
writes a tailored resume and cover letter built only from evidence you have
already recorded.

**Assistive, not autonomous.** It never submits an application, and it never
scrapes Seek or LinkedIn. You save the ad, it does the work, you send it. The
hard rules are in `CLAUDE.md`.

---

## The UI

```
jobagent ui
```

Opens the tool in your browser, served from this Mac only. Leave the terminal
it prints to open while you use it; Ctrl-C stops it. If the browser does not
open, `jobagent ui --no-browser` prints a link to paste — use the whole link,
including the `?t=…` part, or the buttons will be refused.

**What it does today:**

- **The shortlist.** Every ad with its verdict, both scores, where it is in the
  pipeline and whether documents exist. Sort by date or score.
- **The assessment.** Click an ad for everything `score` would print — hard
  filters (a breach says so; an unstated one says "not stated", never met),
  requirements, what they will push on, questions to ask — plus any history
  with the same company, and the ad text as parsed.
- **Documents.** Every folder for that ad, current, superseded or from an
  earlier month, with **Open** (in Word) and **Reveal in Finder**.
- **Add an ad.** *Add an ad* in the menu: the newest file in
  `~/job-agent-jds/`, a file you drop on the page (kept in that folder), or
  pasted text. You see how much text was read and the cost before it parses; a
  capture cut off at "…more" is refused, and a thin one is flagged.
- **Score.** A button on every ad, and *Re-score* on a scored or stale one. A
  stub needs a box ticked before it will score, as `--force` does.
- **Generate.** Tick resume and letter, paste application questions if there
  are any, and you get a confirmation page first: the files it will write, the
  measured cost, the scorer's reasons if it said skip (with a box to overrule
  it, recorded as `--force` records it), and any documents already there.
  Nothing is spent until you confirm. The result shows every validation issue
  and the profile entries it left out, as the command does.

**Close the tab whenever you like.** A run keeps going on this Mac, and the next
page you open says when it finished. Ctrl-C with a run going asks you to press
it again; the UI then waits for the run so its result and cost are recorded,
and a third Ctrl-C abandons it.

**It never overwrites documents.** If a folder already holds them, the
confirmation says so and the old folder is kept under a dated name next to the
new one (`2026-09.superseded-20260929T140512_Acme_EngineeringManager`), edits
and all.

- **Batch.** *Batch* in the menu: every ad saved since you last added one,
  with the cost of parsing them all, then one table. Tick rows to score
  several (combined cost first) or to mark them not applied; open a row to
  generate. A file that could not be used is its own row, with the reason.

**Still in the terminal for now:** `apply`, `outcome`, `prep`, and anything
under `jd amend`, `jd delete`, `eval` and `spend`.

---

## Several ads at once

Save the ads as usual, then:

```
jobagent batch            # free: the new files, what parsing them costs, then the table
jobagent batch parse      # parse them all
jobagent score 81 82 84   # score several: one combined estimate, then each in turn
jobagent batch skip 83 85 # record the rest as not applied
```

"New" means saved after you last added an ad, so the folder's older files are
never offered at once. Every file gets a row, including one that was cut off at
"…more" or is a copy of an ad already stored, with what to do about it. Generate
stays one ad at a time.

## Applying again

The tool will not score or generate for **the same job you applied for less
than six months ago** (`reapply_window_days: 183` in `profile/assets.yaml`). A
different job at the same company is assessed like any other ad, and company
history alone never rules one out. Nothing is spent on a refused ad.

- **Same job** means the same requisition number (`JR_000123`, `Req ID: 45871`,
  read from the ad text) or the same ad URL. To go ahead anyway:
  `jobagent score <id> --overrule-reapply`, recorded for that ad only.
- **Possibly the same job** means the same company and title where the numbers
  do not settle it. You answer: `jobagent jd same <id> yes` (the rule applies)
  or `no` (assessed normally). The UI shows the same question with buttons.

The rule can only see applications it knows about. Record ones made before the
tool, or straight through a portal:

```
jobagent outside add --company "Acme Logistics" --title "Engineering Manager" \
    --on 2026-05-05 --req JR_000123 --status applied_no_reply
jobagent outside list
jobagent outside link <outside_id> <jd_id>   # once the ad is stored too
```

`jobagent jd backfill` (free) fills in requisition numbers and source files for
ads stored before this existed.

## The loop

Five commands per application. Two of them are optional. The whole thing takes
about ten minutes, most of which is you reading the assessment.

Run them from a terminal in `~/job-agent`, or from inside Claude Code by
prefixing the line with `!` — that runs it in the session so Claude sees the
output too.

### 1. Save the ad, then ingest it

Print the job page to PDF (Chrome: Cmd-P → "Save as PDF") into
`~/job-agent-jds/`. Printing is better than copying: it keeps the URL, the
posting age and the applicant count.

**Expand the description before you print.** Printing does not rescue a
collapsed one — the text behind LinkedIn's "…more" toggle is lazy-loaded and
genuinely absent from the page. The Nuix ad printed on 2026-09-02 gave 706
characters against 6,912 for the same company's expanded ad. `jd add` says so
when it sees it, and `score` refuses to read a stub.

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

**If you have been to this company before, it says so** — every earlier ad from
them in the pipeline, and what became of each:

```
Seen before — Nuix
  JD 14  2026-09-01  Engineering Manager - AI Team  rejected at screen
                     worth it: yes. "I fit the job description reasonably well…"
   JD 7  2026-08-31  Engineering Manager - AI Team  not applied
  4 earlier ads, 1 applied to, 1 rejected at screen. This does not change the verdict.
```

It is a report, not a filter. Nothing about it moves the score, and the same
lines print again before `score` and before `generate`, which is where the
money and the day actually go. If a company ever becomes a flat no, that is a
line you write in `profile/assets.yaml` like any other hard filter, not
something the tool infers from a rejection.

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
  ? location: Hybrid in Sydney NSW. Up to 3 office days a week the
    ceiling is 90 minutes by train or 60 by car one way; more days than
    that and it is 75 minutes by train or 30 by car. Neither can be
    checked from the ad.
  ? salary: No band stated; the floor is $XXX,XXX.

Requirements 4 of 7 met
  ✓ Demonstrated leadership of software engineers
      Led 15 engineers across three product lines. (easy_signs)
  ✗ Kubernetes in production
      Absent from the profile.
...
Ask before applying
  · How many days a week in the office, and is it within 90 minutes by
    train or 60 by car one way (75 minutes by train or 30 by car if more
    than 3 days)?
  · What is the band? The floor is $XXX,XXX.
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

Costs about 14 cents; the command prints its measured estimate before it
spends. If the verdict was `skip`, it refuses:

```
The assessment says skip. Wrong-shaped role: this is IT infrastructure
management, not engineering leadership of a software team.

Generating anyway is a day of work against a role the scorer has already
argued against. Pass --force if you disagree with it.
```

**`--force` overrules it and generates anyway** — and records that you
disagreed, so `jobagent eval report` can later tell you which of you was right.
That is how the tool learns your judgment rather than arguing with it.

It also refuses if you have already generated for this application, before it
spends anything:

```
Already generated. /Users/alanbron/job-agent-out/2026-09_Acme_EngineeringManager
holds documents for this application, most recently 4 September 2026 at 09:07.
  2026-09-04 09:07  AlanBron_Resume_Acme_202609.docx
  2026-09-04 09:07  assessment.md

Re-running would replace these in place, including any edits made by hand
since. Move or rename the folder to keep them, pass --supersede to keep them
under a dated name, or pass --overwrite to replace them.
```

**`--supersede` keeps them**: the folder is renamed with a timestamp,
`2026-09.superseded-20260904T090700_Acme_EngineeringManager`, and a fresh one
is written beside it. The rename happens only once every other check has
passed, just before the first model call, so a run that is refused for another
reason leaves the folder alone. **`--overwrite` replaces them.** Only the files
that run would write are listed — an `interview-prep.md` from `jobagent prep` is never at risk. The
folder name carries the month, so regenerating in a later month starts a fresh
folder and leaves the old one alone.

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

**Fit, coverage and checks (spec 003).** Before writing, each ad is
classified once by the kind of role it is — people-focused, delivery-focused,
technical lead or AI enablement — and `score` shows it with the assessment.
The kind decides what leads the resume and the order of the skills table, and
anything you mark `exclude_for: [people_focused]` (on a story, an entry or a
bullet in `profile/`) is never shown to the writer for that kind of ad; citing
it anyway is a blocker. Interview prep still uses it.

After the folder list you get:

- **Coverage**: each must-have the scorer found evidence for, and where the
  resume answers it. *missing* is a blocker (the evidence exists but no
  highlight or bullet cites it), *weak* means only a skills keyword answers it,
  *gap* is a real gap and stays one.
- **Story reuse**: one story at most twice on a resume (a highlight and a
  bullet, never also the PROFILE paragraph), once in a letter, once across a
  form's answers. Past that is a blocker.
- **Cited prose**: the letter and the answers come back sentence by sentence,
  each naming the evidence it rests on. A sentence citing nothing, or an id
  that does not exist, is a blocker. A company sentence must quote the ad.
- **Two paid checks, on by default**: the *claim check* reads each sentence
  against the evidence it cites (merged people, a moved place, a detail the
  evidence lacks); the *independent review* reads only the ad, the written
  policies and the finished documents, and writes `review.md`. Then one line:
  **Ready**, **Not ready**, or **Not reviewed**. `--no-check-claims` and
  `--no-review` switch them off for a run; documents are then never "ready".

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
| `jobagent jd same <jd_id> yes\|no` | Answer "possibly the same job as an earlier application?" Free. |
| `jobagent jd backfill` | Fill in requisition numbers and source files for older ads. Free. |
| `jobagent batch [parse\|skip IDS]` | Several ads at once; see *Several ads at once*. |

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
| `jobagent score <jd_id>` | Assess one ad against the profile. **Costs ~$0.11.** |
| `jobagent score <jd_id> --last` | Show the last saved assessment. Free. |
| `jobagent score <id> <id> …` | Score several: one combined estimate, then each; a refused one is reported and the rest go ahead. |

`--overrule-reapply` goes ahead with a job you applied for recently (see
*Applying again*).

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
  writes `answers.md` with a short and a long answer to each, starting from
  your answer bank (`answers:` in `profile/stories.yaml`, keyed `summary`,
  `why_company`, `why_role`, `why_you`, `what_made_you_apply`,
  `salary_expectation`, `notice_period`, `right_to_work`, `why_leaving`).
- `--limit N` — with `--answers`, a character limit every answer must meet.
- `--no-check-claims`, `--no-review` — skip either paid check for this run
  (`CHECK_CLAIMS=false` / `REVIEW=false` in `.env` to make it the default).
- `--force` — generate even against a `skip`, and record the disagreement.
- `--supersede` — keep documents already generated: move their folder aside
  under a dated name, then write a fresh one.
- `--overwrite` — replace documents already generated for this application.
  Without one of these, a folder that already holds them stops the run before
  any model call.

Costs about $0.14 for a resume and letter; the estimate is printed before it
spends. The job must be scored first — the
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

Applications made outside the tool: `jobagent outside add|list|link` (see
*Applying again*).

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
pass `--no-save`. Costs roughly $0.11.

### Measuring the scorer

| Command | What it does |
|---|---|
| `jobagent eval report` | Grade stored assessments against outcomes. **Free.** |
| `jobagent eval run` | Re-score every case, then grade. **Costs ~$0.11 each.** |
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
stale through neglect. An application made before its ad was stored (say a
May application to an ad captured from an October repost) is left out and
named in the report: the ad text it would be graded against is not what the
decision was made on.

### Housekeeping

| Command | What it does |
|---|---|
| `jobagent profile validate` | Check `profile/*.yaml` loads and cross-references. |
| `jobagent config check` | Which model each call uses, and whether keys are set. |
| `jobagent ui` | The browser UI, on this Mac only. `--port`, `--no-browser`. |

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

Measured, not estimated — these are the mean per call over 183 real calls on
Claude Sonnet 5, read out of `runs.jsonl` by `jobagent spend`.

| Action | Cost |
|---|---|
| `jd add` | ~$0.03 |
| `score` | ~$0.11 |
| `generate --resume --cover` | ~$0.13 |
| role kind, once per ad | ~$0.003 (one real call so far) |
| claim check, per generate | ~$0.01 (one real call so far) |
| independent review, per generate | ~$0.13 (one real call so far) |
| `prep` | ~$0.11 |
| Everything else, `spend` included | free |

**About 28 cents per application end to end.** The figure used to read 60 cents,
which was two errors compounding: the estimates were conservative, and the
hardcoded price table costed Sonnet 5 at Sonnet 4.6's rate and overstated every
logged call by a third.

**Every paid command says what it expects to cost before it spends** —
`jd add`, `score`, `generate` and `prep` print a line like `Expected cost ~$0.11
(mean of 80 runs on claude-sonnet-5)`, and the UI shows the same figure on its
confirmation page. It is your own past calls' tokens priced at today's rates in
`prices.yaml`, not a figure typed in anywhere. When it cannot say, it says why:
no measurement yet for that model, a price missing from `prices.yaml`, or
budget mode.

Run `jobagent spend` for the real numbers, broken down by job description, by
call and by where it came from: `cli` and `ui` are real work, from the terminal
and the browser; `eval` is grading runs. `jobagent spend --jd 22`
answers what one application cost end to end.

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
