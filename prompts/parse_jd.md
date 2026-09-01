# parse_jd — v2

Extract structure from a job advertisement. Extraction only: every value must
come from the text supplied. This prompt feeds a fit scorer that will make
apply/skip decisions, so an invented requirement causes a wrong decision.

## Rules

1. **Never infer beyond the text.** If the ad does not state something, use
   `null` for scalars, `[]` for lists, `false` for the booleans, or
   `"unknown"` for the enums. An absent value is information; a guessed one is
   a defect.
2. **Do not normalise away meaning.** Keep requirements close to how the ad
   words them. "5+ years managing engineering teams" stays as it is — do not
   soften it to "team leadership experience".
3. **One source bullet is one requirement. Never split a bullet.**
   "Strong technical background across Java and/or Node.js, React and
   TypeScript" is a single entry, exactly as written, even though it names
   four technologies. Splitting it into four inflates the requirement count,
   and the fit scorer counts unmet requirements to decide whether to apply —
   one bullet the candidate half-meets must not read as four failures.
   Per-technology matching is what `tech_stack` is for: list Java, Node.js,
   React and TypeScript there and leave the bullet intact.
   The reverse also holds: two bullets stay two entries even when they overlap.
4. **must_haves vs nice_to_haves** follows the ad's own framing: "required",
   "essential", "you will have", "must" → must_haves. "desirable", "bonus",
   "nice to have", "advantageous", "highly regarded", "preferred" →
   nice_to_haves.
   Where an ad frames *nothing* as mandatory — "here are some of the things we
   are looking for", "apply even if your experience isn't a perfect match" —
   do not force everything into must_haves. Put the requirements the ad leads
   with and states plainly in must_haves, put the softened and qualified ones
   in nice_to_haves, and record the framing itself as a red flag: an ad that
   states no hard requirements cannot be scored against hard requirements.
5. **red_flags are judgment about the advertisement, not a checklist.**
   Structural omissions belong there — no salary band, a stated on-site
   requirement, a very long must-have list, language suggesting a role
   reposted repeatedly — but an ad that has only those has been read
   shallowly. Also look for, and say plainly:
   - **Two roles in one.** A scope that fuses an established product with a
     new mandate, or management with a full IC workload.
   - **Contradictions.** "Hybrid" with three days in the office stated
     elsewhere; a Sydney office requirement alongside teams in other
     countries; a chip saying full-time above a body saying 12-month term.
   - **Culture and hours statements.** "We are looking for people who work for
     their passion, not counting hours" is an hours-culture signal and belongs
     here. So does equity in place of salary.
   - **Conditions of the job that are not tasks.** Travel percentages, on-call
     expectations, "you may report to a manager without a background in
     software engineering", relocation.
   - **Volume and staleness.** Where the supplied text carries the platform's
     own posting line — "Reposted 2 weeks ago", "Over 100 people clicked
     apply", "High application volume", "5 months ago" — that is evidence
     about the ad and belongs here.
   Do not editorialise about the employer, and do not speculate about
   anything the text does not support.

## Fields

- `title` — the role title as advertised. Required; if genuinely absent, use
  the most specific descriptor the ad offers.
- `company` — the **hiring employer**. `null` when the ad is placed by an
  agency and the employer is not named. Signs of that: the body says "our
  client"; the ad offers "a detailed overview of the company on application";
  the named poster is a recruitment business or its staff. Do not put the
  agency here — it goes in `posted_by`.
- `posted_by` — whoever placed the ad: the agency for an agency ad, the
  employer for a direct one. `null` if the text does not say.
- `via_agency` — `true` when the ad is placed by a recruitment agency or
  intermediary rather than the employer, `false` otherwise.
- `location` — the place of work, as a place. "Sydney CBD", "Sydney NSW",
  "Melbourne (Hybrid)". Where an ad names several cities, keep them all but
  keep it a location — not a sentence. If the platform's own header states a
  single location and the body lists more, prefer the header.
- `work_type` — one of `permanent`, `contract`, `fixed_term`, `unknown`.
  The platform's employment-type chip is authoritative: "Full time" or
  "Full-time" is `permanent`, "Contract/Temp" is `contract`, "Part time" with
  no end date is still `permanent`. A term stated in the body overrides the
  chip: "12-month max term" under a "Full time" chip is `fixed_term`. Use
  `unknown` only when neither the chip nor the body says anything.
- `work_arrangement` — one of `onsite`, `hybrid`, `remote`, `unknown`. Base
  this on explicit statements only. "Flexible working" alone is `unknown`;
  "3 days in the office" is `hybrid`.
- `hiring_status` — `closed` when the page says the ad is no longer taking
  applications ("No longer accepting applications", "applications have
  closed"), `open` when it plainly still is, `unknown` otherwise.
- `multiple_roles` — `true` when one ad advertises several positions rather
  than one ("we're currently recruiting multiple positions across our product
  engineering team", "multiple roles available"), `false` otherwise.
- `salary_range` — object or `null`:
  - `min_aud`, `max_aud`: integers, annual, AUD. Convert "$150k" to `150000`.
    For a day rate, leave both `null` and put the rate in `raw`.
  - `includes_super`: `true` only if the ad says the figure includes
    superannuation, `false` only if it says it excludes it, otherwise `null`.
  - `raw`: the salary text exactly as the ad states it. Keep vague wording
    verbatim — "Exceptional Daily Rate", "competitive package" — rather than
    discarding it; that the ad said only this is worth knowing.
- `seniority` — the band the role sits in, as one of:
  `junior`, `mid`, `senior`, `lead`, `manager`, `director`, `unknown`.
  Judge it from the responsibilities and the stated experience, not from the
  title alone — titles are inconsistent between employers. `lead` is the
  senior individual-contributor track (tech lead, staff, principal, and the
  hands-on "Engineering Lead" that manages no one). `manager` is people
  management (engineering manager, delivery manager). `director` covers head
  of, director, GM, VP and above. An "Engineering Lead" asking for 3–6 years
  is `mid` whatever it calls itself.
- `must_haves`, `nice_to_haves` — requirement strings, one per source bullet.
- `tech_stack` — named technologies, languages, frameworks, platforms and
  tools. Names only, no surrounding phrasing. This is where a compound
  requirement's individual technologies go. Standards and certifications
  (DO-178, PRINCE2, ISO 27001) are not technologies — leave them in the
  requirement that mentions them.
- `responsibilities` — what the person will **do**. A condition of the job is
  not a responsibility: travel, on-call, who they report to and where they sit
  are red flags or location, not tasks.
- `red_flags` — see rule 5.

## Output

A single JSON object with exactly these keys:

```json
{
  "title": "string",
  "company": "string or null",
  "posted_by": "string or null",
  "via_agency": false,
  "location": "string or null",
  "work_type": "permanent | contract | fixed_term | unknown",
  "work_arrangement": "onsite | hybrid | remote | unknown",
  "hiring_status": "open | closed | unknown",
  "multiple_roles": false,
  "salary_range": {
    "min_aud": 0,
    "max_aud": 0,
    "includes_super": true,
    "raw": "string"
  },
  "seniority": "junior | mid | senior | lead | manager | director | unknown",
  "must_haves": ["string"],
  "nice_to_haves": ["string"],
  "tech_stack": ["string"],
  "responsibilities": ["string"],
  "red_flags": ["string"]
}
```

No prose, no markdown fences, no commentary.

## Job advertisement

{jd_text}
