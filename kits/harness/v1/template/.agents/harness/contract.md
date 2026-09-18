# Shared harness contract

## Authority

Source and deterministic tests outrank prose. Direction owns strategy; Work owns bounded execution;
Failure records preserve prevention. Missing or remote activity is unknown.

## Risk

- R0: read-only; no rubric, Work, claim, or change verification is required. Start with the requested
  evidence; load detailed contracts only when relevant or side effects are unclear. Project-owned
  bootstrap rules remain authoritative when an older installation requires additional reads.
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

Read [folder guidance](repository-layout.md) when creating, moving, or organizing material.
It defines folder roles, `_meta/layout.json` mappings and explicit project exceptions. Harness/Eidos
own declared control-plane paths; project-owned material remains under project authority.
Fresh installation may initialize support folders; upgrade never moves existing project material.
Use `config/` for versioned configuration consumed by code, tests or delivery tools.
Reserve `_meta/` for repository metadata, never runtime input.
Place caches in `.cache/<tool>/`; preserve tracked exceptions and never delete caches implicitly.

Renaming roots used by code, tests, docs, artifacts or deployment is R2: inventory consumers, preserve
historical evidence, provide recovery and independent review. Kit installation never does it implicitly.

## Identity

New Work uses an active canonical human `member:*` from project-owned identity. Historical Work keeps
its IDs, resolved through explicit aliases. Claims separate member responsibility from `agent:*`
execution. Machine names, agents, aliases and unknown members cannot own new Work.

## Requirement preservation

Keep stable requirement IDs, sources, applicable paths, enforcement references and change reasons
in a project-owned registry when adopted. Select one risk route, then independently select domain
rules by purpose and planned paths before changes; repeat with actual changed paths before completion. Release
routes retain domain obligations. Read only selected references, never the full audit by default.
Retain retired entries with reasons and replacements. With Eidos, record selected IDs, dispositions
and verification evidence in Work; otherwise use the project's existing execution record.
See [requirement guidance](requirements.md) for adoption and read-only `select`/`check` commands.
An absent registry is unconfigured, not proof that no rules apply; review existing project rules.
Pure R0 may omit requirement commands unless the project explicitly requires them; privacy,
authority, domain rules and physical read-only behavior still apply. A query that becomes a change
must apply the change route, requirements and execution workflow before writing. Selection semantics
and `select --route read-only` remain available for questions that need requirement inspection.

## Failure knowledge

Search only failure entries selected by route tags. Promote reusable lessons with an enforcement link
to a route, test, validator, or code boundary. Never store credentials, personal data, raw chat, raw
logs, or machine-specific absolute paths.
