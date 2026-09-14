# Portable Harness Kit v1

Harness Kit installs a small, cross-model project control plane: canonical bootstrap, routing,
risk-based rubrics, append-only failure knowledge, verification workflow, and thin Codex/Claude
adapters. Eidos v3 is composed by default and remains the only owner of Direction, Work, focus,
and claims. Harness Kit does not copy or fork Eidos code.

## After installation: adapt the project

Installation and `doctor` success verify the kit structure; they do not automatically optimize an
existing project's rules or workflow. Both GitLab and GitHub recipients should follow
[설치 후 프로젝트에 맞게 정리하기](ADOPTION.md): preserve existing rules, reconcile entry points,
set the actual Direction and human owner, map verification to change impact, and complete one real
Work when Eidos is enabled. With `--without-eidos`, verify a real bounded task using the project's
existing execution records instead. Fresh projects also need their actual goals, ownership, and verification setup.

## Fresh install

Run only against a Git top-level directory that does not already contain managed target files.

```powershell
py -3 kits/harness/v1/harness_kit.py install `
  --root C:\project\example `
  --project-id project:example `
  --project-name "Example Project"
```

Rare projects that do not need durable Direction/Work may add `--without-eidos`. `install` never
adopts or overwrites an existing path. An existing unmanaged project may use the explicit
`migrate` command only after its project-owned AGENTS, context, routing, failure guide, and optional
Direction already satisfy the current contracts. Migration preserves those declared project-owned
bytes, accepts a colliding kit-owned file only when it is the exact release byte, validates the
complete candidate together with existing Work, Failure, route, and archive extensions, and applies
one rollback-protected write set. Those extension snapshots remain read-only CAS guards throughout
the transaction; a concurrent addition, removal, content change, mode change, or reparse transition
refuses migration and rolls back every managed write.

When a trustworthy standalone Eidos v3 installation already exists, migration authenticates its
identity, complete file set, ownership map, manifest hashes, and every kit-owned byte against the
bundled Eidos source without executing the installed tool. Current project-owned context and
Direction bytes are then preserved and both manifests are rebuilt around those exact bytes.

```powershell
py -3 kits/harness/v1/harness_kit.py assess --root C:\project\example
py -3 kits/harness/v1/harness_kit.py migrate --root C:\project\example `
  --project-id project:example --project-name "Example Project"
py -3 kits/harness/v1/harness_kit.py diff --root C:\project\example --json
py -3 kits/harness/v1/harness_kit.py doctor --root C:\project\example --json
py -3 kits/harness/v1/harness_kit.py upgrade --root C:\project\example
```

`doctor`는 관리 파일과 Eidos 계약을 검증한 뒤 저장소 루트의 `.pytest_cache/`,
`.ruff_cache/`, `.mypy_cache/`도 경고함. 캐시는 각각 `.cache/pytest/`, `.cache/ruff/`,
`.cache/mypy/` 아래에 생성해야 하며, doctor는 캐시를 이동하거나 삭제하지 않음.

Install and upgrade reject repository paths that traverse symlinks, junctions, or reparse points.
They validate the complete combined Harness/Eidos write-set in a temporary Git repository before mutation and restore all target
bytes, modes, and newly created directories after a write failure. Doctor uses this manager's
templates as its trust anchor before executing the installed validator; provider application code
is never executed.

Each release retains a source-owned hash descriptor for the prior Harness templates and the
canonicalized Eidos kit-owned bytes composed with that release. Upgrade authenticates both layers
before changing versions, then validates the complete candidate. A compare-before-replace guard
refuses concurrent edits that appear after the initial drift check. Additive managed paths are
supported; removing a managed path requires an explicit future migration rather than an implicit
delete.

## Ownership

The manifest records SHA-256, mode, and `kit` or `project` ownership. Project-owned bootstrap,
context, routing, Direction, and failure contract are never overwritten during upgrade. Kit-owned
contract, rubrics, workflows, validators, adapters, and Eidos implementation can be upgraded only
while they still match the installed manifest. Failure entries and project routes are append-only
project data and are outside the managed template set.

`AGENTS.md` is canonical. `CLAUDE.md` and both Skills are deliberately short pointers and must not
grow separate policy bodies. Routes select relevant rubrics and failure tags, avoiding full-history
loads.

## Project repository layout

Harness 1.8.1 creates standard project-owned support folders for a new empty Git root. It never
automatically relocates existing material. The shared contract recommends
`config/` for machine-consumed configuration, profiles, scenarios, schemas, and fixtures. `_meta/`
is reserved for optional repository-management metadata that is not consumed by product runtime code.
`install --layout auto` is the default; `none` retains control-only installation, and `standard`
explicitly initializes absent support files in an existing project. `_docs/` contains a small
maintained newcomer reading set; `_blueprint/` contains detailed architecture, ADRs and build plans;
`_note/` contains working notes, planning drafts and meeting/mail material. `_reference/` holds
source references, while `_evidence/` holds verification evidence. With Eidos enabled, Direction
and Work remain the authorities for strategy and execution.

Harness 1.6.0 installs [folder guidance](template/.agents/harness/repository-layout.md) at
`.agents/harness/repository-layout.md`, with examples for software and research projects.
Existing explicit conventions take precedence. Upgrading adds the guide and read-only layout inspector
without moving material, and preserves project-owned bootstrap and routing files.

Use `layout init --root <project>` for a creation preview, then `--apply` to initialize only absent
entry files. Edit `_meta/layout.json` to declare roles, entrypoints and reasoned exceptions.
`layout check`, `layout preview`, and `doctor` inspect placement; preview never moves files.
The installed `.agents/tools/layout.py` also provides `check` and `preview` without the manager.
The initial reading set is a template, not a claim that project documentation is complete.

Existing repositories may declare a route-level deviation. Moving an established configuration root
is an R2 migration when code, tests, artifacts, documentation, packaging, or deployment consumes it;
the Kit never performs such a rename during install or upgrade.

## Failure knowledge

Harness 1.7.0 also supplies requirement preservation, described below; failure entries continue
to record concrete observed failures rather than becoming a second requirement catalog.

Use the installed tool without staging or committing automatically:

```powershell
py -3 .agents/tools/harness.py failure search --root . --tag evidence
py -3 .agents/tools/harness.py failure new --root . --input failure.json
py -3 .agents/tools/harness.py failure validate --root . --json
```

Each record is exclusive-created under `.agents/failures/YYYY/`. Corrections append a record with
`supersedes_id`; they do not overwrite history. With Eidos enabled, `source_work_id` must name an
existing Work. Records reject secrets, personal data, raw machine paths, and malformed schemas.

## Requirement preservation (1.7.0)

Harness 1.7.0 adds [requirement guidance](template/.agents/harness/requirements.md), a schema example
and standalone read-only `.agents/tools/requirements.py` (`select` / `check`, text or JSON).
Each project chooses its audit categories, local repository identity, rules and verification
references in its own `_meta/requirements/registry.json`. Install/upgrade never creates or overwrites
that registry. The example is schema guidance, not an audited project baseline.

Select domain rules independently of the risk route before work, then check actual changed paths
against a reviewed Git baseline. Preserve explained amendments and retirements; missing references
and affected known gaps fail. Unrelated gaps remain visible. Record applied IDs, dispositions and
verification evidence in Eidos Work or the project's existing execution record. Neither the tool nor
marker presence proves behavior: use actual behavior tests and independent review.

The installed shared contract links this procedure even when an older project's bootstrap remains
unchanged. An absent registry reports unconfigured; the workflow calls for manual rule review and
an adoption decision. Add the quick check to the project's canonical verifier when adopting it.
The folder guide now includes `.cache/<tool>/`, ignored contents and explicit `.gitkeep` exceptions.

## Risk and verdicts

R0 is read-only. R1 requires common self-check. R2 adds the relevant profile and independent review.
R3 requires fresh approval and independent review. Rubrics are blocking criteria rather than scores;
review verdicts are exactly `PASS`, `NEEDS_REVISION`, or `INCONCLUSIVE`.
