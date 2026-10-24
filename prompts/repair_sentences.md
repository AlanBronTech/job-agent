# repair_sentences — v1

These sentences come from Alan Bron's job application. A checker compared
each one with the evidence it cites and found a problem. Rewrite each
sentence so it says only what its evidence says. You are fixing these
sentences only; the rest of the document stays as it is.

## The sentences, each with the problem and the full text of its evidence

<sentences>
{items}
</sentences>

## Rules

1. **Say only what the evidence says.** Keep the point the sentence was
   making where the evidence supports it. Where it does not, say less: drop
   the unsupported part. Never add a fact, number, mechanism, cause or order
   of events that the evidence does not state.
2. **Keep its job.** Same person (first person, "I"; or no pronoun in a
   resume highlight), same tense, roughly the same length, so it still fits
   the sentences around it. Never "Alan", "he" or "his".
3. **A resume highlight keeps its form** "Label — claim": a short label, a
   spaced em dash, then the claim. The label may change if it was the
   problem.
4. Plain, factual, engineering register. None of these phrases: {banned}.
5. Do not list or explain what you changed.

## Output

JSON only. One entry per sentence, `original` copied exactly as given.

{"repairs": [{"original": "the sentence exactly as given", "text": "the rewritten sentence"}]}
