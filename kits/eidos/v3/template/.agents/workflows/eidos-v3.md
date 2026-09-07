# Eidos v3 workflow

1. Read Direction and `focus --summary`; use detailed focus/catalog/claim list when needed.
2. Give one Work exactly one owner and a non-overlapping repository-relative `write_scope`.
3. Split parallel efforts into child Works; do not collaboratively edit a parent Work.
4. Use `work start` to create Work and claim before mutation; surface conflicts.
5. Record verified Progress, Result, Evidence, and deviations in the Work.
6. Validate before `work finish` records closure and releases its claim. Never delete claims as cleanup.

The current Direction must contain exactly `Purpose`, `Boundaries`, `Baseline`, `Stages`, `Gates`,
and `Dependencies` in that order. Every actual Work, including planned Work, requires an assigned
namespaced owner; `unassigned` is only a template placeholder. Closed Work cannot acquire, renew,
or adopt a claim.

Claim records use opaque, non-reusable worktree-instance identities and never store local absolute
paths. Removing and recreating a worktree never reattaches its historical claims, even when Git
reuses the same administrative name. Unavailable worktree state, claims from another PC, and
unpushed Work are not observable; report them as unknown. Focus and claim-list commands must not
refresh or rewrite a Git index. Adoption retains the original worktree and every outgoing custody
epoch so dirty state is never attributed only to the newest custodian. Scope comparisons follow
repository case semantics after separator and dot-segment canonicalization. Trailing-dot/space
components and Git pathspec syntax are invalid, and Git probes always use literal pathspecs.

## Short Work commands

`work start --input start.json` and `work finish --input finish.json` each perform one operation.
Use `--input -` for stdin. Both return the `ok`, `command`, `data`, `error` JSON envelope.
Commands only write the declared Work and local runtime state: no tests, staging, commit, or remote calls.
R1 may use a concise Plan. R2+ still requires detailed scope, compatibility, test and independent review evidence.

```json
{
  "slug": "parser-boundary",
  "title": "Define empty parser input",
  "owner": "member:h",
  "stage": "S01",
  "write_scope": ["src/parser", "tests/test_parser.py"],
  "risk": "R1",
  "actor": "agent:codex",
  "intent": "Make empty input deterministic.",
  "completion_criteria": "Empty input returns no rows.",
  "verification_plan": "Run parser boundary tests."
}
```

Use an active project member. Supply exactly one of `slug` or today's explicit `id`.
Optional `workstream` defaults to `workstream:default`; `parent` is omitted when absent;
`depends_on` is an optional nonempty array of existing Work IDs. The Work path is automatically
included in its scope. The initial claim lasts one hour; existing claim renew/adopt commands remain available.

Use the returned Work and claim IDs to finish:

```json
{
  "work_id": "W-20260907-01-parser-boundary",
  "claim_id": "claim-0123456789abcdef0123456789abcdef",
  "actor": "agent:codex",
  "status": "done",
  "result": "Empty input returns no rows.",
  "evidence": "Parser boundary tests passed."
}
```

Terminal status is `done`, `failed`, or `cancelled`. Supply actual result and evidence for each;
submitted text is not proof that checks or review ran. Existing explanations and progress are preserved.
Older Work with incomplete Intent/Plan produces validation warnings; fill its purpose, completion
criteria and verification plan before using `work finish`. Its claim must cover the Work document.
Open Work may retain an archived Direction; missing Direction/Stage remains an error. New Work always
uses the current Direction. Revision rollover preserves archived bytes and existing Work references.

## Retry and recovery

Retry with the same input content: local receipts retain the generated IDs, timestamps and write set.
Successful retries do not append progress or rewrite terminal records. Changed terminal content is refused.
Receipts live under the worktree Git administrative directory's `eidos/operations`; they are not project
records or shared state. Keep them while retries may be needed. No command cleans them automatically.
Only the target Work/claim keep recovery bytes; other project inputs use hash and metadata guards.
Normal failures restore only this operation's bytes and retain a receipt. Concurrent edits are preserved;
`work_recovery_required` requires inspection of the receipt and conflicting files before retry.
Changed project inputs or HEAD refuse a pending retry; expired leases require explicit diagnosis/adoption,
never silent takeover. Do not remove a lock after interruption until its owning operation is known to have stopped.
If both Work and claim already match the recorded result, retry only acknowledges completion and
does not need a new lease. Full or partial rollback that requires publication must retain a valid lease.

`new-work` and individual claim commands remain available for planned Work and manual workflows.
