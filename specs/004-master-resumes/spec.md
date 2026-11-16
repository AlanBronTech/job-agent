# Feature Specification: Master Resumes

**Feature Branch**: `resume-masters` (built), `004-master-resumes` (this spec)

**Created**: 2026-11-16, **as built**: written after the code merged locally
(`eccd86b`). The feature skipped `/speckit-specify` (Constitution,
Development Workflow); this spec records what was asked, decided and built,
and carries the one task still open.

**Status**: Implemented except T017-T022 (custom resume layout, em-dash check)

**Input**: User description: "Stop composing a new resume for every job.
Keep a small set of hand-approved master resumes, have JobAgent pick the best
one for each ad, and record which one it sent. Keep the cover-letter step as
it is. Do not build the resume documents; JobAgent only needs their file
paths and which roles each one is for. Keep the option of a custom resume."

All examples are invented (Constitution VI). The person is Sam Rivera from
`profile.example/`; the companies are Northwind Freight, Acme Logistics,
Contoso Health and Fabrikam Energy.

## Clarifications

### Session 2026-11-14 (analysis, before any code)

- Q: How many masters? → A: Three: Engineering Manager (the default and the
  public one), AI adoption lead, and a contract senior engineer. No master for
  delivery/PM, for a domain, or for Head-of roles: the application record did
  not support one, and a resume cannot write around a missing must-have.
- Q: What changes between masters? → A: Headline, PROFILE, the order of
  CAREER HIGHLIGHTS and of CORE SKILLS. EXPERIENCE, EARLIER CAREER and
  EDUCATION stay the same.

### Session 2026-11-16 (during the build)

- Q: Is the contract master for every contract? → A: For contract and
  fixed-term roles only, and not for every one: a management or delivery role
  on a contract takes the Engineering Manager master, because the contract
  master's headline says senior engineer.
- Q: Permanent hands-on engineering roles? → A: Not a target. The person
  applies for those on contract only. Permanent Team Lead is undecided and
  takes the default meanwhile.
- Q: Who picks the master: a model or code? → A: Code. The title, the work
  type and the stored role kind already decide it, the rule is short enough
  to read, and a free choice can be shown everywhere without a cost line.
- Q: An override before applying, stored per ad? → A: No. What matters is
  what went, so the choice is made when the application is recorded.
- Q: `apply` with no resume named? → A: The CLI records the suggested master,
  keeps its file as the resume sent, and says so. The UI form assumes nothing
  (REVIEW-2026-10-16 D9): nothing is recorded unless chosen or uploaded.
- Q: Where do the masters live? → A: In `profile/resumes/` (gitignored with
  the profile), as .docx and .pdf without version suffixes; a retired version
  moves to `old-resumes/` with its retirement date in the name.
- Q: A custom resume? → A: Always available (`generate --resume`), recorded as
  `custom`.
- Q: The story the person never wants written down? → A: A
  `never_in_documents` flag that no ad wording or role kind can open.

### Session 2026-11-16 (T017, before the code)

- Q: Which Core Skills order does a custom resume use? → A: The order of the
  master that would be chosen for the ad. Without masters, the role-kind
  order as before.
- Q: The profile's skill categories differ from the masters'. → A: Replace
  the profile's skills with the masters' categories, text copied from the
  approved master; the category that is in neither (embedded and hardware)
  goes. One source of truth.
- Q: Em-dashes inside profile text? → A: A free check flags any em-dash in a
  generated resume or letter, as a warning (no paid repair); the profile text
  is reworded by hand.

## Why

Generated resumes were honest but not persuasive, and each one led with
something different: one opened as a technical lead, the next as an AI
enablement lead, the next as an engineering manager. A reader who saw two
would not know what the candidate is. Hand-written masters fix the
persuasion, and picking one keeps the message consistent. The pipeline still
has to say which went, or the masters can never be compared.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The masters are known to JobAgent (Priority: P1)

The person lists the masters in `profile/resumes/masters.yaml`: an id, a
label, the .docx and optional .pdf, what each is for (role kinds, work types)
and which one is the default. `jobagent profile validate` lists them and
refuses a broken list.

**Independent Test**: an invented registry with three masters loads, with
absolute paths, in file order; a missing file, two defaults, a duplicate id
or an unknown role kind is refused with a message naming the problem.

**Acceptance Scenarios**:

1. **Given** no `masters.yaml`, **When** anything runs, **Then** behaviour is
   exactly as before: no masters, no new lines anywhere.
2. **Given** a registry whose AI master's .docx is missing, **When**
   `profile validate` runs, **Then** it exits non-zero naming the file.

---

### User Story 2 - Each ad gets a master, or "not a target" (Priority: P1)

For each ad, JobAgent picks a master, free and in code, with a one-line
reason.

**Independent Test**: titles and work types modelled on real ad shapes, with
invented employers, each map to the expected master.

**Acceptance Scenarios** (rules in order):

1. **Given** an AI-adoption role ("AI Enablement Lead", classified
   `ai_enablement`), **Then** the AI master, unless the title is plainly
   hands-on. An unclassified ad whose title names AI and adoption or
   enablement counts as AI adoption.
2. **Given** a hands-on title (engineer, developer, architect, also "Lead AI
   Engineer"): on a contract or fixed term, the contract master; permanent,
   not a target; terms not stated, not a target until they are known.
3. **Given** a delivery or project role (by title, or classified
   `delivery_focused` when the title is not a team lead), **Then** the default.
4. **Given** a manager title, contract or not, **Then** the default.
5. **Given** any other contract, **Then** the contract master.
6. **Otherwise** the default, including Team Lead ("Engineering Team Lead",
   "Technical Team Lead"), whose reason says Team Lead is undecided.

---

### User Story 3 - The choice is shown wherever the assessment is (Priority: P1)

`score`, `score --last`, the `assessment.md` kept with generated documents,
and the job's page in the UI show the master, why, and the file to send (the
PDF when there is one), or "Not a target" with the reason, and how to ask for
a custom resume instead.

**Independent Test**: `score --last` for an invented Acme Logistics
"Engineering Manager" prints a resume row naming the default master's PDF and
`jobagent generate <id> --resume`.

---

### User Story 4 - What went is recorded (Priority: P1)

Recording an application records which resume went (a master's id or
`custom`) and what JobAgent suggested, so an override can be told from
agreement.

**Acceptance Scenarios**:

1. **Given** `apply 3` with nothing named, **Then** the suggested master is
   recorded, its file kept under `sent/` as the resume sent, and the command
   says so and how to correct it.
2. **Given** `apply 3 --master ai` where the default was suggested, **Then**
   `ai` is recorded with the suggestion beside it, and the command says
   "instead of the suggested …".
3. **Given** `--sent-resume` naming a byte-identical copy of a master,
   **Then** that master; any other file, or `--sent-as-generated`, `custom`.
4. **Given** `--master executive` (not in the list), **Then** refused before
   anything is written, listing the known ids.
5. **Given** `apply` again with nothing named, **Then** an existing record is
   left alone and no second copy is kept.
6. **Given** the UI's Pipeline form, **Then** a "Master resume sent" choice
   lists the masters with the suggested one marked, plus "A custom resume";
   choosing a master keeps its file as sent when none is uploaded; choosing
   nothing records nothing.
7. **Given** `status`, **Then** a `resume` column shows the id, `custom`, or
   `—` for applications recorded before this feature.

---

### User Story 5 - Some evidence is never written down (Priority: P2)

A story or bullet marked `never_in_documents` is excluded from every resume,
cover letter and application answer, whatever the ad says and whether or not
it has a role kind. Interview prep still sees it.

**Independent Test**: an invented story gated on "performance management"
and marked `never_in_documents` stays excluded, with its linked bullet, for
an ad that names that phrase and has no role kind.

---

### User Story 6 - A custom resume looks like the masters (Priority: P2, **open**)

A generated resume uses the masters' layout: highlight labels followed by a
colon, no em-dash anywhere, and CORE SKILLS as six "Label: list" lines. Today
the renderer still writes em-dash labels and a 4×2 skills table (T017).

### User Story 7 - No em-dash reaches a document unseen (Priority: P2)

Any em-dash in a generated resume, letter or answer is reported, naming the
text, so it can be reworded. Free; a warning, not a blocker.

### Edge Cases

- The registry exists but lists no masters: an error, not "no masters".
- The registry is broken when a page or score is shown: the choice line says
  the list is invalid and why; the score or page is still shown.
- A sent file that does not exist: the existing sent check refuses it.
- A master without a PDF: its .docx is the file to send.
- An ad scored before role kinds existed: the title and work type still
  decide; AI adoption is read from the title.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The registry is optional; without it nothing changes.
- **FR-002**: Exactly one master is the default; every file it names exists.
- **FR-003**: Selection is computed in code from title, seniority, work type
  and stored role kind. No model call.
- **FR-004**: Every choice carries a reason a person can read.
- **FR-005**: `score`, `score --last`, `assessment.md` and the job's page
  show the choice and the custom-resume route.
- **FR-006**: The application stores `resume_master` and `resume_suggested`
  (schema v19); older rows read None.
- **FR-007**: `apply --master <id|custom>`; an unknown id is refused before
  any write.
- **FR-008**: The CLI assumes the suggestion when nothing is named, and says
  so; the UI assumes nothing.
- **FR-009**: A byte-identical copy of a master is that master.
- **FR-010**: JobAgent never writes or edits a master.
- **FR-011**: `never_in_documents` on stories and bullets excludes them from
  all written documents; interview prep is unaffected.
- **FR-012**: A custom resume renders in the masters' layout: highlight and
  earlier-career labels end in a colon, CORE SKILLS is one bold-label line
  per category, education reads "Name (Issuer)" and "Qualification,
  Institution".
- **FR-013**: A custom resume lists the skill categories in the chosen
  master's `skills_order`; each master's order names only categories the
  profile has.
- **FR-014**: Every em-dash in generated text is reported as a warning.

### Key Entities

- **Master** (`MasterEntry` in the file, `MasterResume` resolved): id, label,
  docx, pdf?, default, role_kinds, work_types, use_for, not_for?.
- **MasterChoice**: master?, not_a_target, reason.
- **SentResume** (service result on apply): master, suggested, file?,
  assumed; `overrode` when a named master differs from the suggestion.

## Success Criteria *(mandatory)*

- **SC-001**: Every selection rule has a test with an invented example; the
  rule run read-only over the real store matches the analysis (not
  committed: real data).
- **SC-002**: A master is recorded for each application made after the
  feature, and `status` shows it.
- **SC-003**: After about 20 sends per master, the record can say how each
  fared and how often the suggestion was overridden. Read then, not before
  (D46: a regression detector, not a measurement).
- **SC-004**: No written document contains a `never_in_documents` item, for
  any ad.

## Assumptions

- The masters are written and approved by the person, outside JobAgent.
- The cover letter is still generated per ad.
- Interview prep may use anything in the profile.
