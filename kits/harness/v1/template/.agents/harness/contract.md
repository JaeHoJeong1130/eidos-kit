# Shared harness contract

## Authority

Source and deterministic tests outrank prose. Direction owns strategy; Work owns bounded execution;
Failure records preserve prevention. Missing or remote activity is unknown.

## Risk

- R0: read-only; no rubric is required.
- R1: bounded internal change; common rubric and self-check are required.
- R2: public or multi-consumer impact; common plus profile rubric and independent review are required.
- R3: release, external, destructive, or irreversible impact; fresh approval and independent review are required.

## Verdicts

Use only `PASS`, `NEEDS_REVISION`, or `INCONCLUSIVE`. A blocking criterion cannot be waived by a score.
Use N/A only when its rubric condition is satisfied and record why.

## Change safety

Preserve unrelated dirty files. Never push, release, deploy, delete, or contact an external system
without explicit authority. Validate exact changed paths and retain evidence. Read-only operations must
not change tracked files or the Git index.

## Repository layout

Harness/Eidos own declared control-plane paths only; they never create or rename product directories.
Use `config/` for versioned configuration, profiles, scenarios, schemas and fixtures consumed by code,
tests, packaging or deployment. Reserve `_meta/` for repository-only metadata, never runtime input.

Create optional project-owned folders only when needed. Respect explicit project conventions;
record deviations in a project route instead of moving existing files implicitly.

| Path | Purpose |
| --- | --- |
| `_docs/` | Maintained explanations sufficient to understand the project's purpose, scope, structure, behavior, use and limits. |
| `_note/` | Exploratory notes, planning drafts, meeting/mail summaries and reply drafts; not execution authority. |
| `_reference/` | External source material, specifications and curated references with provenance. |
| `_evidence/` | Verification results and evidence supporting claims and decisions. |
| `config/` | Versioned inputs consumed by code, tests, packaging or deployment. |
| `_meta/` | Repository-management metadata, never product runtime input. |
| `.agents/eidos/` | With Eidos enabled, stable Direction and durable execution Work; focus is derived. |

Keep transient planning and correspondence out of `_docs/`. Promote confirmed, relevant conclusions
into maintained explanations; leave working history in its original role. Documentation never proves
implementation by itself. See [folder guidance](repository-layout.md) for placement examples.

Renaming roots used by code, tests, docs, artifacts or deployment is R2: inventory consumers, preserve
historical evidence, provide recovery and independent review. Kit installation never does it implicitly.

## Identity

New Work uses an active canonical human `member:*` from project-owned identity. Historical Work keeps
its IDs, resolved through explicit aliases. Claims separate member responsibility from `agent:*`
execution. Machine names, agents, aliases and unknown members cannot own new Work.

## Failure knowledge

Search only failure entries selected by route tags. Promote reusable lessons with an enforcement link
to a route, test, validator, or code boundary. Never store credentials, personal data, raw chat, raw
logs, or machine-specific absolute paths.
