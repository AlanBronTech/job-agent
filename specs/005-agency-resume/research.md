# Research: Agency Resume

No open unknowns reached this phase: the spec had no clarification markers.
Each entry below is a design choice read from the code as it stands
(2026-11-25), with what else was weighed.

## R1. Writing the longer profile for a master copy

**Decision**: a new prompt, `prompts/generate_profile.md`, written through the
cover letter's machinery (`_write_cited`): the model returns paragraphs of
sentences, each citing profile ids, at most 250 words. The code checks
(`validate_prose` with `max_words=250`, `check_citations`,
`check_employers`, story reuse within the profile) and one rewrite on
blockers are the letter's, unchanged. `on_resume` is the master's own
highlight and bullet text, read from the master .docx with
`adapters/docx_reader.read_sections`, so the profile does not repeat the page
below it word for word (`_repeats_resume`).

**Rationale**: per-sentence citations are what the claim check and the
sentence repair already work on. Reusing them gets FR-005 for free and keeps
one path for "cited prose", not two.

**Alternatives**: asking the resume prompt for the profile alone (it is
built around selecting bullets, and its checks assume a whole selection);
free text with paragraph-level refs (coarser; the repair route works per
sentence).

## R2. A custom resume with the longer profile

**Decision**: one resume call, as today, with the PROFILE rule swapped. The
resume prompt's rule 7 ("PROFILE is two short paragraphs") becomes a
placeholder, `{profile_rule}`: the current text by default, the longer-profile
rule when asked. `_check_resume` adds a blocker when the PROFILE paragraphs
together exceed 250 words.

**Rationale**: a second call to write a profile the resume call already
writes would cost more for no gain (save money: standing priority). The
existing PROFILE checks (citations per paragraph, claim check, repair,
reuse caps, third person) then apply unchanged.

**Shared wording**: what an agency profile should do (answer the ad's main
requirements in order, say what kind of role and engagement is sought,
first person as the masters write) lives once, in
`prompts/long_profile_rules.md`, substituted into both prompts. Prompts stay
in `prompts/` (CLAUDE.md), not in code.

**Alternatives**: the R1 writer for both kinds (two calls for a custom
resume; rejected on cost).

## R3. Replacing PROFILE in a copy of the master

**Decision**: a new adapter function, `docx_writer.replace_profile(master,
target, paragraphs)`. It opens the master read-only, finds the paragraph
whose text is exactly `PROFILE`, takes the following paragraphs up to the
next heading (the `docx_reader._is_heading` rule: short, all caps, has a
letter, not a list item), and replaces them in the copy: the first body
paragraph's XML is cloned once per new paragraph, its first run keeps its
formatting and takes the text, extra runs are removed. Saved to `target`.
Refuses (`DocxError`) when the heading is missing, appears twice, or has no
body paragraph to clone.

**Rationale**: the masters (measured 2026-11-25) hold PROFILE as plain
`Normal` paragraphs of one run each between two bold all-caps headings, no
tables. Cloning keeps whatever formatting the person gave them; nothing is
re-derived from the CLAUDE.md typography table.

**Never edits the master**: the master is read; the copy is written to the
job folder. A test compares the master's bytes before and after (FR-003).

## R4. Staying within 3 pages

**Decision**:
- Master copy: render the copy with `adapters/pages.count_pages`. Over 3.0
  pages: rewrite the profile once, telling the model a word target computed
  from the overflow (`words now - overflow pages x 46 lines x 12 words -
  10`, both constants read from the masters: about 46 lines a page, 12-13
  words a full line). Re-measure; still over is a `resume length` blocker
  and `_NOT-READY`.
- Custom: the existing one reselection on length, with its feedback
  extended to name the PROFILE as the first thing to shorten. No second
  extra call. (The spec's US3 is amended to match: one shortening step, not
  two.)
- No LibreOffice: no measurement, said in the run, as today.

**Rationale**: the masters end about half way down page 3 with an 85-word
profile, so 250 words should fit; the check runs anyway.

## R5. Recording which resume went

**Decision**:
- Generate keeps, in the resume record it already writes
  (`ws.documents.keep_record(..., "resume", ...)`), `"base"` (a master id or
  `custom`) and `"long_profile"` (true/false).
- Schema v19 → v20: `applications.resume_long_profile INTEGER` (nullable;
  NULL for applications before this feature), via `_ADDED_COLUMNS`.
- `services/masters.resolve_sent` resolves the pair:
  - `--master em --long-profile` (CLI) or `em+profile` (UI): as named.
  - `--sent-as-generated`: the latest resume record's base and flag.
  - `--sent-resume <file>` identical to a master: that master, no long
    profile. Any other file: the latest resume record's base and flag when
    one exists for the job (the sent file is an edit of what was generated),
    else `custom` as today.
  - Nothing named: the suggested master, as today.
- `status` and the job page show `em+profile`, `custom+profile`.

**Rationale**: documents on disk are state (D19): what was generated is
read from the folder's record, not guessed from a file name.

## R6. File name

**Decision**: the master copy with the longer profile is named like every
generated resume, `<Person>_Resume_<Company>_<YYYYMM>.docx`, with
`_NOT-READY` on a blocker. The plain master is not also copied in that run.
Which base it came from is in the resume record and in `assessment.md`, not
in the name: the recruiter sees the file name.

## R7. Cost

**Decision**: the new prompt is a new label, `generate_profile`, on the
`generate` route (writing; not a cheap step). Until it has been run, the
estimate says "No measurement yet for generate_profile" beside the measured
part, as `costs.describe` already does for any unmeasured label. The claim
check is added as today. The custom-with-longer-profile kind uses the
measured `generate_resume` label.

## R8. `revise` on a master copy

**Decision**: `revise --resume` refuses when the job's latest resume record
has a master base, saying to generate again with a context note instead.
Revise rebuilds a custom resume from the previous draft, which would quietly
turn a master copy into a custom resume.

## R9. The UI choice

**Decision**: on the Generate panel, the two resume tick boxes (master,
custom) become one radio group: no resume, master as is (default when a
master is suggested), master with longer profile, custom, custom with longer
profile; the master drop-down stays and applies to both master options. A
master option is disabled, with the reason, when no master fits the job and
none is picked. The cover letter tick box and answers stay as they are, but
the cover letter is no longer ticked by default when a longer-profile kind is
chosen (FR-008; agencies are the case). The Pipeline form's "Master resume
sent" list gains "<label> with longer profile" for each master and "A custom
resume with longer profile".

**Changed behaviour**: today both boxes can be ticked, copying the master and
generating a custom resume in one run. With one choice, that takes two runs;
copying a master is free and never clashes, so the second run costs nothing
extra.

## R10. Decision record

**Decision**: D53 in `docs/decisions.md`: a master copy with a generated
PROFILE is a permitted, recorded variant. It does not reopen D51: the masters
stay hand-written and unedited, one section is generated and checked as any
generated PROFILE is, and what went is recorded beside what was suggested so
the variants can be compared.
