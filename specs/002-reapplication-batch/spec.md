# Feature Specification: Reapplication Rule and Batch Review

**Feature Branch**: `002-reapplication-batch`

**Created**: 2026-10-03

**Status**: Draft

**Input**: User description: "Reapplication rule and batch review. (1) Don't apply again to the same job within 6 months; a different job at a previously-applied company is evaluated like any other ad, and company history alone never dismisses an ad. (2) Detect 'same job' reliably: identical URL is not enough because reposts get new URLs; extract requisition IDs (e.g. Workday JR_ numbers) from ads. (3) Record applications made outside the tool without an ingested ad, so earlier applications count. (4) Batch review: parse results, scores and decisions for several ads shown as one table, in the CLI and the UI, with refused captures as their own rows with the reason."

All examples are invented (Constitution VI). No company, requisition number,
figure or person here comes from the profile or the application history.

## Why

In one batch session, an ad for "Engineering Manager" at an employer (call it
Fabrikam Medical) was parsed, scored and had a resume and cover letter
generated, about $0.30 and an hour of review, before the employer's own
careers portal showed that the same requisition, `JR_000123`, had been applied
for five months earlier and was still open with no reply. The tool could not
know: the earlier application was made before the tool existed, the ad had
been reposted under a new URL, and nothing in the store linked the two.

In the same session, one of seven saved ads was refused because its capture
was cut off, and the refusal sat inside another ad's output, so it was missed
until the results table was compared against the folder.

## Clarifications

### Session 2026-10-03

- Q: What counts as the same job when neither ad has a requisition number? → A:
  Same company and same role title within six months is "possibly the same
  job": Alan answers yes or no before anything is spent, and the answer is
  recorded. Chosen because the worked example's ad carried no requisition
  number in its text, so requisition matching alone would not have caught it,
  while generic titles make a hard block wrong for different jobs.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Review a batch of new ads in one table (Priority: P1)

Alan saves several job ads during a session. He asks the tool to take in
everything new, and gets one table: one row per saved file, showing company,
role, work arrangement, posting age and applicant count, the free hard-filter
check, any history with the company, and, for a file that could not be read or
was refused, the reason. From the table he picks which ads to score, sees the
combined cost, and confirms. The table then shows verdicts and scores, and he
picks which ads to generate documents for and which to mark not applied.

**Why this priority**: This is the daily loop for more than one ad, done today
by hand over a dozen commands. It is also where the missed refusal happened.

**Independent Test**: With model calls mocked, save five invented ads (one cut
off at "…more", one a duplicate of an ad already stored), run the batch, and
check the table has five rows: three parsed, one refused with its reason, one
flagged as already stored. Choose two to score, then one to generate.

**Acceptance Scenarios**:

1. **Given** five ads saved since the last batch, **When** Alan starts a batch,
   **Then** he is shown the five file names and the combined parse cost before
   anything is spent.
2. **Given** a capture that ends at a "…more" toggle, **When** the batch runs,
   **Then** it is its own row, marked refused, with the reason and what to do,
   and nothing is spent on it.
3. **Given** the parsed batch, **When** Alan selects three rows to score,
   **Then** he sees the combined score cost, and after confirming, the table
   shows each verdict and both scores.
4. **Given** scored rows, **When** Alan marks some for documents and the rest
   as not applied, **Then** documents are generated only for the marked rows,
   each with the same confirmation and guards as a single generate, and the
   rest are recorded as `not_applied`.
5. **Given** the same batch in the CLI and in the UI, **Then** both show the
   same rows, columns and refusals.

---

### User Story 2 - Don't reapply to the same job within six months (Priority: P1)

When an ad turns out to be a job Alan applied for less than six months ago, the
tool says so before anything is spent and does not score it or generate for it
unless he explicitly overrules. A different job at the same company is
assessed like any other ad. Company history alone never dismisses an ad.

**Why this priority**: The money and the hour in the worked example were spent
on a job that had already been applied for.

**Independent Test**: Record an application to Fabrikam Medical `JR_000123`
three months ago. Add a reposted ad carrying `JR_000123` under a new URL: it is
flagged as the same job, and score and generate refuse without an overrule. Add
a Fabrikam Medical ad for `JR_000456`: it is scored normally, with the earlier
application shown as history.

**Acceptance Scenarios**:

1. **Given** an application to requisition `JR_000123` four months ago, **When**
   an ad with `JR_000123` is added, **Then** the ad is marked "applied for this
   job on <date>, <n> months ago" and scoring is refused before any cost.
2. **Given** the same, **When** Alan overrules, **Then** scoring and generation
   go ahead and the overrule is recorded with the ad.
3. **Given** an application to the same requisition seven months ago, **When**
   the ad is added, **Then** it is assessed normally and the earlier
   application is shown as history.
4. **Given** an earlier application at the same company to a different
   requisition, **When** the ad is added, **Then** it is assessed normally and
   the earlier application is shown as history, never as a reason to skip.
5. **Given** an ad from a company Alan has applied to before but with no
   requisition number in either ad, **When** the role title also matches,
   **Then** the ad is marked "possibly the same job as your application of
   <date>", and before any cost Alan is asked yes or no. Yes applies the
   six-month rule as for a confirmed match; no assesses the ad normally. His
   answer is recorded with the ad and not asked again.

---

### User Story 3 - Record an application made outside the tool (Priority: P2)

Alan records an application he made before the tool existed, or through a
portal, without having an ad for it: company, role title, requisition number if
known, date applied, channel, and status. It counts for history and for the
six-month rule exactly like an application the tool tracked. If the ad is later
added, he can link the two.

**Why this priority**: Without it the six-month rule can only see applications
made through the tool, which is how the worked example happened.

**Independent Test**: Record "Fabrikam Medical, Engineering Manager,
`JR_000123`, applied 2026-05-05, status applied_no_reply" with no ad. Add an ad
carrying `JR_000123`: User Story 2 fires.

**Acceptance Scenarios**:

1. **Given** no stored ad, **When** Alan records an outside application with a
   requisition number, **Then** it appears in the pipeline and in that
   company's history.
2. **Given** an outside application without a requisition number, **When** an
   ad from that company is added, **Then** the application shows as history,
   and Story 2 scenario 5 applies.
3. **Given** an outside application and an ad later recognised as the same
   job, **When** Alan links them, **Then** one pipeline record results, keeping
   the original application date, and the ad's text is marked as captured
   after the decision to apply.
4. **Given** a date in the future, **When** Alan records an outside
   application, **Then** it is refused, as `apply` refuses today.

---

### User Story 4 - Requisition numbers read from ads (Priority: P2)

When an ad carries an employer's requisition or reference number, it is
extracted and stored with the ad, and shown in the table and detail view.

**Why this priority**: It is what makes "same job" reliable across reposts,
where the URL changes and the title often does not.

**Independent Test**: Parse invented ads containing `JR_000123`, `Req ID:
45871` and `Job reference: ABC-2026-77`; each stores its number. An ad with
none stores nothing, never a guess.

**Acceptance Scenarios**:

1. **Given** an ad stating a requisition number, **When** it is parsed, **Then**
   the number is stored exactly as written.
2. **Given** an ad with no requisition number, **When** it is parsed, **Then**
   none is stored and nothing is inferred from the URL or title.
3. **Given** ads already in the store, **When** this feature is introduced,
   **Then** their numbers can be extracted from their stored text without
   re-parsing them through the model.

---

### Edge Cases

- The same file is saved twice under different names: the second is flagged as
  a likely duplicate of a stored ad and not parsed unless Alan says so.
- A batch is interrupted midway (a model call fails, the UI stops): rows already
  parsed or scored keep their results; the rest show as not done and can be
  resumed without repeating paid work.
- Two ads in one batch carry the same requisition number: both are flagged, and
  only one can be scored without an overrule.
- A requisition number appears in an ad that also names a different one (for
  example a "similar jobs" footer the capture did not strip): only the number
  in the ad body is taken; if the body has more than one, none is stored and
  the row says so.
- The six-month window is measured from the date applied, not the date the ad
  was captured.
- An earlier application that ended `withdrew` or `rejected_screen` still counts
  for the six-month rule; the rule is about the job, not the outcome.
- Ads saved before this feature exists are not offered as "new" in the first
  batch unless Alan picks them; otherwise the first batch would hold the whole
  folder.
- Budget mode: the table's cost lines say free tier.

## Requirements *(mandatory)*

### Functional Requirements

**Batch review**

- **FR-001**: Alan MUST be able to start a batch over every saved ad not yet
  taken in, and MUST be shown the files and the combined parse cost before
  anything is spent.
- **FR-002**: The batch MUST produce one row per saved file, including files
  refused or unreadable, each with its reason and the next step.
- **FR-003**: Each parsed row MUST show company, role, work arrangement, salary
  as stated, posting age and applicant count as captured, requisition number,
  the free hard-filter results, company history, and the reapplication flag.
- **FR-004**: Alan MUST be able to choose any subset of rows to score, then any
  subset to generate for, then mark the rest not applied, each step showing its
  combined cost and needing confirmation, as single actions do today.
- **FR-005**: Each per-ad action started from a batch MUST be exactly the
  single-ad action: same guards, refusals, records, run-log entries and files.
- **FR-006**: The batch table MUST be available in both the CLI and the UI with
  the same rows and columns. In the UI, the ad list MUST present a multi-ad
  view as this table.
- **FR-007**: A batch MUST be resumable after an interruption without repeating
  any paid step that already succeeded.

**Reapplication rule**

- **FR-008**: An ad MUST be marked "same job as an earlier application" when its
  requisition number matches an earlier application's, or its URL matches an
  earlier application's ad.
- **FR-008a**: When neither ad has a requisition number, an ad from the same
  company with the same role title as an application less than six months old
  MUST be marked "possibly the same job", and Alan MUST answer yes or no before
  any cost is spent on it. Yes is treated as a match (FR-009); no is assessed
  normally. The answer MUST be recorded and not asked again for that ad.
- **FR-009**: When the matching application is less than six months old,
  scoring and generation MUST be refused before any cost, unless Alan overrules;
  an overrule MUST be recorded with the ad.
- **FR-010**: The six-month window and the rule itself MUST be Alan's stated
  setting in his profile, like the other filters, and not a constant.
- **FR-011**: An earlier application to a different job at the same company MUST
  NOT affect the verdict, the score or whether scoring is allowed; it is shown
  as history only.

**Outside applications**

- **FR-012**: Alan MUST be able to record an application with no ad: company,
  role title, optional requisition number, date applied, channel, status,
  notes.
- **FR-013**: Outside applications MUST count in company history and in the
  reapplication rule exactly as tracked applications do.
- **FR-014**: Alan MUST be able to link an outside application to an ad added
  later, keeping the original application date, and the ad MUST be marked as
  captured after the decision to apply.
- **FR-015**: Outside applications MUST NOT enter the eval set unless linked to
  an ad captured before the application date; an ad captured later was not what
  the decision was made on.

**Requisition numbers**

- **FR-016**: Parsing MUST extract an employer requisition or reference number
  when the ad states one, stored exactly as written, and MUST store none rather
  than guess.
- **FR-017**: Requisition numbers MUST be extractable for ads already stored
  without a paid re-parse.

### Key Entities

- **Requisition number**: an employer's own identifier for a job opening,
  stated in the ad or known from the application; the strongest evidence that
  two ads are the same job.
- **Outside application**: an application with no ad: company, title, optional
  requisition number, date, channel, status, notes; optionally linked to an ad
  later.
- **Batch**: a set of saved files taken in together, and the per-row state of
  each (refused, parsed, scored, documents generated, not applied).
- **Reapplication flag**: on an ad, the earlier application it matches, how old
  that application is, and whether the window applies.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Replaying the worked example (an outside application, then a
  reposted ad for the same job) spends nothing, in a test and in use: with the
  requisition number in the ad, it is refused before scoring; with no number
  in the ad, Alan is asked "possibly the same job?" before scoring.
- **SC-002**: A batch of seven saved ads, including one refused capture, can be
  taken from saved files to scored table in two confirmations and under five
  minutes of Alan's time, excluding model wait.
- **SC-003**: In a test batch with a refused capture, the refusal appears as its
  own row 100% of the time, never only in another row's detail.
- **SC-004**: Every per-ad action started from a batch produces records and
  run-log entries identical to the same action started singly.
- **SC-005**: No ad is refused or downgraded because of a different job at the
  same company, verified by test.

## Assumptions

- Six months is measured as 183 days from the date applied. Alan's wording was
  "six months"; the setting can change it.
- "New since the last batch" means saved files with no stored ad recorded
  against them. Recording which file each ad came from is part of this feature;
  ads stored before it are matched to files where that is unambiguous.
- The 001 local UI and its service layer are the foundation; the batch table
  reuses the confirmation, cost and run machinery built there.
- The overrule for one ad does not waive the rule for others; the worked example
  was overruled once, deliberately.
- No automated access to job boards is added. Requisition numbers come only from
  saved ad text or from what Alan types.
