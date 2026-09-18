# Enabled capabilities and authorized evidence

Read the workspace `SIDERIUS-RUN.md` for the active task instructions,
capability enablement, evidence sources, model routing and information-access
policy. This generic skill defines no experiment arms or retrieval policy.
Interface availability does not authorize invocation or access to data.

| Material | Source of authority |
| --- | --- |
| These neutral interface descriptions | Pinned SIDERIUS classes and public contracts |
| Scientific instructions and initial advice | Separately identified task and permitted advice artifacts |
| Measured findings and run history | Authorized output artifacts with scope, provenance and native status |

## Preserve context provenance when building requests

| Context | Native destination and source |
| --- | --- |
| Task instructions and declared I/O | `task_description` / task blocks where the recipient exposes them; the declared `forward_contract` or `model_io_contract` and native task binding where applicable |
| Candidate specification | Model description, mathematical definition and configuration from the supplied proposal or specification |
| Initial human advice | `human_advice` only from a separately authorized human-advice artifact; leave absent when none is supplied or the run disables it |
| Upstream agent guidance | `expert_advice` only from an authorized upstream typed artifact or native handoff, preserving its actual provenance |
| Literature / measured analysis | Their dedicated typed evidence projections, with authorized scope and references |

Do not put ordinary task prose, your own instructions or a rewritten model
specification into `human_advice` or `expert_advice` merely because the recipient
lacks a general-purpose context field. For example, ValidatorInput has no
`task_description`: carry the candidate specification and `model_io_contract`,
use the supported task binding, and keep remaining orchestration instructions
in caller context. If required context cannot be represented, report that exact
interface gap instead of relabeling its source.

An upstream native `expert_advice` artifact is not initial human advice. An
initial-advice-off condition does not by itself erase guidance produced by an
authorized agent within this run; use the declared treatment and typed handoff.

A disabled capability must not contribute findings through another input field,
cache, prior-run workspace or registry. Optional schema fields are not an
information-access grant. Omitting a specialized analysis capability does not
itself prohibit ordinary reasoning over otherwise authorized evidence. Apply
the actual run policy rather than guessing from an experiment name.

Where a common baseline package is supplied, keep its files and provenance
unchanged. An added run descriptor identifies the active condition; it must not
silently relabel an older receipt or rewrite the common task. Conflicting
scientific scopes require an operator decision outside this toolkit.

All calls, custom tooling, evaluation, failures, retries and controller reasoning
consume the run's declared resources and continuing clock. The toolkit creates
no extra budget. The task's evaluator owns final eligibility and submission.
