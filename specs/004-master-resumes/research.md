# Research: Master Resumes

## R1. How many masters

Read from the application record (the analysis itself is gitignored: it names
real employers and outcomes). Applications grouped by role type: engineering
manager, AI adoption, tech/team lead, senior engineer, delivery/PM. Findings
that shaped the decision, in general terms:

- Engineering-manager roles were most of the volume and most of what the
  person marks interesting: the default master.
- AI-adoption roles were few but asked for different things: a master of
  their own, scoped to adoption, never to shipped production agent systems.
- The one human-stated rejection reason that concerns a resume's opening was
  "hands-on coding not recent enough": a hands-on master. The person then
  scoped it to contracts only.
- Delivery/PM, contract-as-such, domain and Head-of roles: no evidence a
  separate master would help; several lacked a must-have no resume can supply.
- The numbers are too small to rank masters by outcome. That is why what went
  and what was suggested are both recorded: to read later (SC-003).

## R2. Code or model for the pick

Code. Every input is already stored, the rule fits in a docstring, the result
is repeatable and free, and it can be shown on every page. A model would add
a cost line to a read-only view and a coin flip on boundary cases (D45).

## R3. Title shape

Whole-word matching, in order: manager words (manager, head, director, chief,
CTO, VP) → "manager"; a team/tech/technical/squad lead phrase → "lead";
seniority manager or director → "manager"; hands-on words (engineer,
developer, programmer, architect, scientist) → "hands_on"; any other "lead" →
"lead". So "Engineering" is not "engineer", "Lead AI Engineer" is hands-on,
and an "Engineering Team Lead" pitched at manager level is still a lead.

## R4. Recording the override

Stored at `apply`, not before: what went matters; a per-ad override would be
one more thing to keep in step with nothing gained.
