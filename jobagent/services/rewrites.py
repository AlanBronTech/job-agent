"""Why documents get written twice: the blockers of every rejected draft, counted.

A draft that fails a check is written again with the failures named, and on
2026-10-22 every resume and letter draft for one job was written twice, which
doubles a generate's time and cost. The final issues cannot say why: the
draft that failed is gone. Each run now keeps the blockers of its rejected
drafts beside its copies (services/documents.py, `record-<document>.json`);
this reads them back. Free.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from jobagent.services.workspace import Workspace


@dataclass
class RewriteReport:
    documents: int = 0  # document runs with a record
    rewritten: int = 0  # of those, how many needed at least one rewrite
    first_draft_rules: Counter = field(default_factory=Counter)  # rule -> drafts it failed
    any_draft_rules: Counter = field(default_factory=Counter)
    still_blocked: Counter = field(default_factory=Counter)  # rule -> final drafts it blocked
    by_document: Counter = field(default_factory=Counter)  # document -> rewrites
    examples: dict[str, str] = field(default_factory=dict)  # rule -> one excerpt


def report(ws: Workspace) -> RewriteReport:
    out = RewriteReport()
    for _folder, _run, document, record in ws.documents.all_records():
        drafts = record.get("rewrites", [])
        out.documents += 1
        if drafts:
            out.rewritten += 1
            out.by_document[document] += len(drafts)
        for n, draft in enumerate(drafts):
            rules = {issue["rule"] for issue in draft}
            if n == 0:
                out.first_draft_rules.update(rules)
            out.any_draft_rules.update(rules)
            for issue in draft:
                out.examples.setdefault(issue["rule"], issue.get("excerpt") or issue.get("detail", ""))
        final = [i for i in record.get("issues", []) if i.get("severity") == "blocker"]
        out.still_blocked.update({i["rule"] for i in final})
        for issue in final:
            out.examples.setdefault(issue["rule"], issue.get("excerpt") or issue.get("detail", ""))
    return out
