# Public contract rubric

| Blocking | Criterion | Evaluation | Required evidence | N/A condition |
| --- | --- | --- | --- | --- |
| yes | Compatibility is explicit | Compare all consumers and versions | consumer matrix and tests | new private interface |
| yes | Invalid input fails closed | Exercise malformed and boundary values | behavioral regression | no external input |
| yes | Migration is recoverable | Fault-inject upgrade or conversion | rollback evidence | no persisted prior version |
