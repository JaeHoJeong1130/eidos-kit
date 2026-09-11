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

Harness/Eidos own declared control-plane paths. Fresh Harness installation in an empty Git root also
initializes project-owned support folders; upgrade never moves existing project material.
Use `config/` for versioned configuration, profiles, scenarios, schemas and fixtures consumed by code,
tests, packaging or deployment. Reserve `_meta/` for repository-only metadata, never runtime input.

Use `_meta/layout.json` to declare project folder roles, the newcomer reading set, and reasoned
exceptions. Respect explicit project conventions; review migration consumers before moving files.

| Path | Purpose |
| --- | --- |
| `_docs/` | A small maintained newcomer reading set: purpose, current structure, behavior, use and limits. |
| `_blueprint/` | Detailed build specifications, target architecture, ADRs, research and implementation plans. |
| `_note/` | Exploratory notes, planning drafts, meeting/mail summaries and reply drafts; not execution authority. |
| `_reference/` | External source material, specifications and curated references with provenance. |
| `_evidence/` | Verification results and evidence supporting claims and decisions. |
| `config/` | Versioned inputs consumed by code, tests, packaging or deployment. |
| `_meta/` | Repository-management metadata, never product runtime input. |
| `.cache/` | Regenerable tool caches and temporary output, excluded from Git except explicitly tracked sentinels. |
| `.agents/eidos/` | With Eidos enabled, stable Direction and durable execution Work; focus is derived. |

Keep detailed implementation plans and transient correspondence out of `_docs/`. Summarize confirmed
conclusions in its newcomer reading set; link detailed design in `_blueprint/`. Documentation never proves
implementation by itself. See [folder guidance](repository-layout.md) for placement examples.

Place tool caches in `.cache/<tool>/`; preserve explicit tracked exceptions such as `.gitkeep`.
Caches are not retained evidence. Never remove cache folders or tracked sentinels implicitly.

Renaming roots used by code, tests, docs, artifacts or deployment is R2: inventory consumers, preserve
historical evidence, provide recovery and independent review. Kit installation never does it implicitly.

## Identity

New Work uses an active canonical human `member:*` from project-owned identity. Historical Work keeps
its IDs, resolved through explicit aliases. Claims separate member responsibility from `agent:*`
execution. Machine names, agents, aliases and unknown members cannot own new Work.

## Requirement preservation

Keep stable requirement IDs, sources, applicable paths, enforcement references and change reasons
in a project-owned registry when adopted. Select one risk route, then independently select domain
rules by purpose and planned paths; repeat with actual changed paths before completion. Release
routes retain domain obligations. Read only selected references, never the full audit by default.
Retain retired entries with reasons and replacements. With Eidos, record selected IDs, dispositions
and verification evidence in Work; otherwise use the project's existing execution record.
See [requirement guidance](requirements.md) for adoption and read-only `select`/`check` commands.
An absent registry is unconfigured, not proof that no rules apply; review existing project rules.

## Failure knowledge

Search only failure entries selected by route tags. Promote reusable lessons with an enforcement link
to a route, test, validator, or code boundary. Never store credentials, personal data, raw chat, raw
logs, or machine-specific absolute paths.
