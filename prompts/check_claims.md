# check_claims — v1

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

Not a mismatch: paraphrase, compression, a different order, leaving detail
out, or a sentence about the ad (those are marked `ad` and are not listed).

## Output

JSON only. An empty list when every sentence is faithful.

{"mismatches": [{"sentence": "the sentence, verbatim", "problem": "merged people: the evidence has a developer and a team lead; the sentence makes them one person"}]}
