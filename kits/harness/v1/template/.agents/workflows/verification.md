# Verification workflow

Freeze the exact revision, file set, modes, and hashes. Evaluate every blocking rubric row and record
required evidence or a valid N/A reason. Independent review must use the frozen bytes. Return only
`PASS`, `NEEDS_REVISION`, or `INCONCLUSIVE`; any blocking finding produces `NEEDS_REVISION`.

Compare selected requirements and their original sources with final changed paths. Check for
omission, weakening and retirement, including obligations outside the selected risk route.
When the project has adopted a registry, run `.agents/tools/requirements.py check --base <commit>`
before expensive tests. Record and review explained amendments; marker presence is not behavioral
evidence. Use relevant behavior tests and independent semantic review. Unrelated pre-existing gaps
remain visible without blocking; changed missing surfaces must be handled. An absent registry
requires a recorded manual rule review and an explicit adoption decision, not a silent PASS.
