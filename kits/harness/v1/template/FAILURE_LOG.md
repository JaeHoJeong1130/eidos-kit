# Failure knowledge contract

Reusable failures are stored as individual records under `.agents/failures/YYYY/`. Do not load the
entire history. Select records by the active route's failure tags, then prefer current code and tests,
the active Work, retained evidence, and finally failure records. A failure record is a prevention aid,
not proof that the current implementation is correct.

When Eidos is enabled, record a concrete failure in Work first and promote only a reusable lesson.
Use `.agents/tools/harness.py failure search` and `failure validate`; do not build a manual catalog.
