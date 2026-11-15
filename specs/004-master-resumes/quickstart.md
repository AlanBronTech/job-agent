# Quickstart: Master Resumes

1. Put the masters (.docx, and .pdf if you have one) in `profile/resumes/`
   and list them in `profile/resumes/masters.yaml` (see data-model.md).
2. `jobagent profile validate`: the masters are listed; a missing file fails.
3. `jobagent score <id>` (or `--last`, free): the `resume` row names the
   master and the file to send, or says not a target.
4. `jobagent generate <id> --cover`: the letter, as before. Add `--resume`
   for a custom one.
5. `jobagent apply <id> --channel linkedin` records the suggested master;
   `--master <id|custom>` records something else.
6. `jobagent status`: the `resume` column.

Tests: `tests/test_masters.py` (registry, selection), `tests/test_services_masters.py`
(choose, resolve_sent), `tests/test_cli_score.py`, `tests/test_cli_apply.py`,
`tests/test_docs.py`, `tests/test_services_documents.py`,
`tests/test_services_listing.py`, `tests/test_web_read.py`,
`tests/test_web_masters.py`, `tests/test_store.py` (v19), `tests/test_roles.py`
(`never_in_documents`).
