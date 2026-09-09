# Project requirement preservation

Harness supplies a read-only tool and a small example; each project owns its requirements and
verification commands. Eidos remains the owner of Direction, Work, focus and claims. No second task
tracker is introduced. Installation never creates `_meta/` or a live requirement registry.

## Adoption

Review existing instructions, design principles, relevant Work/Failure and bounded Git history.
Name the audit categories, repositories and limits before searching. Classify every investigated
requirement as `common`, `project-only`, `retired`, `gap` or `unknown`; do not promote another
project's convention automatically. Preserve evidence limitations and disagreements.

Use `.agents/harness/requirements.example.json` as a schema example, then create the project-owned
`_meta/requirements/registry.json` with real evidence. The example is not an audited baseline:
replace its observations, choose your own categories and rules, and connect actual verification.
Do not copy an example digest or invent a committed revision. An initial registry needs independent
review before it becomes the basis for deletion checks. Commit it through the project's usual flow.
If no registry has been adopted, the commands report unconfigured and exit nonzero without writing;
review the existing rules manually and record the adoption decision in the existing execution record.

## Select and check

```powershell
py -3.13 -B .agents/tools/requirements.py select --route change --path src --domain software
py -3.13 -B .agents/tools/requirements.py select --route release-or-external --path kits
py -3.13 -B .agents/tools/requirements.py check --base HEAD --json
```

Use the project's declared domains and paths in these examples. Select exactly one existing risk
route. Purpose (`--domain`, optional) and paths select additional obligations independently of risk.
`common: true` means always selected; classification `common` means shared-kit coverage. These are
different concepts. Select before implementation and check actual paths afterwards; extra `--path`
arguments add obligations and cannot hide actual changes. Unregistered paths warn and retain common
obligations. Load only returned references; the full registry is not a bootstrap reading requirement.

The registry has schema version 1, an `audit` with `local_repository`, `repositories`, `categories`
and descriptive limits, `observations`, and `rules`. Local repository identity cannot be rebound in
place to bypass reference checking. Categories cannot disappear; retain retired requirements.
Each observation records repository, relative path, SHA256 of observed bytes, observation kind and
revision. `working-tree` uses the base revision without asserting those bytes were committed;
`unborn` has null revision. External observations are provenance only and are never opened or run.

Each rule keeps a stable `REQ-*` ID, concise summary, category, classification, always-selected
boolean, domains, literal file/directory prefixes, sources, surfaces, notes and optional decision.
Sources link observation IDs and exact text locators. Surfaces link relative paths, exact markers,
roles (`guidance`, `documentation`, `implementation`, `verification`) and a null or known `gap`.
Connect the project's actual behavior tests and verification instructions; this tool runs neither.
Text markers locate evidence and never prove semantic compliance.

Unexplained removal or amendment, duplicate IDs and broken references fail. Preserve retired rows
with a new decision reason, source references and replacement IDs. Other amendments need a new
decision too (replacement list may be empty); a declaration merely marks them for independent
review. Never weaken checks to manufacture success. Known missing surfaces warn while unrelated,
and fail when changed. Registering an old gap alone is allowed. Human and JSON reports are derived
from this same registry; completion, ownership and follow-up stay in Work or existing project records.

## Dirty baseline and review

`check` compares the working tree and index against a Git commit, including nonignored untracked
files. Before any task edits, capture a reviewed JSON snapshot if unrelated dirty work must be
excluded. Its `head` must be the exact base commit, `files` maps every tracked/nonignored path to its
SHA256, and `registry_text` retains the exact previous registry text when present. Retain the snapshot
hash in Work. Keep it in an ignored project evidence location, not inside the rules registry.

```powershell
py -3.13 -B .agents/tools/requirements.py check --base <commit> --baseline <relative-snapshot.json>
```

Both the committed registry and reviewed dirty registry remain comparison bases. A snapshot cannot
replace the committed guard. Its authenticity and completeness require review; do not capture it
after edits and treat those changes as pre-existing. For a repository without a commit, use `select`
and initial manual review first; `check` requires a real Git base. Queries never create commits.

Connect `check` to the project's canonical verification entry point as a quick preflight. Then run
relevant behavior tests and independent review against original requirements and frozen changes.
With Eidos, Work needs only applied IDs, dispositions, verification evidence and residual candidates;
do not copy rule bodies. Run the full suite once after freezing; repeat only checks justified by
changed bytes or failures. Restoring a gap's reference is not proof its behavior was restored.

The commands never write files, refresh the Git index, run tests, execute reference code, or access
other repositories. Output reports metadata files/bytes read and baseline hashing separately. These
measure I/O, not agent capability or token savings. The shared contract is the short bootstrap link;
project-owned bootstrap, routing and registry files are never overwritten by a kit upgrade.
