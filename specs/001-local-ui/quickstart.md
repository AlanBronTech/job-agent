# Quickstart: validating the local UI

All examples use invented data. Nothing here touches the real profile or store.

## Automated: no network, no cost

```bash
uv run pytest -q
```

Expected: the existing suite (562 at the start of this feature) plus the new
tests, all passing. The ones that prove the spec:

| Proves | Test |
|---|---|
| FR-001 / SC-003: same rows, files and log records from CLI and UI | `tests/test_parity.py` |
| FR-002: each refusal fires identically on both paths | `tests/test_services_*.py`, existing `test_cli_*` unchanged |
| FR-004 / SC-004: no spend without confirmation | `tests/test_web_spend.py` |
| FR-006 / SC-005: one run per click | `tests/test_web_runner.py` (concurrent POSTs) |
| FR-016a/b: runs outlive the page, announced once, interrupted on restart | `tests/test_web_runner.py` |
| FR-017/017a: supersede, rename failure spends nothing, superseded folders found | `tests/test_docs_supersede.py` |
| FR-018 / SC-006: Host check, CSRF, bind address | `tests/test_web_security.py` |
| FR-021–023 / SC-007: two workspaces, no crossover | `tests/test_workspace_isolation.py` |

## Manual, against a throwaway store: about $0.30

Point the tool at scratch locations so the real store and output folder are
untouched:

```bash
export DB_PATH=/tmp/jobagent-demo/demo.db OUTPUT_DIR=/tmp/jobagent-demo/out \
       JD_DIR=/tmp/jobagent-demo/jds
mkdir -p $JD_DIR
# An invented ad: a few paragraphs for "Acme Logistics — Engineering Manager",
# with a salary band, location and requirements, saved as plain text.
$EDITOR $JD_DIR/acme-logistics-em.txt
uv run jobagent ui
```

1. The browser opens on an empty list.
2. **Add newest saved ad**: the file name and a parse estimate (~$0.03) are shown.
   Confirm. The ad appears; the detail page shows it parsed.
3. **Score**: estimate ~$0.11; confirm; close the tab while it runs. Reopen
   `127.0.0.1:8765`: the banner says the score finished. Open the ad: the
   assessment is shown, and the banner is gone.
4. **Generate** resume + cover: estimate ~$0.13; confirm. The files are listed with
   **Open** and **Reveal** buttons. Open launches Word. Validation issues and
   the unused-entry list are shown.
5. **Generate** again: the confirmation lists the existing files and their times
   and says the folder will be moved aside. Confirm. Finder shows both folders,
   the old one named `…superseded-…`, and the detail page lists it as superseded.
6. **Board**: record `applied` today. `uv run jobagent status` in a terminal
   shows the same row.
7. From a second machine on the network, `http://<this-mac>:8765` does not connect.
8. `uv run jobagent spend` shows this session's calls under source `ui`.

Before and after: `jobagent spend` totals for source `ui` match the sum shown in
the confirmations, within the variation of a mean.
