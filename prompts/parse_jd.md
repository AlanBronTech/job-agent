# parse_jd — v1

Extract structure from a job advertisement. Extraction only: every value must
come from the text supplied. This prompt feeds a fit scorer that will make
apply/skip decisions, so an invented requirement causes a wrong decision.

## Rules

1. **Never infer beyond the text.** If the ad does not state something, use
   `null` for scalars, `[]` for lists, or `"unknown"` for the enums. An absent
   value is information; a guessed one is a defect.
2. **Do not normalise away meaning.** Keep requirements close to how the ad
   words them. "5+ years managing engineering teams" stays as it is — do not
   soften it to "team leadership experience".
3. **Split compound requirements.** "Strong PHP and React with AWS exposure"
   becomes three entries, so each can be matched independently.
4. **must_haves vs nice_to_haves** follows the ad's own framing: "required",
   "essential", "you will have", "must" → must_haves. "desirable", "bonus",
   "nice to have", "advantageous" → nice_to_haves. Where the ad does not
   distinguish, put the item in must_haves — over-stating a requirement causes
   a conservative score, under-stating it causes a wasted application.
5. **red_flags** are observations about the *advertisement*, not the company.
   Legitimate entries: no salary band; a stated on-site requirement; a
   requirement combination implying two roles in one; unpaid work or equity in
   place of salary; a very long must-have list; contradictions within the ad;
   language suggesting a role reposted repeatedly. Leave empty if there are
   none. Do not editorialise about the employer.

## Fields

- `title` — the role title as advertised. Required; if genuinely absent, use
  the most specific descriptor the ad offers.
- `company` — hiring organisation. `null` if the ad is via an agency and the
  employer is not named. Do not use the agency name as the company.
- `location` — as stated, e.g. "Sydney CBD", "Melbourne (Hybrid)".
- `work_type` — one of `permanent`, `contract`, `fixed_term`, `unknown`.
- `work_arrangement` — one of `onsite`, `hybrid`, `remote`, `unknown`. Base
  this on explicit statements only. "Flexible working" alone is `unknown`;
  "3 days in the office" is `hybrid`.
- `salary_range` — object or `null`:
  - `min_aud`, `max_aud`: integers, annual, AUD. Convert "$150k" to `150000`.
    For a day rate, leave both `null` and put the rate in `raw`.
  - `includes_super`: `true` only if the ad says the figure includes
    superannuation, `false` only if it says it excludes it, otherwise `null`.
  - `raw`: the salary text exactly as the ad states it.
- `seniority` — the level as worded ("Senior", "Lead", "Engineering Manager"),
  or `null`.
- `must_haves`, `nice_to_haves` — requirement strings.
- `tech_stack` — named technologies, languages, frameworks, platforms, tools.
  Names only, no surrounding phrasing.
- `responsibilities` — what the person will do.
- `red_flags` — see rule 5.

## Output

A single JSON object with exactly these keys:

```json
{
  "title": "string",
  "company": "string or null",
  "location": "string or null",
  "work_type": "permanent | contract | fixed_term | unknown",
  "work_arrangement": "onsite | hybrid | remote | unknown",
  "salary_range": {
    "min_aud": 0,
    "max_aud": 0,
    "includes_super": true,
    "raw": "string"
  },
  "seniority": "string or null",
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
