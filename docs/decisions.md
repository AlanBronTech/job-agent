# Decisions — job-agent

Why each rule in `CLAUDE.md` exists: what happened, what it cost, and what
was decided. Moved out of `CLAUDE.md` on 2026-10-23 (REVIEW-2026-10-18,
task 11) so that file holds only the rules. Numbers are stable: `CLAUDE.md`
cites them as D1, D2, … Add new decisions at the end; never renumber.

---

## Document format

### D1. A closed venture is record; an ongoing one is evidence

DataLlama runs
2018–present and appears as a CAREER HIGHLIGHT and, since 2026-10-21 (Alan),
as one part-time line under Bron Consulting in EXPERIENCE — never in
EARLIER CAREER. Its `note_for_scorer` says never
to present it as full-time work or use it to fill a gap in the employment
timeline, and a dated line among closed ventures does neither job. The
renderer blocks an ongoing venture from that section and points at the
highlights.

---

## LLM usage

### D2. Stream anything with a long output

`prep` died three times at ~180s with
the API reachable and a small call answering in two seconds: a long
generation on a non-streamed connection, with the socket closing while the
model was still thinking. Connection errors and timeouts are transient and
are retried; a 401 is not.

### D3. A stream dies outside the SDK's exception hierarchy

`except
anthropic.APIError` does not catch `httpx.ReadTimeout` raised out of the
iteration while the model is still generating, so the retry wrapper built for
precisely that never saw it and a `jd add` died on an unhandled traceback — a
plain re-run succeeded immediately. Transport failures are now classified in
`_complete_with_retry`, the provider-agnostic loop, as well as in each
client: a guarantee that depends on every future client remembering is not a
guarantee. Match on `httpx.TransportError` in the MRO by name rather than
importing httpx, which is the SDKs' dependency and not this project's.

### D4. A failed call is logged, or its cost disappears

The run log was written
on success only, so a timed-out parse left no record at all while still
being billed for what it generated — `spend` was silently low and "no
record" was indistinguishable from "never happened". Every failed attempt now
appends `outcome: "error"`, including attempts a retry later rescues, because
those were billed too. Token counts are null and honestly so: the failure
happens inside the provider call, before any usage comes back. `price_unknown`
stays false — the price table is fine, there is simply nothing to price, and
conflating the two would send the next reader to `prices.yaml` for no reason.
Anything reading the log treats a missing `outcome` as success, because every
record predating the field is one.

### D5. Most of a call's cost is its hidden reasoning, so effort is set per call type

(2026-10-14). A resume selection wrote 15-30k output tokens for a
~1k-token answer, and output costs five times input. `DEFAULT_EFFORT` in
`adapters/llm.py`: low for parse, classify and the screen; medium for score,
generate, prep and review. Sent as `output_config.effort` only to Claude
models known to accept it (`_EFFORT_MODELS`), as a thinking budget to
Gemini, and to nothing else. Gemini's `thoughts_token_count` is added to
output tokens: leaving it out made every Gemini call look cheaper than it was.

### D6. Output ceilings are sized for the reasoning, not the answer

Four real
calls were lost at their ceilings in one week (resume 16k, review 4k,
classify 1k, letters 8k). Resume and letters now 32k, checks 16k, classify 8k.

### D7. Cheap steps get cheap models by default

(`CHEAP_DEFAULTS`): parse and
classify on Gemini's free tier (they see only the ad), the screen on Haiku
(it sees a profile summary, and the free tier's terms allow training on
input). A spent free tier hands over to `LLM_FALLBACK` (Haiku) through
`FallbackClient`. A route configured in `.env` or on the Settings page always
wins over these defaults.

### D8. Settings live beside the database

(`services/settings.py`,
`settings.json`): per-step route and effort, and the two checks. Applied by
`get_config()` and by the UI on every request, so the CLI and the browser
agree and a change needs no restart.

---

## Design invariants

### D9. Hard filters are computed in Python; judgment is asked of the model

Salary floor, employment type, on-site geography, closed ads — arithmetic
and set membership over decisions Alan has already made. A breach overrides
the model's verdict outright. `ConstraintStatus` has three values because
"the ad does not say" is not "the ad is fine".

### D10. For the resume the model returns references, not prose

It picks roles,
bullets and ordering by id; the text is copied verbatim from `profile/`. A
model that cannot type a bullet cannot embellish one. It writes prose only
for the tagline, the PROFILE paragraphs and the cover letter — all validated.

### D11. What a highlight may cite is wider than what a bullet may copy

The
catalogue holds role bullets keyed `id.index` because its text is copied
verbatim into EXPERIENCE; `build_citable` also accepts entry ids, including
`earlier_career`, because a CAREER HIGHLIGHT composes prose and cites the
evidence behind it. Collapsing the two would let a thirty-year-old undated
summary render inside a dated role block. Keeping them equal in the other
direction blocked `mlc_nab` — a real, correct citation of Alan's
superannuation work, on a superannuation ad. A checker narrower than the
prompt reports the model's best answer as a fabrication.

### D12. `core/validation.py` enforces the hard rules mechanically

, not by asking
a prompt nicely: every number traced to the profile, the banned list parsed
out of `voice.md` at runtime, explicit patterns for the age-signal policy.

### D13. In `profile/`, `text` is rendered and `note_for_scorer` is not

A
cross-reference left in a bullet's `text` was copied onto a real resume.

### D14. The generator never sees `note_for_scorer`; a writing rule goes in `note_for_writer`

Scorer notes are kept from the model that writes
because they hold facts never to be published. So a rule about *how to
write* parked there bound only the model that does not write: the DataLlama
attribution rule sat in `note_for_scorer` for a week and a highlight broke
it. `note_for_writer` is printed into the generator's catalogue under its
entry or bullet, and under each story the letter and answers prompts are
given, and is excluded from the number haystack. Rules only — never a
fact the writer has to be kept from. Brightside's `sector: insurance` was
the same shape of bug the other way round: a field the writer *did* see,
contradicting a note it did not.

### D15. The number haystack is built by exclusion, and the exclusions are the point

`_profile_numbers` walks the loaded model, so a field added to the
schema is licensed without editing the validator — the hand-written list it
replaced had drifted and was blocking the agreed salary expectation, which
`generate.py` hands the model under "use these words". But the obvious
version of that fix, scanning every string, inverts the rule it enforces:
the DataLlama user count and the HDD equity split live only in
`note_for_scorer`, under an instruction never to publish them, and a
haystack covering them would have the validator bless the one figure the
profile forbids. `voice.md` is excluded for the same shape of reason — it
quotes "25 years" and "20+ years" as examples of *banned* age signals and
states Alan's age, so scanning the rules file licensed all three. Excluded:
`voice`, `note_for_scorer`, `phone`, `*_rationale`, and anything marked
`visibility: scorer_only`.

### D16. The number check is unit-blind, and knows it

The haystack holds `180`,
not `$180K`, so "I led 180 engineers" validates against "MVP in 18 months on
$180K". It catches the fabricated metric, not the transplanted one. Do not
describe it as stronger than that.

### D17. The eval harness grades "was this worth applying to", never "was he hired"

Alan was offered the Easy Signs job and applying was still the
wrong call — the commute that ended it is an absolute filter in his profile.
Grading on hiring outcomes would tune away the constraint that mattered.

### D18. Company history is reported, never scored

`core/history.py` reads the
store and says "you have been here before, and here is how it went". It does
not reach `check_constraints` and does not move a verdict. Nuix screened him
out on JD 14 and posted a different role in the same team the next day; the
fix for that is a line he reads, not a filter inferred from one rejection.
A company only becomes an absolute skip when Alan says so in `assets.yaml`,
the way every other hard filter got there. The warning cannot fire before
the ad is parsed — the company name is what the parser reads out of it — so
it costs the $0.03 parse and saves the $0.11 score and the $0.13 generate.

### D19. The store is not the record of what has been done

`generate` rewrote
the Colonial First State folder three days after it was written, in place,
because the database had no application row and the agent read that as "not
yet worked on" without looking in `OUTPUT_DIR`. Documents on disk are state.
Ebury and Bright & Duggan had also been generated and were about to be read
the same way. A guard now refuses before spending, and any check of "has this
been done" has to look where the artefacts actually land, not only in SQLite.

### D20. A figure nobody re-checked is worse than no figure

The price table was
hardcoded and carried Sonnet 4.6's rate for Sonnet 5, so every logged cost
was overstated by a third and the README quoted double the real per-
application cost. Prices now live in `prices.yaml` with a `checked_on:` date
and the pages they were read off; a model absent from it has *no* price, and
that is written into the run log as `price_unknown` and printed once at the
end of the command. A silent `None` in a spend log is how two Gemini calls
cost nothing at all for a week.

### D21. The run log records what a call was for, not just what it cost

Every
record carries `command`, `jd_id`, `source` (`cli`, `ui` or `eval`) and
`run_id`. Without `source`, a month of eval runs is indistinguishable from a
month of applications; `ui` is kept apart from `cli` so the log can show
whether the UI is actually used. `run_id` exists because `parse_jd` runs before the JD has an
id — `jd add` parses, then stores — so the command appends one attribution
record once the id is known and `spend` joins on it. The call records are
never rewritten; the log is append-only.

### D22. A record that cannot express what happened will be read as evidence that it did not

`ApplicationStatus` had two terminal values, neither able to say
"reached an interview, then ended". Closing four such rows forced them to
`rejected_screen` or `applied_no_reply`, and the next analysis read the
flattening as fact: it reported that LinkedIn applications had produced no
human contact when one of them was the only interview of the batch. The
conclusion drawn was about which channel to trust. Before inferring anything
from a status field, ask what the enum is incapable of saying.

### D23. An omission is invisible in a finished document

`generate` prints every
profile entry the model used nowhere, because the same entry was dropped from
two resumes and both times the only way to notice was to already know it
should have been there — the second one was flagged in writing and sent
unedited anyway. It is a list, not a warning, and it is printed on clean runs
too: which evidence an ad rewards is the model's judgement and usually it is
right, so a validator cannot make the call and a warning that fired on every
run would be ignored within a week. Entry granularity, not bullet — "bullet 4
was not used" is noise on every run. An ongoing venture sorts first, because a
CAREER HIGHLIGHT is its only route onto the page and missing it there means
the entry is absent entirely. The list can name an entry whose substance
appears elsewhere under a different id; that is the cost of reporting rather
than enforcing, and it is the right cost.

### D24. A fix at the top of a document does not cover the bottom

The prompt says
to return the letter body only, because the renderer writes the salutation,
the closing and the name. Two early letters were addressed twice and
`strip_letter_salutation` was added to drop what the model sent anyway. The
same model then signed off as well, so a letter ended "Regards, Alan Bron"
twice and went to an employer that way — nobody checks the last line of a
document they have already read. Both ends are stripped in `core/` now, and
only a *bare* closing matches: one letter's final sentence is "Thanks for
contacting me." and a looser rule would delete it. The first version of the
strip walked up one line at a time and stopped at whatever name was signed,
so an unfamiliar spelling left the closing in place — a test caught that
before it shipped. **The length rule was already enforced and needed nothing:
`_check_length` is a blocker at 350 words and every letter's body passes it.
Measure the body, not the rendered page — counting the name, contact line,
date, salutation and closing puts a compliant letter over the limit and
invents a defect that is not there.**

### D25. A rule that only forbids gets satisfied by omission — and check the rule was delivered before crediting it with anything

A generated CAREER
HIGHLIGHT stated the DataLlama deployment and dropped Alan's authorship,
which implied ownership more strongly than the sentence the note forbade.
That was read as the model obeying a prohibition by omission; strengthening
the note to *require* his contribution, and the model then dropping the
entry, was read as the requirement backfiring. Both readings were wrong:
the whole note lived in `note_for_scorer`, which the generator never sees,
so neither run was a response to it. The highlight simply paraphrased the
bullet it was shown. The principle still holds — a constraint changes what
gets written, so check what it displaced, not only that the banned thing is
absent — but first confirm the model that writes was ever shown it.

### D26. Deleting an ad is not the same as deleting a decision

`jd delete` exists
for a genuine duplicate — a recruiter thread ingested twice as JD 46 and 47 —
and refuses when an application row exists, because foreign keys cascade and
that row is the pipeline record `eval` is built from. It names the assessments
it will take with it before it takes them, and it never touches OUTPUT_DIR:
46 and 47 both resolved to the *same* folder, so deleting documents alongside
the row would have destroyed the resume that was actually sent. A skip is a
result worth keeping, not rubbish to tidy away.

### D27. When a record has forked, amend the one holding the application

Do not
move the application to the record with the better text. Repointing it swaps
the ad out from under the application with no marker, and the fuller text
usually arrived *after* the decision to apply — so `eval`, which builds from
the `applications` table, would grade that decision against text that was not
observable when it was made. `jd amend` keeps `superseded_text`, sets
`amended_at`, leaves `ingested_at` alone and flags the stale assessment.

### D28. An ad is not immutable

A recruiter answers a question in chat, or the
real job description arrives a week after the teaser — both happened inside
three days, and each forked one role across two records, the second holding
the better text and the first holding the application and every note.
`jd amend` re-parses in place; `--append` is for a conversation that grew.
The superseded text is kept, `ingested_at` is not touched, and any assessment
that predates the amendment is reported rather than silently trusted.

### D29. A public repo is audited, not trusted

"Public on GitHub" on a resume is
an invitation to look. Before making that claim, check the *history*, not the
working tree — at blob level, for salary figures, candid judgments about
named employers, and anything the profile marks never-publish. Two of the
three exposures found on 2026-09-20 had been introduced by tidying that only
touched the current version.

### D30. An average of logged costs inherits every pricing error ever logged

The
first cost estimate averaged `cost_usd` from `runs.jsonl` and put `score` at
$0.15 against a true $0.11, because every record before 2026-09-08 was
written at Sonnet 4.6's rate. The question an estimate answers is what the
next call will cost, so `expected_cost` prices past calls' tokens at today's
`prices.yaml`. One unpriced sample makes the estimate "unknown", never a
partial sum and never $0.00.

### D31. A guard that moves things runs after every refusal, not before

The first
`--supersede` renamed the application folder before the profile and model
checks, so a run refused a moment later left the documents renamed for
nothing. The move now happens last — after every refusal, before the first
model call — so a refused run touches nothing and a failed move spends
nothing.

### D32. The six-month rule is a refusal before spending, not a hard filter

Hard
filters run inside scoring, after the model is paid; a rule whose purpose is
to save the $0.11 and the $0.14 has to fire before either. A reposted ad was
scored and had documents generated before the employer's portal showed the
same requisition applied for five months earlier. Same job means the same
requisition number or URL; same company and title where the numbers do not
settle it is *possibly* the same job, and Alan answers. That case had its
number only on the earlier application (the receipt email), not in the
repost: "neither side has a number" would have missed it. Only 2 of 58
stored ads carry a number at all, so the title question does most of the
work. The rule only sees applications it knows about, hence `outside add`.

### D33. Excluded evidence is removed from the writer's input, then re-checked on output

(spec 003). A rule that only forbids gets satisfied by rephrasing —
a technology the profile rules out went into a letter that way. `core/roles.excluded_ids` names what an
ad's role kind excludes (a story takes its linked bullets with it), the
catalogue and story list skip those ids without renumbering the rest, and a
citation of one anyway is a blocker. The letter and answers return cited
sentences for the same reason: a citation can be counted, prose cannot.

### D34. A paid check never loses the documents

The claim check and the review
return `NotChecked` / `NotReviewed` on any failure; the documents are still
written and are never called ready.

### D35. A blocker is a stop, not a note

(2026-10-15). "Regulated banking
contract" was flagged as a blocker in the report and sent anyway, because
the file was written regardless. Now the resume is selected again once with
the failures named (as the letter always was), a claim-check mismatch has
the letter written once more, and a blocker that survives puts
`_NOT-READY` in the file name. A name cannot be skimmed past.

### D36. Checking reuse afterwards only works if failing forces a rewrite

The
reuse caps existed and both real resumes still repeated themselves. A
highlight may not restate a bullet printed below it (word overlap ≥ 0.7);
the letter is told what the resume says and a copied line blocks; an
unlinked bullet counts as its own story. With blockers now forcing a
rewrite, these bind.

### D37. Admit a gap only in a real must-have

A letter volunteered a Kubernetes
gap the ad listed as "e.g. Kubernetes". `must_have_gaps` keeps only gaps
matching the firm part of a must-have (before "e.g.", "ideally", "a plus").

### D38. Claims about order are unverifiable and get contradicted

A letter
called a role his first in leadership while EARLIER CAREER listed three
earlier team-lead roles. "My first …", "for the first time" and "never
before" are blockers.

### D39. The first-pass screen is advice and must stay cautious

Measured on 65
labelled cases (`eval screen`): 0 of 11 worthwhile jobs skipped, 9 of 40
scorer skips caught. Its value is the zero, not the nine; tune it towards
bolder only with that number re-measured.

### D40. A guard that fires when nothing is at risk stops being a guard

The
overwrite check names only the files that run would write, so an
`interview-prep.md` from a `prep` run never triggers it. The moment
`--overwrite` becomes reflexive it protects nothing.

### D41. Check a variable was observable at decision time before it informs anything

Applicant counts read off a page saved weeks later are target
leakage; they were not there when he decided.

### D42. Read the prompt before blaming the model

Two sessions were spent
attributing over-split requirements to Gemini, then to Claude. The v1 prompt
instructed it.

### D43. A weaker model is a prompt-underspecification detector

Running the eval
set through free-tier Gemini found that the v2 scoring prompt never stated
the 0-100 range. Claude had been filling it in from convention.

### D44. A comparison across two models is not a prompt regression

`eval diff`
took the two newest assessments per case whatever produced them, so a budget
run sitting between two real ones read as a fifty-point prompt change. It
now takes `--model`, names what it compared, and warns on a mixed set.
Anything that reads a run history has to say which model it read.

### D45. One run of a boundary case is a coin flip, not a measurement

Case 10
has gone skip / apply / apply / skip / apply across five Sonnet runs, a
20-point band straddling the threshold, with the two `skip`s falling either
side of a prompt change that had nothing to do with it. Grading a boundary
case once and attributing the result to the last edit is how a prompt gets
blamed for noise. Repeat the case before believing the delta.

---

## Testing

### D46. The eval set is a regression detector, not a measurement of scorer quality

Its job is to catch a prompt edit that moves verdicts beyond the
known noise floor. It cannot tell you whether the scorer is good, and saying
it can is the kind of claim this project exists to avoid making: at 14 cases
and 4 errors the confidence interval on accuracy runs roughly 45–90%, which
does not distinguish a good scorer from a mediocre one and will not at the
rate applications accumulate. Report it as "no regression", never as "71%
accurate".

### D47. Eval standing, 2026-09-20, and why not to tune on it

Current standing, 2026-09-20: the scorer agrees on **26 of 31** labelled
cases, with **3 false negatives and, for the first time, 2 false positives**.
Separation between the cases worth applying to and the rest is 18 points of
mean score. Accuracy fell from 89% when the September labels were added —
that is not a regression, it is what happens when hard cases replace easy
agreements. **The separation is the number to watch, not the percentage.**

One of those false positives matters more than a number. Pet Circle scored
skip at 32/30; the verdict moved to apply only after `profile/roles.yaml` was
corrected to name the offshore teams, and Alan then judged the day not worth
it. **Adding true evidence to the profile moved a verdict the wrong way.**
The other is a false positive on *process*, not fit: the role matched, and
the day was spent without confirming an office location that could have
breached an absolute filter. The eval grades the day, not the scorer, and
here the two come apart.

Most labels are still `not_applied` cases where Alan agreed with a skip he
had just read. That is not independent evidence. **Do not tune on this.**
`generate --force` records each time he overrules the scorer, and
`eval report` reports who was right; the threshold moves on that evidence.

That 10 is itself **±1 between runs of the same prompt**. Measured on
2026-09-01: same-prompt score movement averages 6.3 points, and the cases
that sit on the apply/skip boundary change verdict from one run to the next
without anything changing. Grade a prompt edit with `eval diff --model`, and
re-run a case that flipped before treating the flip as real.

---

## History

### D48. The master resume's format was measured, not chosen

Source of truth: `~/Documents/AlanBronResumeMaster102026.docx`, revised Oct 2026.
Every value in `CLAUDE.md`'s Document format section was measured from the master, not chosen, and re-measured on
2026-09-20 when the September revision superseded the August one — all of them
held, because that revision changed content rather than format. The October
revision (2026-10-21) was made from the September file by editing text inside
its existing paragraphs and copying one bullet paragraph for two new ones, so
every format value is unchanged; only content changed (corrected claims and two
new bullets under the current role). The earlier
version of that section was wrong on all six values — if a future spec and the
master disagree, the master wins, and that section gets corrected.

### D49. The public history was purged on 2026-09-20

The repo was re-verified after the purge.
`evals/cases.yaml` had been committed on 2026-09-01 and deleted the same day —
deleting a file does not remove it from history, and fourteen named
applications with candid judgments stayed reachable for nineteen days. Two more
figures went with it: a salary expectation left in a test fixture, and a
deployment user count the profile marks NEVER PUBLISH that had been quoted
verbatim in a public test docstring to explain why it must never be published.
A mirror of the pre-purge state is kept locally and must stay off any public
host.

### D50. The cost table was double until 2026-09-08

The per-command costs once quoted in `CLAUDE.md` (now in the README) were
measured — the mean per call over 183 real calls, from `jobagent spend` — not
estimates. They were roughly double until 2026-09-08, because the hardcoded
price table costed Sonnet 5 at Sonnet 4.6's rate and the estimates on top of
that were conservative. They also predate the cheap-model defaults and
per-step effort of 2026-10-14. Re-measure with `jobagent spend` before quoting
any of them; that is the whole reason it exists.
