# Feature Specification: Local UI (Phase 8)

**Feature Branch**: `001-local-ui`

**Created**: 2026-09-29

**Status**: Draft

**Input**: User description: "Phase 8 UI"

**Source**: `BUILD_PLAN.md` § Phase 8. Exit criterion carried over unchanged:
*the daily loop — see the shortlist, read an assessment, generate documents —
happens without typing a command.*

All examples in this spec are invented (Constitution VI). No company, figure or
person named here comes from the profile or the application history.

## Clarifications

### Session 2026-09-29

- Q: When a generate run is refused because documents already exist in that
  application's folder, should the UI offer any way to overwrite them? → A:
  Neither overwrite nor refuse outright: after confirmation, the existing
  folder is moved aside to a dated name, then the run writes a fresh folder.
  Nothing is replaced.
- Q: If Alan closes the tab or browser while a model call is running, should
  the run keep going? → A: Yes. The run finishes on the local server whatever
  the browser does; reopening the ad shows it running or its result; and a run
  that finished while its page was closed is announced on the next page opened.
- Q: After documents are generated, how should the UI get Alan to them for
  review? → A: Buttons open each document in its default application and
  reveal the folder in Finder. No in-page preview.
- Q: Should this version be built as a cloud product? → A: No. Local UI first,
  but built so a hosted version can follow without reworking workflow
  behaviour: a single-user hosted demo on an invented persona next, then
  profile intake (master CV), multi-user only after that has a real user.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Read the shortlist and an assessment (Priority: P1)

Alan opens the tool and sees every job ad on record with its verdict, both
scores, pipeline status and the date it was captured. He picks one and reads
the whole assessment on one page: hard-filter results (met / breached / not
stated), requirements with evidence and gaps, challenge points, questions to
ask, and any prior history with the same company.

**Why this priority**: Reading is the most frequent part of the loop, costs
nothing, and changes no state. It is useful on its own and every other story
builds on the same two views.

**Independent Test**: With a store holding scored and unscored ads, open the
list and a detail page; every field shown matches what `jobagent jd show` and
`jobagent score --last` print for the same record. No model call is made.

**Acceptance Scenarios**:

1. **Given** a store with ads in several states (unscored, scored apply,
   scored skip, applied), **When** Alan opens the tool, **Then** he sees one row
   per ad with id, company, title, verdict, both scores and status, newest first.
2. **Given** an ad whose salary floor is breached, **When** he opens it, **Then**
   the breach is shown as overriding the model's verdict, and a constraint the
   ad does not mention is shown as "not stated", never as met.
3. **Given** an ad from "Northwind Freight" where an earlier Northwind ad ended
   `rejected_screen`, **When** he opens it, **Then** the prior encounter is shown
   as information and the verdict is unchanged by it.
4. **Given** an ad amended after it was scored, **When** he opens it, **Then** the
   assessment is flagged as predating the amendment.

---

### User Story 2 - Generate documents from a button (Priority: P1)

From an ad's detail page Alan chooses which documents to generate (resume,
cover letter, application answers), sees the expected cost, confirms, and waits
while it runs. When it finishes he sees where the files were written, every
validation issue, and the list of profile entries used nowhere.

**Why this priority**: This is the step the exit criterion names and the one
that spends the most. It must carry every guard the command line has, or the
UI becomes the way around them.

**Independent Test**: With model calls mocked, generate for a scored ad and
confirm the same files land in the same folder, the same validation issues and
unused-entry list are shown, and the run is logged exactly as a command-line
run would be.

**Acceptance Scenarios**:

1. **Given** a scored `apply` ad, **When** Alan selects resume and cover letter,
   **Then** he sees the measured cost before anything is spent, and nothing is
   spent until he confirms.
2. **Given** the application folder already holds a resume from an earlier run,
   **When** he asks to generate a resume again, **Then** before spending he is
   shown each existing file and when it was last modified, and told the folder
   will be moved aside to a dated name. Only on confirmation is it moved and
   the run started; no existing file is replaced or deleted. If the move fails
   (name taken, permission denied), nothing is spent and the folder is left
   exactly as it was.
3. **Given** a `skip` verdict, **When** he asks to generate, **Then** he must
   explicitly overrule the verdict, and the overrule is recorded exactly as
   `generate --force` records it.
4. **Given** a run whose validation reports a blocker (a banned phrase, an
   untraceable number, an over-length letter), **When** it finishes, **Then**
   the blocker is shown prominently and the documents are not presented as ready.
5. **Given** a clean run, **When** it finishes, **Then** the unused-entry list is
   still shown, ongoing ventures first.

---

### User Story 3 - Add and score an ad without the terminal (Priority: P2)

Alan saves a job ad as PDF, `.mhtml` or `.txt` as he does now. In the tool he
either drops the file in or picks the newest saved ad, confirms the parse cost,
and lands on the new record's detail page. From there one button scores it
after showing the cost.

**Why this priority**: Needed to close the loop without a terminal, but less
frequent than reading, and the command-line path already works well.

**Independent Test**: With model calls mocked, add an invented ad for "Acme
Logistics — Engineering Manager" by file and by "newest saved"; the stored
record and run-log entries match what `jd add` produces. Score it; the
assessment matches `score`.

**Acceptance Scenarios**:

1. **Given** a newly saved ad file, **When** Alan chooses "add newest saved ad",
   **Then** the tool names the file it will parse and the cost before parsing.
2. **Given** a file of an unsupported type, **When** he drops it, **Then** it is
   refused before any cost, naming the accepted types.
3. **Given** the parsed company has prior history, **When** parsing completes,
   **Then** the history is shown before he decides whether to score.

---

### User Story 4 - Pipeline board and status changes (Priority: P3)

Alan sees applications grouped by status and records a change — applied on a
date, interview, offer, rejection after interview, no reply — from the board or
the detail page.

**Why this priority**: The status record feeds the eval set, so it matters,
but it changes a few times a week and `apply` / `outcome` are quick to type.

**Independent Test**: Record `applied` then `rejected_after_interview` for an
invented ad; `jobagent status` shows the same rows and dates.

**Acceptance Scenarios**:

1. **Given** applications in several statuses, **When** Alan opens the board,
   **Then** every status in the application vocabulary has a place, including
   `rejected_after_interview` and `ghosted_after_contact`, so nothing has to be
   flattened into the nearest available column.
2. **Given** an ad with no application row but documents on disk, **When** it
   appears on the board, **Then** it is shown as "documents generated, not
   recorded as applied", not as untouched.

---

### User Story 5 - Interview prep from a button (Priority: P3)

From the detail page of an ad in interview status, Alan runs prep after seeing
the cost and reads the result in the page.

**Why this priority**: Occasional and long-running; useful but not part of the
daily loop.

**Independent Test**: With model calls mocked, run prep; the file written and
the content shown match `jobagent prep`.

**Acceptance Scenarios**:

1. **Given** prep takes minutes, **When** it is running, **Then** the page shows
   it is still working and does not time out or invite a second run.

---

### Edge Cases

- A model call fails midway (timeout, dropped stream): the page says so, the
  failed attempt is still in the run log, and nothing half-written is presented
  as a result.
- Alan double-clicks a spending button or reloads mid-run: one run, not two.
- Alan closes the tab mid-run: the run continues and its outcome is announced
  later (FR-016a, FR-016b).
- The UI server itself is stopped mid-run: the run ends, as a killed command
  does, and its cost may be missing from the run log. On next start the UI
  says a run was interrupted rather than showing it as still running.
- The tool is open in a browser tab while he runs a command in the terminal:
  the next page load shows the terminal's changes; nothing is cached across them.
- A model has no entry in the price table: the cost is shown as unknown, not as
  zero, and the run is still allowed after confirmation.
- Budget mode (free tier): shown as such wherever cost is shown.
- The configuration is incomplete (no API key, output folder missing): read-only
  views still work; spending actions explain what is missing.
- An ad whose status the vocabulary cannot express: the UI offers no way to
  invent a status; the record is left as it is.
- The UI is reached from another machine on the network: it must not be.

## Requirements *(mandatory)*

### Functional Requirements

**Parity with the command line**

- **FR-001**: Every action the UI offers MUST produce the same stored records,
  files, run-log entries (apart from `source`, which is `ui`) and validation
  results as the equivalent command.
- **FR-002**: The UI MUST contain no business logic of its own. Any guard the
  command line enforces today MUST apply identically to the UI, including the
  overwrite guard, the skip-verdict overrule record, company-history
  reporting and the stale-assessment flag.
- **FR-003**: Hard-filter breaches MUST be shown as overriding the verdict, and
  "not stated" MUST be visually distinct from "met".

**Money**

- **FR-004**: Every action that calls a model MUST show its expected cost
  before running and MUST NOT run without an explicit confirmation.
- **FR-005**: Expected cost MUST come from measured spend, not a constant in the
  UI; where no measurement exists, it MUST say so.
- **FR-006**: A spending action MUST NOT be startable twice concurrently for the
  same ad.

**Hard rules**

- **FR-007**: The UI MUST NOT fetch or embed any job-board page. Ads enter
  only as files Alan saved himself or text he pastes.
- **FR-008**: The UI MUST NOT submit, fill in or link-through to any application
  form. Its output is files in the local output folder.
- **FR-009**: Generated documents MUST be shown with every validation issue and
  the unused-entry list, on clean runs as well as failing ones.

**Views and actions**

- **FR-010**: A list view MUST show every ad with id, company, title, captured
  date, verdict, both scores and pipeline status, sortable by date and score.
- **FR-011**: A detail view MUST show the parsed ad, the latest assessment in
  full, prior company history, amendment state, documents on disk for that ad,
  and its pipeline status.
- **FR-012**: Alan MUST be able to add an ad by dropping a file or by choosing
  the newest file in the saved-ads folder, and by pasting text.
- **FR-013**: Alan MUST be able to score, generate and prep from the detail view.
- **FR-014**: A board view MUST group ads by pipeline status, with a place for
  every status value and for "documents generated, not recorded".
- **FR-015**: Alan MUST be able to record a status change with a date.
- **FR-016**: Long-running actions MUST show progress until they finish or fail,
  and MUST report failure in plain terms.
- **FR-016a**: A run MUST NOT depend on the page that started it. Closing the
  tab or browser MUST NOT cancel it; reopening the ad MUST show it still
  running or its outcome.
- **FR-016b**: A run that finishes, or fails, while its page is closed MUST be
  announced on every page Alan opens, naming the ad and the outcome, until he
  has viewed it.
- **FR-016c**: For every generated document on disk — current or superseded —
  the UI MUST offer to open it in its default application and to reveal its
  folder in Finder. The UI MUST NOT render a preview of a document's content;
  the file itself is what gets reviewed and sent.
- **FR-017**: The UI MUST NOT overwrite existing documents. When a generate run
  would clash with documents already in the application folder, the UI MUST
  list them with their modification times and, on confirmation, move the
  whole folder aside to a dated name before any model call. If the move fails,
  nothing is spent. The move-aside MUST live in the shared service layer and be
  available to the command line too (FR-002), so the UI has no behaviour the
  command line lacks.
- **FR-017a**: A moved-aside folder MUST still count as documents on disk for
  that ad — in the detail view, on the board, and in every "has this been
  done" check — and MUST be shown as superseded, not as the current set.

**Access and launch**

- **FR-018**: The UI MUST be reachable only from the machine it runs on.
- **FR-019**: A single command MUST start the UI and open it in the default
  browser.
- **FR-020**: Out of scope for this version: `jd amend`, `jd delete`, `eval`,
  `spend`, profile editing. These remain command-line only. Also out of scope:
  hosting, sign-in, more than one user, and profile intake. Those are later
  features (see Assumptions).

**Readiness for a hosted version**

- **FR-021**: Every workflow the UI or command line runs MUST take, as an
  explicit input, whose profile it uses, which record store, which saved-ads
  location and where documents go. None may read these from process-wide
  settings. A later hosted version must be able to supply a different set per
  person without changing any workflow's behaviour.
- **FR-022**: Storing, listing, superseding and opening documents MUST each go
  through one replaceable interface. The local implementations (a folder on
  disk, opened in the desktop application) are the only ones built now.
- **FR-023**: Nothing in the workflows may assume one person. Records the UI
  adds (for example a run's status) MUST be attributable to the person they
  belong to, even though this version has only one.

### Key Entities

Existing entities only; this feature adds none.

- **Job description**: the parsed ad, with amendment history.
- **Assessment**: verdict, two scores, constraint results, requirements, gaps,
  challenge points, questions to ask; may predate an amendment.
- **Application**: pipeline status and dates for one ad.
- **Generated documents**: files in the output folder — state in their own
  right, independent of whether an application row exists. An ad may have one
  current folder and any number of superseded (moved-aside) folders; a
  superseded folder may hold the documents that were actually sent.
- **Run record**: one logged model call with cost and purpose.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a week of real use, the daily loop (see shortlist → read
  assessment → generate documents) is completed without typing a command.
- **SC-002**: Opening the list or a detail page takes under one second with
  100 ads on record.
- **SC-003**: For every UI action with a command-line equivalent, an automated
  test shows identical stored records, files and run-log entries.
- **SC-004**: No model call is made without a confirmation that displayed its
  cost; verified by test for every spending action.
- **SC-005**: Zero cases, in test or use, of the UI overwriting documents,
  deleting records, or spending twice for one click.
- **SC-006**: The UI is unreachable from any other machine on the network.
- **SC-007**: A test runs each workflow twice in one process against two
  different contexts (profile, store, saved-ads location, document location) and
  finds no state crossing between them.

## Assumptions

- Single user, one machine. No login; reachability is limited to the local
  machine instead (FR-018).
- The command line stays the primary interface for everything in FR-020 and
  remains fully supported; the UI is additive.
- Some guards named in FR-002 currently live in the command layer rather than
  the shared service layer. Moving them is part of this feature, justified as
  a defect under Constitution II, not a UI requirement.
- Opening files relies on the machine running the UI being the machine Alan
  sits at, which FR-018 already guarantees.
- Move aside rather than overwrite (FR-017, clarified 2026-09-29). The
  command line's `--overwrite` stays as it is and is not offered in the UI.
  Superseded folders accumulate in the output folder; tidying them is manual.
- No duplicate-ad check is added. `jd add` has none today, and one in the UI
  alone would be business logic the command line lacks (FR-002). If it is
  wanted, it belongs in the service layer as its own change.
- Ads saved from job boards as PDF / `.mhtml` / `.txt` are the only file inputs,
  as for `jd add`.
- Product direction (2026-09-29): this may become a hosted product — first for
  Alan, later a low-cost public service, possibly with an employment agency
  helping job seekers build a master CV. This version builds none of that;
  FR-021–FR-023 exist so it does not have to be unpicked later. A privacy
  principle is added to the constitution before any other person's data is
  held, not in this feature.
- Timing: `BUILD_PLAN.md` deferred this until typing commands became the
  friction. Starting the spec is Alan's call that it has; SC-001 is how that
  gets checked.
