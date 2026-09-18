# Change workflow

1. For R0 follow the bootstrap's query path. Before changes, read its change references and selected
   route/rubrics once; reread when contract, route, or scope changes.
2. R0 creates no Work/claim. With Eidos, use `work start`/`work finish` for changes; retain legacy
   commands for detailed/manual flows. R1 may use short Work; R2+ requires detailed risk evidence.
3. Search only failure entries matching the route tags.
   Before changes, independently select applicable requirements by purpose and planned paths using
   `.agents/harness/requirements.md`; the risk route never narrows domain obligations.
   When a query becomes a change, apply these change prerequisites before writing.
4. Preserve unrelated changes; implement only declared scope.
5. Record a concrete failure in Work before promoting a reusable failure entry.
6. Run focused and canonical checks and risk-required review. Docs-only R1 may use a declared
   canonical docs check; record why code tests are N/A. R2+ requires full checks and independent review.
   Re-select by actual changed paths, run the adopted requirements check against a pre-work Git
   baseline, and record IDs, dispositions and evidence in Work or the existing execution record.
   Freeze the completion boundary; repeat passed checks only for relevant changes or failures.
7. Commit only exact approved paths. Push remains a separate action.
