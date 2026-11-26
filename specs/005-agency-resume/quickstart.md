# Quickstart: validating the Agency Resume

## Automated (free)

```bash
uv run pytest -q
```

The new tests use `profile.example/` (Sam Rivera) and an invented master
.docx built in a fixture, with every model call mocked. They show:

1. A master copy with a longer profile differs from the master only in the
   PROFILE paragraphs; the master's bytes are unchanged (SC-001, FR-003).
2. A missing or doubled PROFILE heading is refused before any client is
   built (no spend).
3. A mocked profile over 250 words, citing a `never_in_documents` entry,
   containing a banned phrase or an untraced figure, is caught and, if it
   survives, gives `_NOT-READY` (SC-002).
4. A custom resume with the longer profile allows up to 250 words of PROFILE
   and blocks above it.
5. `apply` records the base and the flag for each route in research R5;
   `status` shows `em+profile`.
6. The UI: the radio choice reaches `services.documents.generate` with the
   right kind; the Pipeline form's `em+profile` is recorded.
7. Schema v20 opens a v19 database and adds the column, NULL for old rows.

## By hand (paid, once, after the build)

Needs LibreOffice. Pick a real ad from an agency; state the expected cost
first (`jobagent generate <id> --long-profile` prints it).

1. `jobagent generate <id> --long-profile` → open the resume; only PROFILE
   differs from the master; the run prints the page count.
2. Repeat with `--master ai` and `--master contract` (on a contract ad)
   and record each page count in the spec's SC-003 line.
3. `jobagent generate <id> --custom --long-profile` → PROFILE ≤ 250 words,
   ≤ 3 pages.
4. In the UI (restart `jobagent ui` first), generate with "Master resume
   with a longer profile", then record the application with "… with a
   longer profile" and check the job page and `status`.
5. `jobagent spend` after the first runs: the longer-profile master copy
   costs less than a custom resume for the same job (SC-004).
