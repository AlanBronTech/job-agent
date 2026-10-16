# check_claims — v2

You are checking a job-application document against the evidence it cites.
You did not write it. Your only job is to find sentences that say more than,
or something different from, the evidence they cite.

## The sentences, each with the full text of what it cites

<claims>
{claims}
</claims>

## What counts as a mismatch

- **Overstated**: the sentence claims a bigger number, scope, title or result
  than the evidence states.
- **Merged people**: the evidence describes two people (a developer and a team
  lead, a manager and a report) and the sentence turns them into one, or the
  other way round.
- **Wrong place**: the sentence puts the work at a different employer,
  product, time or team than the evidence does.
- **Unsupported detail**: the sentence adds a fact — an event, an outcome, an
  acquisition, a technology — that none of its cited evidence contains.
- **Invented mechanism, sequence or cause**: the sentence says *how* something
  was done, *in what order*, or *why*, and the cited evidence does not say it.
  A process ("ran both systems side by side", "kept every step reversible"),
  an order ("before the migration started" where the evidence says *while*
  migrating), or a cause ("so that…", "which meant…", "because…") is a claim
  like any other. Nouns and numbers being right does not make it faithful.

  Example. Evidence: "Re-platformed the product incrementally over two years,
  no big-bang cutover, introducing CI/CD and automated testing while
  migrating." Sentence: "I ran the old and new stacks side by side, kept each
  step reversible, and had CI/CD in place before the migration began." That is
  a mismatch three times: *side by side* and *reversible* are mechanisms the
  evidence does not state, and *before* contradicts *while*.

Not a mismatch: paraphrase, compression, mentioning the facts in a different
order within the sentence (as opposed to claiming a different order of
events), leaving detail out, or a sentence about the ad (those are marked `ad`
and are not listed).

## Output

JSON only. An empty list when every sentence is faithful.

{"mismatches": [{"sentence": "the sentence, verbatim", "problem": "merged people: the evidence has a developer and a team lead; the sentence makes them one person"}]}
