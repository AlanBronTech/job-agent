# Final review — pass/fail rubric

For the Claude.ai Job Hunting Project (REVIEW-2026-10-18, task 9). Project
knowledge: `profile/*.yaml`, `profile/voice.md` and this file. Paste in the
job ad and the generated resume and letter.

## What to return

A table, nothing else: one row per item, **PASS** or **FAIL**, and for a FAIL
the offending sentence quoted exactly and the profile entry it contradicts or
lacks. No rewritten sentences, no suggested wording, no summary. The fix is
made by `jobagent revise <id> --resume|--cover --note "…"`, never by hand, so
that the correction is recorded and can recur into the profile or voice rules.

| # | Item | Result | Sentence | Why |
|---|------|--------|----------|-----|

## The items

1. **Every claim traces to the profile.** A number, scope, title, employer,
   technology, outcome, mechanism or cause that no entry in `profile/` states
   is a FAIL, however plausible. Compression is fine; addition is not.
2. **The ad's top five requirements are addressed** — each by a highlight, a
   role bullet or a letter sentence citing real evidence. A skills keyword
   alone does not count. Name any that are not.
3. **Nothing contradicts a `not_true` line** of any story in
   `profile/stories.yaml`, stated or implied.
4. **Departure reasons match** the agreed explanations in `stories.yaml`
   word for word in substance. No new reason, no extra detail.
5. **No volunteered gap outside a firm must-have.** A gap named in the letter
   must match the firm part of a must-have (before "e.g.", "ideally",
   "a plus"). A gap against a nice-to-have is a FAIL.
6. **No claim about order** — "my first…", "for the first time", "never
   before". *(Also a coded blocker.)*
7. **One salutation and one sign-off** in the letter, and the letter body
   under its word limit. *(Also coded.)*
8. **Dates follow the standing decision** — role dates as years, founder
   ventures with their years, no computed career length ("25 years",
   "two decades", "since 2001").

## How an item leaves this list

Once an item has failed twice across applications, it becomes a coded check
in `core/validation.py` (or the claim check's prompt) with a test, and is
marked *(also coded)* here. An item stays on the rubric while the documents
can still be edited outside the tool, because hand edits bypass the code.
