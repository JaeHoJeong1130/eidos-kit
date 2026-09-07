# Portable Harness Kit v1

Harness Kit installs a small, cross-model project control plane: canonical bootstrap, routing,
risk-based rubrics, append-only failure knowledge, verification workflow, and thin Codex/Claude
adapters. Eidos v3 is composed by default and remains the only owner of Direction, Work, focus,
and claims. Harness Kit does not copy or fork Eidos code.

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

Harness Kit does not install or rename product-owned root directories. The shared contract recommends
`config/` for machine-consumed configuration, profiles, scenarios, schemas, and fixtures. `_meta/`
is reserved for optional repository-management metadata that is not consumed by product runtime code.
Optional human/support roots such as `_docs/`, `_note/`, `_reference/`, and `_evidence/` remain
project-owned.

Existing repositories may declare a route-level deviation. Moving an established configuration root
is an R2 migration when code, tests, artifacts, documentation, packaging, or deployment consumes it;
the Kit never performs such a rename during install or upgrade.

## Failure knowledge

Use the installed tool without staging or committing automatically:

```powershell
py -3 .agents/tools/harness.py failure search --root . --tag evidence
py -3 .agents/tools/harness.py failure new --root . --input failure.json
py -3 .agents/tools/harness.py failure validate --root . --json
```

Each record is exclusive-created under `.agents/failures/YYYY/`. Corrections append a record with
`supersedes_id`; they do not overwrite history. With Eidos enabled, `source_work_id` must name an
existing Work. Records reject secrets, personal data, raw machine paths, and malformed schemas.

## Risk and verdicts

R0 is read-only. R1 requires common self-check. R2 adds the relevant profile and independent review.
R3 requires fresh approval and independent review. Rubrics are blocking criteria rather than scores;
review verdicts are exactly `PASS`, `NEEDS_REVISION`, or `INCONCLUSIVE`.
