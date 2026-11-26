# UI contract: Agency Resume

## Job page, Generate panel (`detail.html`, POST `/ads/{id}/generate/confirm`)

The `use_master` and `resume` check boxes are replaced by one radio group,
`resume_kind`:

| Value | Label | Default |
|---|---|---|
| `none` | No resume | when no master list exists and none is wanted |
| `master` | Master resume, as is (free) | when a master is suggested |
| `master_profile` | Master resume with a longer profile for this ad (paid) | |
| `custom` | Custom resume (paid) | when there is no master list |
| `custom_profile` | Custom resume with a longer profile (paid) | |

- The `master` drop-down stays and applies to both master values.
- When the job is "not a target" and the suggestion is empty, the master
  values are still selectable once a master is picked in the drop-down; the
  route refuses a master value with no master, with the reason.
- The cover letter box is unticked by default when `master_profile` or
  `custom_profile` is chosen (a few lines of vanilla JS on the radio
  change; no new library). Server side, nothing is assumed: the box's value is
  what counts.
- No masters registered: the master values are not shown.

## Confirmation page (`generate_confirm.html`)

- Lists the files to be written; for `master_profile`, the resume line says
  "copy of the <label> master with a longer profile".
- The cost lines include `generate_profile` (or "no measurement yet") and
  the claim check.

## Pipeline form (job page, POST to the existing apply route)

The "Master resume sent" select (`master`) gains, after the masters:

- `<id>+profile` → "<label> master with a longer profile", one per master
- `custom+profile` → "A custom resume with a longer profile"

Parsed in the route: a `+profile` suffix sets `long_profile` and strips to
the base. "Sent the generated documents unedited" records the latest resume
record's base and flag (research R5).

## Job page, "Resume sent" line

Shows "Engineering Manager master with a longer profile" or "a custom resume
with a longer profile" when the flag is set.
