# job-agent: an application assistant that is not allowed to make things up

job-agent is a personal tool for applying to jobs. It reads a job ad, scores
it honestly against a structured profile, writes a tailored resume and cover
letter, and tracks the pipeline. It is assistive, not autonomous: it never
submits anything, never scrapes a job board, and a person reads every
document before it goes anywhere.

I built it by directing Claude Code, from August 2026, while using it for my
own job search. This is what it does differently from asking a chatbot for a
resume, and where it still falls short.

## The problem with "write me a cover letter"

A language model asked to persuade will fill gaps with plausible detail. Ask
for a letter for an engineering-manager role and you get a team size nobody
stated, a migration that "ran side by side" when it did not, and a cost
saving with no source. Each sentence reads well. Some are false, and the
false ones are the ones an interviewer asks about.

The fix is not a better prompt. A rule that only forbids gets satisfied by
rephrasing. The fix is to change what the model is allowed to produce, and
then check what it produced against something it cannot argue with.

## 1. A structured profile is the only source of truth

Everything the tool may say lives in YAML files: roles with dated bullets,
founder ventures, an earlier-career summary, a story bank, agreed answers
to awkward questions, and hard constraints (salary floor, commute, work
type, day rate). The profile has two kinds of field that matter:

- `text` is rendered. It is what may appear in a document.
- `note_for_scorer` is not. It holds facts the scorer should weigh but the
  writer must never see, such as a figure that must not be published.

A third, `note_for_writer`, holds rules about *how* to write an entry, and
is shown only to the writer. Keeping these apart was learned the hard way:
a writing rule parked in the scorer's notes bound only the model that does
not write, and a generated highlight broke it for a week before anyone
noticed the writer had never been shown it.

Stories carry their mechanism, not just their outcome: the order things
happened in, how it worked, why it was done that way, the causes the person
is willing to sign, and a `not_true` list of tempting inferences that are
false. Letters invented mechanisms because persuasion needs *how*, and the
evidence recorded mostly *what*. Writing the mechanism down removed the gap
the model was filling.

## 2. For the resume, the model returns references, not prose

The resume generator does not write bullets. It returns ids — which roles,
which bullets, in what order — and the text is copied verbatim from the
profile. A model that cannot type a bullet cannot embellish one.

It writes prose in three places only: the tagline, two short PROFILE
paragraphs, and five CAREER HIGHLIGHTS. Each PROFILE paragraph and each
highlight must name the profile ids it draws on, and is then checked against
them. Cover letters and application answers are returned as sentences, each
with its citations, for the same reason: a citation can be counted and
checked; free prose cannot.

## 3. Validation is code first, judgement second

Hard rules are enforced mechanically in `core/validation.py`, not by asking
nicely:

- **Every number traced to the profile.** The set of licensed numbers is
  built by walking the profile and *excluding* scorer notes, phone numbers
  and the voice rules (which quote banned age signals as examples). The
  check is unit-blind and is described that way: it catches an invented
  figure, not a real figure moved to the wrong claim.
- **Banned phrases** parsed out of the voice file at runtime.
- **Age-signal rules**: dates as years, no computed career length.
- **Claims about order** ("my first leadership role") are blocked, because
  the record can contradict them.
- **A gap may be admitted only against a firm must-have** — not against
  "e.g. Kubernetes" or "ideally".
- **No repetition**: a highlight may not restate a bullet printed below it,
  and the letter may not copy the resume.

On top of the code sits a paid claim check, about two cents per document: a
separate model call reads each written sentence beside the full text of the
evidence it cites, and marks overstatement, merged people, a moved place,
an added detail, an invented mechanism or cause, and anything contradicting
a `not_true` line.

A check that fails is a stop, not a note. Any blocker has the document
written again once, with the failures named. If a blocker survives,
`_NOT-READY` goes into the file name. A warning printed beside a finished
file was sent anyway; a file name cannot be skimmed past.

A paid check never loses the documents. If it times out, the documents are
written and are simply never called ready.

## 4. Hard filters are arithmetic; judgement is the model's

Salary floor, day-rate floor, employment type, on-site geography and closed
ads are computed in Python, from decisions already made. A breach overrides
the model's verdict outright, and "the ad does not say" is a third state,
not a pass. The model is asked only for what needs judgement: how the
profile reads against the ad, for a hiring manager and for a recruiter
screen separately, and what an interviewer will push on.

A cheap first-pass screen (a fraction of a cent per ad) suggests which ads
are worth a full score. It is advice, tuned to be cautious: on 65 labelled
cases it skipped none of the 11 worth applying to, and caught 9 of the 40
the full scorer would skip. Its value is the zero, not the nine.

## 5. The eval is graded on "was the day well spent", not "was he hired"

The eval set is built from the application records themselves, so it cannot
go stale through neglect, and each case is labelled with my retrospective
judgement of whether applying was worth the day. Not whether I was hired:
one offer came from an application that was still the wrong call, because
the commute that ended it is a hard filter. Grading on hiring outcomes would
tune that constraint away.

The eval is a regression detector, not a measurement of quality. With a few
dozen cases the confidence interval on accuracy is far too wide to call a
scorer good, and the same prompt moves scores by about six points between
runs, so a boundary case flips verdict on noise. The number reported is
"no regression beyond the noise floor", and the number watched is the
separation between the mean scores of worthwhile and not-worthwhile cases,
not a percentage.

## 6. The quality metric: what is sent is what was generated

The goal is that the documents sent are the documents generated, unedited.
Every edit made by hand is either a defect (fix the code or prompt, with a
test), a missing fact (fix the profile), a preference (fix the voice rules),
or something only the applicant knew (give it to the tool as context before
generating).

To measure it, `generate` keeps an immutable copy of what it wrote, `apply`
records the file actually sent, and `jobagent diff` compares them section by
section: kept-word share, sentences added, removed and changed. Revisions go
through the tool (`jobagent revise --note "…"`) rather than through Word, so
each correction is stored, counted, and can be promoted into the profile
once it recurs. The first pair measured kept about half of each document.
Of the six documents recorded as sent since, three went out unedited.

## 7. Cost is measured, not remembered

Every model call is logged with what it was for — command, job, source
(terminal, UI or eval) and a run id — including calls that fail, because
those were billed too. Prices live in a dated table; a model missing from it
is logged as "price unknown", never as free. Every paid command prints its
expected cost before spending, computed from past calls' tokens at today's
prices. Routine steps (reading an ad, classifying it, the screen) default to
cheap or free-tier models.

The honest number: a full application, with rewrites and revisions, has run
from about $0.40 to $2.40, median about $0.90. Rewrites are the main cost,
and `jobagent rewrites` reports which checks reject first drafts.

## What it does not do well

- **The claim check is a model.** It catches most invented mechanisms and
  overstatements, but it can miss one, and it can flag a faithful
  paraphrase. It reduces reading; it does not replace it.
- **Rewrites are expensive.** Each blocker can double a document's cost.
  The cheaper fix is usually in the evidence, not in another validator.
- **Rules accumulate.** Many defects found in real documents became a
  check. That keeps the same defect from recurring, and it also means the
  codebase records a long history of specific failures. The decision log in
  `docs/decisions.md` keeps the reasons next to the rules.
- **The eval is small.** It catches a prompt edit that moves verdicts. It
  cannot tell a good scorer from a mediocre one.
- **It is built around one person.** Some policies, such as how founder
  dates render, are code paths rather than per-profile settings.

## Stack

Python 3.12, Typer, Pydantic v2, SQLite with plain SQL, python-docx,
FastAPI with Jinja templates and vendored HTMX for a local browser UI.
Model calls go through one adapter with per-step routing (Anthropic and
Google models), JSON-mode parsing with one retry, streaming for long
outputs, and an append-only run log. The test suite runs without network
access and strips provider keys from the environment, so a forgotten mock
fails instead of billing. Profiles, the database and the run log are kept
out of the public repository; everything committed uses invented examples.
