# Project folder guidance

Use this guide when creating or organizing project material. The shared contract defines the defaults;
explicit project conventions take precedence. These are optional locations, not a required scaffold.
Install and upgrade create only declared kit control files, never the product folders below.

## Choose by purpose

| Location | What belongs here | Examples |
| --- | --- | --- |
| `_docs/` | A maintained document set from which a newcomer can understand the project. | Overview, scope, architecture, data flow, current behavior, usage, operations and known limitations. |
| `_note/` | Material still being explored or a record of working communication. | Planning drafts, alternatives, meeting summaries, mail summaries and reply drafts. |
| `_reference/` | Inputs consulted for understanding or design, with source and version identified. | External specifications, manuals, papers and sanitized source summaries. |
| `_evidence/` | Results supporting a specific claim, tied to the relevant revision and check. | Validation summaries, experiment evidence and acceptance results. |
| `config/` | Versioned configuration consumed by software or its tests and delivery tools. | Runtime profiles, schemas, test scenarios and fixtures. |
| `_meta/` | Metadata about maintaining the repository. | Documentation edition metadata and document input maps. |
| `.cache/` | Regenerable caches and temporary tool output. | `.cache/pytest/`, `.cache/ruff/`, `.cache/mypy/`; explicitly tracked `.gitkeep` sentinels may remain. |
| `.agents/eidos/` | Eidos Direction and Work, when enabled. | Stable strategy in Direction; assigned execution plans, progress and outcomes in Work. |

Folder names alone do not establish truth, permission or implementation status. Separate confirmed
facts, proposals, observed results and unknowns. Follow the project's privacy and evidence rules;
these examples do not authorize copying raw email, personal data, credentials or restricted material.

## Placement examples

- A mail requesting a scope change: put its necessary work summary and reply draft in `_note/mail/`.
  After agreement, update the relevant explanation in `_docs/`; update Direction or create Work when
  execution intent changes. A reply draft is not a sent message or an agreement.
- An early implementation plan: use `_note/planning/` while exploring options. Once assigned and
  accepted for execution, record it in Eidos Work. Do not maintain a second authoritative task list.
- A description of how the current system works: use `_docs/architecture.md`, backed by actual source
  and evidence. A roadmap may explain direction but must label future work clearly.
- A test report: keep retained evidence in `_evidence/` with its source revision, command and result;
  summarize the relevant conclusion in `_docs/` rather than copying raw logs into the explanation.
- A schema read by tests or code: use `config/`, even if humans also read it. A map used only to
  manage documentation editions belongs in `_meta/`.
- Tool results that can be regenerated belong in `.cache/<tool>/`. Ignore their contents in Git,
  while retaining explicit exceptions such as `.cache/pytest/.gitkeep`. Ignoring `.cache/` itself
  prevents descendant exceptions: use traversable parent patterns and verify exclusions and
  exceptions with Git. Promote evidence worth retaining to `_evidence/` with its revision and check.
  Never treat the cache designation as permission to delete another task's files.
- A research project may explicitly reserve `_development_plan/` for R&D proposal documents and
  presentation materials. Preserve that project convention; place everyday planning and mail drafts
  in `_note/`. The kit does not create `_development_plan/` or assume it is a universal requirement.

## Keep the explanation coherent

Start small: a README and an overview may be enough for a new project. Add documents when they help
someone understand the project, not to fill every example folder. Link to source material and evidence
where needed. Move confirmed conclusions into the explanation in your own concise terms, retaining
provenance and relevant uncertainty. Follow the project's edition/archive process before changing an
existing document set. Never rewrite historical evidence or move established folders as part of setup.

When a project's existing layout differs, record the mapping in its bootstrap or project route.
The guide provides defaults; it does not introduce a parallel planner, replace domain contracts, or
make research plans, communication drafts and external reference documents into implementation facts.
