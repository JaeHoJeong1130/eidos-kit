# Project folder guidance

Use this guide when creating, moving or organizing project material. This guide defines the defaults;
explicit project conventions take precedence through `_meta/layout.json` role mapping and exceptions.
Fresh install in an empty Git root creates the standard support scaffold. Existing projects receive
control files only unless `--layout standard` is requested; upgrade never relocates their material.

## Choose by purpose

| Location | What belongs here | Examples |
| --- | --- | --- |
| `_docs/` | A small maintained reading set from which a newcomer can understand the project. | Index plus typically 4–6 concise pages: overview, current structure, usage, operations, status and limits. |
| `_blueprint/` | Concrete documents used to design and build the project. | Detailed target architecture, contracts, ADRs, implementation roadmaps, research designs and acceptance plans. |
| `_note/` | Material still being explored or a record of working discussion. | Planning drafts, alternatives and working discussion notes. |
| `_reference/` | Inputs consulted for understanding or design, with source and version identified. | External specifications, manuals, papers and sanitized source summaries. |
| `_evidence/` | Results supporting a specific claim, tied to the relevant revision and check. | Validation summaries, experiment evidence and acceptance results. |
| `config/` | Versioned configuration consumed by software or its tests and delivery tools. | Runtime profiles, schemas, test scenarios and fixtures. |
| `_meta/` | Metadata about maintaining the repository. | Documentation edition metadata and document input maps. |
| `.cache/` | Regenerable caches and temporary tool output. | `.cache/pytest/`, `.cache/ruff/`, `.cache/mypy/`; explicitly tracked `.gitkeep` sentinels may remain. |
| `.agents/eidos/` | Eidos Direction and Work, when enabled. | Stable strategy in Direction; assigned execution plans, progress and outcomes in Work. |

Folder names alone do not establish truth, permission or implementation status. Separate confirmed
facts, proposals, observed results and unknowns. Follow the project's privacy and evidence rules;
these examples do not authorize copying personal data, credentials or restricted source material.

## Placement examples

- A proposed scope change: keep working notes in `_note/`. After agreement, update the relevant
  explanation in `_docs/`; update Direction or create Work when execution intent changes.
  A draft is not an accepted decision.
- An early implementation idea: use `_note/planning/` while exploring options. A concrete build plan
  belongs in `_blueprint/`; assignment, progress and execution authority remain in Eidos Work.
- A description of how the current system works: use `_docs/architecture.md`, backed by actual source
  and evidence. Put the detailed roadmap in `_blueprint/` and link it from a short status explanation.
- A test report: keep retained evidence in `_evidence/` with its source revision, command and result;
  summarize the relevant conclusion in `_docs/` rather than copying raw logs into the explanation.
- A schema read by tests or code: use `config/`, even if humans also read it. A map used only to
  manage documentation editions belongs in `_meta/`.
- Tool results that can be regenerated belong in `.cache/<tool>/`. Ignore their contents in Git,
  while retaining explicit exceptions such as `.cache/pytest/.gitkeep`. Ignoring `.cache/` itself
  prevents descendant exceptions: use traversable parent patterns and verify exclusions and
  exceptions with Git. Promote evidence worth retaining to `_evidence/` with its revision and check.
  Never treat the cache designation as permission to delete another task's files.
- A project may reserve additional folders for its domain-specific material. Preserve explicitly
  documented purposes and use the project's role mappings and exceptions instead of imposing another
  project's folder names. The kit does not create these custom folders.

## Keep the explanation coherent

Start small: a README and an overview may be enough for a new project. Add documents when they help
someone understand the project, not to fill every example folder. Link to source material and evidence
where needed. Move confirmed conclusions into the explanation in your own concise terms, retaining
provenance and relevant uncertainty. Follow the project's edition/archive process before changing an
existing document set. Never rewrite historical evidence or move established folders as part of setup.

## Scaffold and inspect

`harness_kit.py install --layout auto` (default) scaffolds an empty Git root only. `--layout none`
retains control-only installation; `--layout standard` explicitly adds missing support entry files.
Scaffolded files become project-owned and are not overwritten or hash-policed during upgrade.
The standard support roots are `_docs`, `_blueprint`, `_note`, `_reference`, `_evidence`, `_meta`
and `.cache`; no application source, runtime config or test folders are generated.

For an existing project use `harness_kit.py layout init --root <project>` to preview absent-file
creation, then the same command with `--apply` to apply it. It never overwrites existing files.
The installed `.agents/tools/layout.py check` and `preview` commands are read-only; manager `doctor`
includes their inspection. Missing declared entrypoints and malformed/unsafe mappings are errors.
Unlisted or excessive docs and filenames suggesting detailed plans are review warnings. Path heuristics
cannot prove semantic placement: review document content, not only a green check.

The layout policy has `schema_version: 1`, all eight `roles`, a `docs_entrypoints` array,
`docs_max_files` (default 7), and `exceptions: [{path, reason}]`. Map a role to an existing convention
instead of inventing duplicate roots. Exceptions are bounded, explicit prefixes with a reason.
Keep archived editions immutable; record old-to-new paths and hashes for an approved migration.
Preview reports candidate moves only. Applying moves requires consumer/link inventory, a preserved
pre-change edition, hash verification and independent R2 review; no command auto-classifies and moves
project documents. Installation and layout operations never stage, commit, push or delete project data.

When a project's existing layout differs, record the mapping in its bootstrap or project route.
The guide provides defaults; it does not introduce a parallel planner, replace domain contracts, or
make plans, working notes and external reference documents into implementation facts.
