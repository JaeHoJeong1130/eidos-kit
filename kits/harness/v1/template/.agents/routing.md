# Harness routing

| Route | Use when | Risk | Rubrics | Failure tags |
| --- | --- | --- | --- | --- |
| read-only | Explain, inspect, diagnose, or advise without writes | R0 | none | relevant area |
| change | Make a bounded internal change | R1 | common-change | area and component |
| public-contract | Change an API, schema, CLI, or shared behavior | R2 | common-change, public-contract | contract and component |
| artifact-or-model | Change model, artifact, evidence, or reproducibility boundaries | R2 | common-change, artifact-or-model | artifact, model, evidence |
| release-or-external | Push, release, deploy, delete, or affect an external system | R3 | common-change, release-or-external | release, external, safety |

Project routes may extend this exact five-column schema under `.agents/routes/`.
