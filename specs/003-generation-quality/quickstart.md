# Quickstart: validating 003

## Automated (no network, no cost)

`uv run pytest -q`. The proofs:

| Proves | Test |
|---|---|
| SC-001: people-focused ad → people lead, excluded story absent, ≤2 uses | `tests/test_generate_quality.py` (Northwind Freight fixture) |
| SC-002: every claim cites an existing id | `tests/test_citations.py` |
| SC-003: evidenced must-haves on the resume | `tests/test_coverage.py` |
| SC-004: review flags the worked example's faults (mocked reviewer, real policies text) | `tests/test_checks.py` |
| SC-005: four questions, limit, no repeated story | `tests/test_answers.py` |
| SC-006: cost lines shown; checks switchable | `tests/test_cli_generate.py`, `tests/test_costs.py` |

## Real (ask Alan first, ≈ $0.40)

Regenerate the real ad behind the worked example into a scratch folder
(`OUTPUT_DIR` overridden), and compare with the hand-edited documents Alan sent:
the profile should open on people leadership, the excluded story should be
absent, no story more than twice, the letter should carry no gap-about-coaching
and one company sentence. That comparison is the regression test for the
writer (fixes doc, Part C).
