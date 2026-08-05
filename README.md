# job-agent

Interactive job-application agent. Ingests job descriptions, scores fit against
a structured profile, generates tailored resumes and cover letters, tracks the
pipeline.

Assistive, not autonomous. It never submits an application, and it never
scrapes Seek or LinkedIn — see the hard rules in CLAUDE.md.

## Getting started

1. Fill in `profile/*.yaml` by hand. Do this before writing any code.
2. `cp .env.example .env` and fill it in.
3. Work through `BUILD_PLAN.md` one phase per Claude Code session.

## Why it exists

Tailoring a resume and cover letter per application takes two to three hours.
Roughly half of that is judgement that has to stay human. The other half is
mechanical selection from a fixed set of evidence, which is exactly what an
LLM does well when it is constrained to a structured source of truth.

The measurable claim, once `evals/` exists: does the fit score predict outcomes
better than the candidate's own judgement? That number is the point of the
project.
