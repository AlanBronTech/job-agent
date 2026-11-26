# CLI contract: Agency Resume

Invented examples: job 12 is Harbour Talent's "Engineering Manager" for Acme
Logistics; the suggested master is `em`.

## `jobagent generate`

New option:

```
--long-profile   Replace the resume's PROFILE with a longer one (up to 250
                 words) written for this ad. With a master (the default), a
                 copy of the master; with --custom, a custom resume.
```

| Command | Resume kind | Files |
|---|---|---|
| `generate 12 --resume` | `master` (unchanged behaviour) | the `em` master's file |
| `generate 12 --long-profile` | `master_profile` from `em` | `<Person>_Resume_Acme_<YYYYMM>.docx` |
| `generate 12 --master ai --long-profile` | `master_profile` from `ai` | as above |
| `generate 12 --custom --long-profile` | `custom_profile` | as above |
| `generate 12 --long-profile --cover` | `master_profile` + letter | resume and letter |

- `--long-profile` alone implies `--resume`. With it, the plain master is not
  copied (the copy replaces it).
- `--long-profile --no-master` is `custom_profile`.
- Refused before any spend (exit 2):
  - the job is "not a target" for every master and none is named: "No master
    to copy for this job. Pass --master <id>, or --custom --long-profile.";
  - the master's PROFILE heading cannot be found: names the master file and
    the heading.
- Before spending, the cost line, e.g.
  `Expected ~$0.05 for what has been measured. No measurement yet for generate_profile.`
- After the run, as today: issues, claim check, unused entries, pages
  (`Resume: 2.86 pages`), and the base: `Resume: copy of the Engineering
  Manager master with a longer profile (231 words).`

## `jobagent apply`

New option:

```
--long-profile   The resume sent had the longer profile. With --master.
```

- `apply 12 --master em --long-profile` → `resume_master=em`,
  `resume_long_profile=1`.
- `apply 12 --sent-as-generated` → base and flag from the job's latest
  resume record.
- `apply 12 --sent-resume edited.docx` (not identical to a master) → base
  and flag from the latest resume record when there is one, else `custom`.
- `--long-profile` without `--master`, `--sent-resume` or
  `--sent-as-generated`: refused (exit 2), "Name which resume: --master <id>
  --long-profile, or --sent-as-generated."

## `jobagent status`

The `resume` column shows `em+profile` / `custom+profile` when the flag is 1.

## `jobagent revise --resume`

Refused when the latest resume record's base is a master: "This resume is
a copy of the <label> master. Generate it again with a context note
(`jobagent context 12 \"…\"`), or revise a custom resume."
