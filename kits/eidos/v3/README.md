# Portable Eidos v3 kit

Eidos v3 keeps stable project Direction separate from derived execution focus. It stores durable
Work in the repository and short-lived agent claims under the Git common directory, so linked
worktrees share local collision information without pretending that another PC is observable.

## Install

For folder purposes and placement examples, see the companion Harness Kit's
[project folder guidance](../../harness/v1/template/.agents/harness/repository-layout.md).
Harness 1.6.0 installs that guide alongside the common contract. Standalone Eidos keeps its own
Direction/Work boundary and does not install Harness guidance or create product folders.

```powershell
py -3 kits/eidos/v3/eidos_kit.py install `
  --root C:\project\example `
  --project-id project:example `
  --project-name "Example Project"
```

For an unmanaged repository that already owns `.agents/context.json`, use `migrate`
instead of `install`. Migration requires context schema v2, preserves unrelated context
and project fields, adds the Eidos contract, and refuses every other Eidos path collision.
It validates the complete candidate in isolation before writing, creates all new files
exclusively, and publishes the guarded context as the final atomic write.

```powershell
py -3 kits/eidos/v3/eidos_kit.py migrate `
  --root C:\project\existing `
  --project-id project:existing `
  --project-name "Existing Project"
```

The installed CLI is `.agents/tools/eidos.py`:

Before creating Work, set `.agents/eidos/identity.json` to `configured` and list the project's
active canonical human `member:*` IDs. Keep renamed historical IDs as explicit aliases.

```powershell
py -3 .agents/tools/eidos.py validate --root .
py -3 .agents/tools/eidos.py catalog --root . --json
py -3 .agents/tools/eidos.py focus --root . --summary --json
py -3 .agents/tools/eidos.py new-work --root . --slug scoped-change --stage S01 `
  --title "Scoped change" --owner member:h --workstream workstream:platform `
  --write-scope src/platform
```

Claims use `claim acquire`, `renew`, `release`, `adopt`, and `list` (`conflicts` is an alias).
Released and expired claims remain as local history; no command silently cleans them up. Claim
files are fully schema-checked. A malformed claim becomes a `list`/`doctor` finding, and dirty paths
left behind by a released, expired, or closed-Work claim are reported as `orphaned_dirty`. Claim
records contain only an opaque, non-reusable worktree-instance identity, never a local absolute
path. Its local marker is removed with the worktree, so recreating the same path or Git
administrative name cannot attach new dirty state to historical claims. If the original worktree
is unavailable, dirty and orphan state is reported as `unknown`. Adoption keeps an immutable
origin and complete outgoing-custody history; claim status probes aggregate every retained
worktree instead of discarding dirty state from a prior custodian.

Write scopes canonicalize separators and dot segments, reject parent traversal, and compare path
aliases using the repository's `core.ignorecase` setting. A case alias of an already claimed
physical scope therefore conflicts on case-insensitive repositories. Components ending in a dot
or space and Git pathspec syntax are rejected rather than silently aliased; every Git scope probe
also forces literal-pathspec semantics.

Every real Work, including planned Work, requires an active canonical human owner. Historical
aliases remain valid only when reading existing Work; `agent:*`, aliases, and unknown members are
rejected for new Work. The checked-in
`_template.md` keeps `unassigned` only as a placeholder and is not a valid Work record. Focus and
claim-list probes use index-refresh-free Git plumbing and preserve every worktree index.

## Maintain

Eidos 3.3.0 adds `work start --input <file|->` and `work finish --input <file|->`.
See the [installed workflow template](template/.agents/workflows/eidos-v3.md) for exact JSON inputs,
retry behavior, and recovery limits. Existing `new-work`, `claim`, and detailed `focus --json` remain
available. `focus --summary --limit 5 --json` returns at most five Work per status, with totals,
omitted counts, previous-Direction markers, and diagnostics. Limit requires summary and must be positive.
Summary remains physically read-only and performs the same validation as detailed focus.

`eidos_kit.py diff` compares the installation with its manifest. `upgrade` refreshes unmodified
kit-owned files and can migrate a v1/v2 Direction after every legacy Work is closed. It archives
the old Direction bytes unchanged, removes manual Current Focus from the new revision, and derives
Gates from legacy Stage gates. `doctor` combines manifest, project-validation, Git-common-dir, and
claim-store checks without changing the project. Install and upgrade reject repository paths that
traverse symlinks, junctions, or reparse points and roll back the complete file/manifest set after
any write failure. Doctor executes the installed project tool only after its path and every
kit-owned manifest hash pass manager-side preflight. The manager's own source templates are the
trust anchor; changing an installed tool and its target-manifest hash together still prevents
execution.
