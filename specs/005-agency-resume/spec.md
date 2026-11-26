# Feature Specification: Agency Resume (a longer, ad-specific profile)

**Feature Branch**: `005-agency-resume`

**Created**: 2026-11-25

**Status**: Draft

**Input**: User description: "Agency resume: a resume with a longer,
ad-specific PROFILE (up to 250 words) for recruitment agents, who usually
prefer that to a cover letter. Default form: a copy of the master chosen for
the ad with only its PROFILE section replaced by a generated longer profile;
the master file itself is never modified; every other section is copied
unchanged. Also allowed: a custom (generated) resume with the longer profile.
The longer profile follows the existing rules for generated PROFILE prose.
The whole resume must stay within 3 pages; if it runs over, the profile is
shortened once, then it is a blocker. apply records what went beside what was
suggested. The cost is printed before spending. CLI and UI both offer it; a
cover letter is not generated unless asked. This bends D51, so a new decision
entry is needed. Out of scope: alternative visual styles (a two-column
sidebar layout was considered and deferred)."

All examples are invented (Constitution VI). The person is Sam Rivera from
`profile.example/`; the companies are Northwind Freight, Acme Logistics and
Contoso Health; the agency is Harbour Talent.

## Why

Recruitment agencies rarely read cover letters. A consultant reads the
resume, and above all its opening profile, to decide whether to put the
candidate forward and how to pitch them to the client. The masters' PROFILE
is two short paragraphs written for any ad of their kind. For an agency, a
profile of up to 250 words that answers this ad's main requirements does the
work a cover letter would do, in the one document the consultant will read.

The hand-written masters stay the source of the persuasive, approved text
(D51). Only the profile is generated, so the generated prose a reader sees is
one section, held to the rules already applied to generated PROFILE text.

## Clarifications

### Session 2026-11-25 (with the person, before the spec)

- Q: Longer profile length? → A: Up to 250 words, so the resume stays within
  3 pages.
- Q: Master copy or custom resume? → A: The master copy is the default form;
  a custom resume with the longer profile is also allowed.
- Q: Visual styles (a two-column sidebar)? → A: Not now. Deferred.
- Q: Does it replace the cover letter? → A: It is used instead of one for
  agency ads; a cover letter is still made only when asked, as today.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A master copy with a longer profile (Priority: P1)

For an ad, the person asks for the longer profile. JobAgent takes the master
it chose for the ad, writes a profile of up to 250 words for this ad from the
person's profile data, and saves a copy of the master with its PROFILE
section replaced. Everything else in the copy (name, headline, contact line,
highlights, skills, experience, earlier career, education) is the master's
text, unchanged. The master file itself is never written to.

**Why this priority**: this is the feature. It gives agencies what they ask
for while keeping the approved master text.

**Independent Test**: with an invented master and an invented Harbour Talent
ad for an "Engineering Manager" at Acme Logistics, and the model call mocked,
the output's PROFILE is the mocked text and every other paragraph is
identical to the master's; the master's bytes are unchanged.

**Acceptance Scenarios**:

1. **Given** an ad whose chosen master is the default, **When** the person
   asks for the longer profile, **Then** the expected cost is shown before any
   spend, and the result is a resume file named like other generated
   resumes, built from that master, with only PROFILE changed.
2. **Given** the chosen master is "not a target" for the ad, **When** the
   longer profile is asked for, **Then** it is refused before any spend,
   with the reason and how to name a master or ask for a custom resume.
3. **Given** the person names a different master for the ad, **When** the
   longer profile is made, **Then** that master is the base, and the record
   says it was chosen instead of the suggested one.
4. **Given** the generated profile is over 250 words, **When** it is
   checked, **Then** it is shortened once; still over is a blocker.
5. **Given** the finished resume measures over 3 pages, **When** it is
   checked, **Then** the profile is shortened once and re-measured; still
   over is a blocker and the file name carries `_NOT-READY` (D35).
6. **Given** page measurement is unavailable (no LibreOffice), **Then** the
   resume is still written and the run says the length was not measured, as
   for custom resumes today.

---

### User Story 2 - The longer profile is held to the profile's evidence (Priority: P1)

The longer profile is generated prose, so it gets the same guards as the
generated PROFILE on a custom resume: drawn only from `profile/`, each claim
citing its evidence and checked against it, no banned voice phrases, no
em-dash, no `never_in_documents` evidence, nothing excluded for the ad.

**Why this priority**: Hard rule 2 (no invented experience). A longer
profile is more room to drift, not less.

**Independent Test**: a mocked profile citing an entry marked
`never_in_documents`, one containing a banned phrase, and one with a figure
absent from the haystack are each caught by the same checks a custom
resume's PROFILE gets.

**Acceptance Scenarios**:

1. **Given** the claim check flags a sentence, **Then** that sentence is
   repaired alone and re-checked (repair before rewrite); a full rewrite of
   the profile only when repair fails; a surviving blocker gives `_NOT-READY`.
2. **Given** the claim check is turned off for the run, **Then** the run says
   so, as today.
3. **Given** a profile requirement the evidence cannot meet (a firm
   must-have), **Then** the profile does not claim it; the gap is reported as
   today (D37).

---

### User Story 3 - A custom resume with a longer profile (Priority: P2)

The person can ask for a custom (generated) resume whose PROFILE is the
longer profile instead of the usual two short paragraphs. Every other part
of the custom resume is made as today.

**Why this priority**: an option, for ads where no master fits well; the
master copy is the default.

**Independent Test**: with mocks, a custom resume asked for with the longer
profile has a PROFILE within 250 words and the rest of its sections as a
normal custom resume would.

**Acceptance Scenarios**:

1. **Given** a custom resume with the longer profile runs over 3 pages,
   **Then** the existing one reselection runs, told to shorten the PROFILE
   first; still over is a blocker. (Amended at planning, research R4: one
   shortening step, not a reselection followed by a second call.)

---

### User Story 4 - What went is recorded (Priority: P1)

Recording an application says whether the resume sent was a master as is, a
master with the longer profile (and which master), or custom, with or without
the longer profile, beside what JobAgent suggested.

**Why this priority**: D51 depends on knowing what went, or the variants can
never be compared.

**Independent Test**: `apply` on an invented Northwind Freight job whose
generated master-with-longer-profile file is named as sent records the
master id and the longer-profile marker; `status` shows it distinctly from
the plain master.

**Acceptance Scenarios**:

1. **Given** the person sends the generated master-with-longer-profile file,
   **When** the application is recorded, **Then** the record shows the master
   id and that the profile was the longer one.
2. **Given** applications recorded before this feature, **Then** they show
   as before; nothing is back-filled.
3. **Given** the UI's Pipeline form, **Then** the resume-sent choice includes
   the longer-profile variants beside the masters and custom.

---

### User Story 5 - Choosing it in the UI (Priority: P1)

The Generate page offers the resume kind as one choice: the master as is
(free, the default), the master with a longer profile, a custom resume, or a
custom resume with a longer profile. The cover letter stays a separate tick
box, off unless chosen. The confirmation page shows the expected cost.

**Why this priority**: the person uses the UI for generating; a CLI-only
option would go unused.

**Independent Test**: posting the Generate form with "master with longer
profile" and no cover letter, with mocks, produces the resume only, and the
confirmation page beforehand shows a cost line for the profile call and the
claim check.

**Acceptance Scenarios**:

1. **Given** the master as is is chosen, **Then** nothing is spent for the
   resume, as today.
2. **Given** the job's chosen master is "not a target", **Then** the master
   options are shown disabled with the reason; the custom options remain.

---

### Edge Cases

- The master's PROFILE section cannot be found in the master file (heading
  missing or renamed): refused before any spend, naming the master file and
  the heading looked for. The master is never guessed at.
- No masters registered: the master-based option is unavailable with the
  reason; the custom option with a longer profile still works.
- A longer-profile resume already exists for the job: the existing
  "refuse to clobber" rule applies, as for other generated documents.
- The person asks for the longer profile and a cover letter together: both
  are made; nothing forbids it.
- The longer profile is under the masters' own profile length: allowed;
  250 is a ceiling, not a target.
- The master's own PDF is not the file to send for this variant: the copy
  has a different PROFILE, so only the generated files are offered as sent.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The person MUST be able to ask, per job, for a resume whose
  PROFILE is a generated, ad-specific profile of at most 250 words.
- **FR-002**: By default, that resume MUST be a copy of the master chosen
  for the job (or the master the person names), with only the PROFILE
  section's paragraphs replaced; all other content and formatting MUST be the
  master's.
- **FR-003**: The master files MUST NOT be modified. A test MUST check the
  master's bytes before and after.
- **FR-004**: The person MUST be able to ask for a custom resume with the
  longer profile instead of the short one.
- **FR-005**: The longer profile MUST pass every check applied today to a
  generated resume PROFILE: drawn only from `profile/`, claims cited and
  checked, banned phrases, em-dash warning, `never_in_documents`, excluded
  evidence re-checked on output (D33).
- **FR-006**: A profile over 250 words, or a resume over 3 pages, MUST cause
  one shortening of the profile; still over MUST be a blocker marked
  `_NOT-READY` in the file name.
- **FR-007**: The expected cost MUST be printed (CLI) and shown (UI
  confirmation) before any paid call.
- **FR-008**: A cover letter MUST NOT be generated unless asked for.
- **FR-009**: Recording an application MUST record which master (or custom)
  and whether the longer profile was used, beside what was suggested.
- **FR-010**: The UI Generate page MUST offer the four resume kinds as one
  choice, with the master as is as the default; the Pipeline form MUST offer
  the longer-profile variants when recording what was sent.
- **FR-011**: The longer profile MUST be refused before any spend when the
  base master is "not a target" for the job and no master is named, or when
  the master's PROFILE section cannot be located.
- **FR-012**: `docs/decisions.md` MUST gain an entry recording that a master
  copy with a generated PROFILE is a permitted, recorded variant, and why it
  does not reopen D51 (the master text stays hand-written; only one section
  is generated, and what went is recorded).
- **FR-013**: `README.md` and `CLAUDE.md` MUST describe the option.

### Key Entities

- **Resume kind**: master as is, master with longer profile, custom, custom
  with longer profile. What is asked for at generate time and what is
  recorded at apply time.
- **Longer profile**: up to 250 words of generated prose for one job, with
  its citations, held beside the generated resume like other generated text.
- **Application record**: gains whether the resume sent had the longer
  profile, beside the existing master id / `custom` and the suggestion.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every master, a longer-profile copy differs from the master
  only in the PROFILE paragraphs (checked paragraph by paragraph in tests).
- **SC-002**: In tests, 0 longer profiles containing excluded or
  `never_in_documents` evidence, banned phrases or untraced figures reach a
  file without a warning or `_NOT-READY`.
- **SC-003**: On the person's three masters, a 250-word profile keeps each
  within 3 pages, measured once by hand after the build and recorded in the
  spec.
- **SC-004**: A longer-profile master copy costs less than a custom resume
  for the same job, as shown by `jobagent spend` after the first real runs.
- **SC-005**: Every application recorded after the feature shows which
  resume kind went.

## Assumptions

- The masters' PROFILE section is identifiable by its heading, as in today's
  masters; the replacement keeps the master's paragraph style for the new
  paragraphs.
- The longer profile is written as several short paragraphs (no bullets),
  matching the masters' PROFILE shape.
- The headline under the name stays the master's; only PROFILE changes.
- Room on the page (measured 2026-11-25): the person's masters each end
  about half way down page 3 with a PROFILE of under 100 words, so the
  extra 150-odd words (roughly a dozen lines) should fit. The 3-page check
  still runs every time; this is why it is expected to pass, not a reason
  to skip it.
- The copy is written as .docx only, like every generated resume; the
  person exports a PDF if one is wanted (amended at planning). The master's
  own PDF is not offered, since its PROFILE differs.
- `revise --resume` does not apply to a master copy: it would rebuild it as
  a custom resume. It refuses, and says to generate again with a context
  note (research R8).
- Choosing one resume kind in the UI replaces today's two tick boxes, so
  "master copy plus custom resume" takes two runs; copying a master is free
  (research R9).
- The longer profile is useful for direct-employer ads too; it is not
  restricted to agency ads, and no agency detection is built.
- The cheapest suitable model routes apply as configured; this spec does not
  choose models.

## Out of Scope

- Alternative visual styles, including a two-column sidebar layout
  (considered 2026-11-25, deferred).
- Changing the masters' text, or generating any other master section.
- Detecting whether an ad comes from an agency.
- Any change to how the cover letter is written.
