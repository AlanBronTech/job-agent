# Feature Specification: Generation Quality

**Feature Branch**: `003-generation-quality`

**Created**: 2026-10-07

**Status**: Draft

**Input**: User description: "Generation quality. Make generated resumes, cover letters and application answers fit the kind of role and stay faithful to the profile. (1) Classify each ad by role type … (8) Application answers … Standing decisions to respect: keep the one gap sentence in letters; keep founder years; keep the master resume format; the score-stability item is out of scope unless free models can do it."

All examples are invented (Constitution VI).

## Clarifications

### Session 2026-10-07

- Q: Where does role-type classification happen? → A: A separate small call,
  made the first time an ad needs it and stored with the ad. No prompt that
  the eval set measures changes; old ads cost nothing unless worked on.
- Q: Do the paid checks (claim check, independent review) run by default? →
  A: Yes, both, with the cost shown before each run, and each can be switched
  off.

## Why

For a people-focused Engineering Manager ad at an employer we'll call Northwind
Freight (the ad led with coaching, empathy, 1:1s and "addressing
underperformance with care"), the generated documents:

- opened the resume's profile paragraph on managing out an underperformer,
  and put an AI highlight first;
- used one disagree-and-commit story four times: profile, highlight,
  experience bullet and cover letter;
- had the letter state a fact the profile did not support at the time, and
  collapse two people in a story into one;
- left the strongest coaching evidence out of the resume and put it only in
  the letter, which a screener may never read;
- were never checked against the ad or the policies by anything other than
  the model that wrote them.

Each document passed the existing validator (numbers traced, banned phrases,
length). The faults were in choice, emphasis and fidelity of prose, which the
validator does not see. Alan fixed them by hand before sending.

Several items that looked like defects turned out to be the generator obeying
an instruction: the gap sentence, and a then-canonical closing line. This
feature changes behaviour on purpose and leaves those decisions alone.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Documents fit the kind of role (Priority: P1)

Each ad is classified by the kind of role it is: people-focused,
delivery-focused, technical lead, or AI enablement. That decides which
evidence leads, which sections carry weight, and which stories may not appear
in writing at all. A people-focused ad gets a resume that opens on growing
people and building teams; a story Alan has excluded for people-focused roles
never appears in its resume or letter.

**Why this priority**: the worked example's main fault, and the one a hiring
manager notices in the first ten seconds.

**Independent Test**: With the model mocked, an invented people-focused ad
yields a resume whose profile paragraph and first highlight come from people
evidence, and in which a story excluded for people-focused roles appears
nowhere.

**Acceptance Scenarios**:

1. **Given** an ad whose must-haves lead with coaching and empathy, **When** it
   is classified, **Then** it is people-focused, and the classification is shown
   with the assessment.
2. **Given** a story marked "not in written documents for people-focused
   roles", **When** documents are generated for a people-focused ad, **Then**
   neither the resume nor the letter uses it, checked in code; interview prep
   still may.
3. **Given** a people-focused ad, **When** the resume is generated, **Then** the
   profile paragraph and the first highlight are people evidence, and AI work
   is limited to one clause unless the ad asks for it.
4. **Given** a technical-lead ad, **When** the resume is generated, **Then**
   technical depth leads instead, from the same profile.

---

### User Story 2 - Every must-have is evidenced on the resume (Priority: P1)

Each must-have in the ad is mapped to the evidence that answers it. The resume
must cover each one with a highlight or a bullet, not only a skills keyword,
where the profile has evidence. Where it has none, the requirement is reported
as a gap, as now, and nothing is invented.

**Why this priority**: screeners often read only the resume; in the worked
example the best coaching evidence was in the letter alone.

**Independent Test**: For an invented ad with four must-haves, three of which
the profile evidences, the resume carries a highlight or bullet for each of
the three, and the fourth is listed as a gap.

**Acceptance Scenarios**:

1. **Given** a must-have the profile evidences, **When** the resume is
   generated, **Then** at least one highlight or bullet on it cites that
   evidence.
2. **Given** a must-have answered only by a skills-table keyword, **When** the
   resume is checked, **Then** it is reported as covered weakly.
3. **Given** a must-have with no evidence, **When** documents are generated,
   **Then** it is reported as a gap and nothing fills it.

---

### User Story 3 - Prose stays faithful to the profile (Priority: P1)

Every factual sentence in a cover letter or application answer is tied to the
profile evidence it rests on, and that link is checked in code. A sentence
that cites nothing, or cites evidence that does not exist, fails. Optionally, a
separate check compares each claim with its evidence to catch a sentence that
cites real evidence but says something different, such as two people merged
into one.

**Why this priority**: the resume is already safe (its bullets are copied
from the profile); the letter and answers are free prose and are where
fidelity slipped.

**Independent Test**: With the model mocked, a letter sentence citing a
non-existent evidence id fails; a sentence with no citation fails; a sentence
that frames the ad ("You are hiring for …") without asserting a fact about
Alan passes.

**Acceptance Scenarios**:

1. **Given** a generated letter, **When** it is checked, **Then** every
   sentence asserting something about Alan cites at least one evidence id that
   exists in the profile.
2. **Given** a profile without an acquisition fact, **When** a letter is
   generated, **Then** the word "acquisition" does not appear (seeded test).
3. **Given** the optional claim check is run, **When** a sentence merges two
   people from its cited story into one, **Then** it is reported.

---

### User Story 4 - An independent review before documents are called ready (Priority: P2)

After generation, a separate review reads only the ad, the written policies
and the finished documents (not the instructions the writer was given) and
reports blocking failures and suggestions, as a hiring manager and a policy
checker would. Documents with a blocking failure are not presented as ready.

**Why this priority**: nothing checked the worked example's documents against
the ad; Alan did it by hand.

**Independent Test**: With the reviewer mocked to return a blocking failure,
the generate result is marked not ready and lists it; with none, it is ready.

**Acceptance Scenarios**:

1. **Given** finished documents, **When** the review runs, **Then** its cost
   was shown before it ran and is logged like every other call.
2. **Given** a blocking failure from the review, **When** the result is shown,
   **Then** the documents are labelled not ready, with the failures listed.
3. **Given** the original worked-example documents (invented copy), **When**
   reviewed, **Then** at least the role-fit fault, the repeated story and the
   unsupported fact are reported.

---

### User Story 5 - Story reuse and defensive phrasing are capped (Priority: P2)

One story appears at most twice on a resume (a short highlight plus one
experience bullet, never also in the profile paragraph) and at most once in a
letter. Defensive or self-referential phrasing ("not a claim about it", "not
advisory influence", "this ad is asking for", more than one "not X but Y" per
document) is caught mechanically.

**Why this priority**: both were visible in the worked example; both are
cheap to enforce.

**Independent Test**: A resume using one story in the profile paragraph, a
highlight and a bullet fails; a letter containing "this ad is asking for"
fails.

**Acceptance Scenarios**:

1. **Given** a resume, **When** checked, **Then** no story id is used more than
   twice, and none appears in the profile paragraph if it also has a bullet.
2. **Given** a letter, **When** checked, **Then** no story is used twice.
3. **Given** defensive phrasing from the banned list, **When** it appears,
   **Then** it is a blocker, as banned phrases are today.

---

### User Story 6 - A letter knows who it is written to (Priority: P3)

A cover letter carries one sentence about the employer: its product, mission
or work, drawn only from the ad's own text. Nothing is said about the company
that the ad does not say.

**Why this priority**: a letter with no company-specific content reads as
generic; but it is the smallest fault.

**Independent Test**: An invented ad describing "3D site mapping for
construction" yields a letter that names that work; an ad with no company
description yields no company sentence rather than an invented one.

**Acceptance Scenarios**:

1. **Given** an ad with an "about us" section, **When** a letter is generated,
   **Then** one sentence draws on it.
2. **Given** an ad without one, **When** a letter is generated, **Then** no
   company claim is made.

---

### User Story 7 - Application answers from an answer bank (Priority: P2)

Many portals ask questions instead of, or as well as, a cover letter. Alan
keeps an answer bank in his profile, by question type (summary, why this
company, why this role, why you, what made you apply, salary expectation,
notice period, right to work, why leaving). Pasting a form's questions, with an
optional character limit, gives one answer per question tailored from the bank
and the evidence, in a short and a long variant, with no story repeated across
the answers to one form, and saved with the application. The cover letter
becomes something Alan asks for, not a default.

**Why this priority**: portals increasingly ask questions instead of letters,
and the questions were answered by hand last time.

**Independent Test**: Four invented questions with a 600-character limit give
four answers within the limit, each with a short and a long variant, no story
used twice across the four, every claim traced as in User Story 3.

**Acceptance Scenarios**:

1. **Given** questions and a limit, **When** answers are generated, **Then**
   every variant is within the limit.
2. **Given** a "why this company" question, **When** answered, **Then** it cites
   only what the ad says or what Alan has confirmed he has seen.
3. **Given** an answer bank entry for the question type, **When** answered,
   **Then** the answer starts from it.
4. **Given** generation in the UI, **When** the form opens, **Then** the cover
   letter is not ticked by default.

---

### Edge Cases

- An ad that is genuinely two kinds (people-focused and technical lead): one
  primary kind decides, the secondary is shown, and exclusions for either
  apply.
- A must-have that two pieces of evidence answer: one on the resume is enough.
- Prose that quotes the ad back ("You want someone who …"): framing, not a
  claim, so it needs no citation; a sentence asserting the ad's need as Alan's
  fact does.
- The reviewer call fails or times out: documents are written, marked "not
  reviewed", never "ready"; its cost is logged.
- A profile story without an exclusion for any role type: usable everywhere,
  as now.
- Answer-bank entry with no evidence behind it: it is Alan's own words and may
  be used, but numbers in it are traced like any other.
- Standing decisions are unchanged: one gap sentence per letter, founder years
  shown, the master resume's format.

## Requirements *(mandatory)*

### Functional Requirements

**Role fit**

- **FR-001**: Each ad MUST be classified into one primary role kind
  (people-focused, delivery-focused, technical lead, AI enablement), with an
  optional secondary kind, and the classification MUST be shown with the
  assessment. It MUST be produced by a separate small call the first time an
  ad needs it (at scoring or generation) and stored with the ad, so neither the
  parse nor the scoring prompt changes and the eval set is unaffected; ads
  never worked on again are never classified.
- **FR-002**: A profile story or entry MUST be able to declare the role kinds
  it is excluded from in written documents; an exclusion MUST be enforced in
  code for resumes, letters and answers, and MUST NOT apply to interview prep.
- **FR-003**: The role kind MUST decide what leads the resume's profile
  paragraph and highlights, and the order of the skills categories.

**Coverage and reuse**

- **FR-004**: Each must-have MUST be mapped to the evidence that answers it, and
  the resume MUST cover every evidenced must-have with a highlight or bullet.
  Coverage by skills keyword only MUST be reported as weak.
- **FR-005**: A story MUST appear at most twice on a resume, never in the
  profile paragraph if also in a bullet, and at most once in a letter or
  across one form's answers. Enforced in code.

**Fidelity of prose**

- **FR-006**: Every sentence in a cover letter or answer that asserts something
  about Alan MUST cite at least one existing evidence id; a missing or unknown
  id MUST be a blocker. Framing sentences about the ad need none.
- **FR-007**: An optional claim check MUST compare each cited claim with its
  evidence and report mismatches, with its cost shown before it runs. It and
  the review in FR-008 MUST run on every generate by default, each with its
  cost shown first, and MUST each be possible to switch off per run and in
  configuration.
- **FR-008**: An independent review MUST read only the ad, the written
  policies and the finished documents, and return blocking failures and
  suggestions; documents with a blocking failure MUST be labelled not ready.
- **FR-009**: Defensive and self-referential phrasing MUST be added to the
  banned list and enforced by the existing validator.
- **FR-010**: A letter MUST contain at most one company-specific sentence,
  drawn only from the ad's text, and none when the ad says nothing about the
  company.

**Answers**

- **FR-011**: The profile MUST hold an answer bank keyed by question type; the
  answers command MUST start from it, honour a character limit, give a short
  and a long variant, and not repeat a story across one form.
- **FR-012**: Answers MUST be saved with the application's documents so
  interview prep knows what was claimed.
- **FR-013**: The cover letter MUST be opt-in in the UI (unticked by default);
  the CLI already requires `--cover`.

**Standing decisions**

- **FR-014**: The one gap sentence in letters, founder years and the master
  resume format MUST be unchanged. Repeated scoring for stability is out of
  scope.

### Key Entities

- **Role kind**: the classification of an ad; primary and optional secondary.
- **Exclusion**: on a story or entry, the role kinds it must not appear for in
  written documents.
- **Coverage map**: each must-have → the evidence answering it → where it
  appears in the documents.
- **Citation**: a sentence's link to one or more evidence ids.
- **Review**: the independent pass's findings, blocking or advisory, per
  document.
- **Answer bank entry**: Alan's own answer for a question type, used as the
  starting point.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Regenerating the worked example's ad (invented copy) yields a
  resume that opens on people evidence, uses the excluded story nowhere, and
  repeats no story more than twice: verified by test.
- **SC-002**: In a test set of generated letters, 100% of sentences asserting
  something about Alan cite an existing evidence id; 0 cite an unknown one.
- **SC-003**: For an ad with evidenced must-haves, 100% appear on the resume as
  a highlight or bullet.
- **SC-004**: The review flags at least 3 of the worked example's 4 faults when
  run on the original documents.
- **SC-005**: A four-question form with a character limit yields four answers
  within the limit, with no story repeated, in one confirmation.
- **SC-006**: The per-application cost stays under $0.45 with the paid checks
  on (today about $0.28 without them), and the extra cost is shown before
  each run.
- **SC-007**: Over the next ten real applications, the hand edits Alan makes
  before sending fall, measured by noting each one.

## Assumptions

- The eval set grades the scorer, not the writer, and no prompt it measures
  changes (classification is a separate call).
- Exclusions are set by Alan in his profile; none is inferred.
- The answer bank starts with Alan's own answers to one recent four-question
  form, which he will paste into the profile.
- Prices are per the measured run log; the review and the claim check are each
  expected to cost a few cents, to be measured once built.
- Nothing here submits anything; answers are produced to paste.
