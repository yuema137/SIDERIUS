# data-analysis: native schema field inventory

Reference snapshot: SIDERIUS `1c68bc81d7e44bbdc6e03a445a8422c3f77f45ff`. Derived from the actual
Pydantic `model_fields`; the installed classes remain the execution authority.
Defaults below describe the generic API, not permission to override the
frozen task, information treatment, budget, or candidate-selection contract.
Custom validators can impose cross-field requirements not expressible by a
required-field flag. Use `model_validate` / `model_validate_json` before execution.

Return to the [capability guide](../agents/data-analysis.md).

## DataAnalysisInput

Import: `agent.schemas.data_analysis.DataAnalysisInput`.

| Field | Python type | Required / default | Constraints | Meaning |
| --- | --- | --- | --- | --- |
| schema_version | Literal[1] | 1 | [] |  |
| request_id | str | required | [StringConstraints(strip_whitespace=True, to_upper=None, to_lower=None, strict=None, min_length=1, max_length=None, pattern=None)] |  |
| task_context | agent.schemas.data_analysis.context.AnalysisTaskContext | required | [] |  |
| analysis_brief | agent.schemas.data_analysis.context.AnalysisBrief | required | [] |  |
| available_assets | tuple[agent.schemas.data_analysis.assets.AnalysisAsset, ...] | required | [] |  |
| declared_scope | agent.schemas.data_analysis.source_scope.DeclaredAnalysisScope | required | [] | One caller-declared ceiling over raw input and ordered prior models. |
| prior_evidence | tuple[agent.schemas.data_analysis.context.PriorEvidenceRef, ...] | () | [] |  |
| literature_evidence | agent.schemas.data_analysis.context.DataAnalysisLiteratureEvidence \| None | None | [] | Optional source-backed hypotheses and caveats supplied by a workflow edge. Reasoning context only; it cannot grant assets, information or operations. |
| access_policy | agent.schemas.data_analysis.access.AnalysisAccessPolicy | required | [] |  |
| resource_envelope | agent.schemas.data_analysis.resources.AnalysisResourceEnvelope | required | [] |  |
| allowed_skill_packs | tuple[agent.schemas.data_analysis.context.SkillPackRef, ...] | required | [] |  |
| generated_skill_registry | agent.schemas.data_analysis.generated_skill.GeneratedExperimentSkillRegistryRef \| None | None | [] |  |
| allow_generated_skill_promotion | bool | False | [] |  |
| human_advice | str \| None | None | [] |  |
| source_scope | agent.schemas.data_analysis.source_scope.AnalysisSourceScope \| None | None | [] | Exact resolved lock; absent means automatic choice under declared_scope. |
| retain_model_outputs | bool | False | [Strict(strict=True)] | Retain per-sample historical predictions after their analysis action. False retires exact output bytes; neither value changes source authorization. |
| storage | agent.schemas.storage.StorageConfig | required | [] |  |
| caller | agent.schemas.data_analysis.common.CallerIdentity | required | [] |  |

Read the complete nested JSON Schema from the same public class:

```python
import json
from agent.schemas.data_analysis import DataAnalysisInput
print(json.dumps(DataAnalysisInput.model_json_schema(), indent=2))
```

This inspection uses the selected installation and does not instantiate an
agent or call a model provider. It does not grant access to a dataset.

## DataAnalysisReport

Import: `agent.schemas.data_analysis.DataAnalysisReport`.

| Field | Python type | Required / default | Constraints | Meaning |
| --- | --- | --- | --- | --- |
| schema_version | Literal[1] | 1 | [] |  |
| report_id | str | required | [StringConstraints(strip_whitespace=True, to_upper=None, to_lower=None, strict=None, min_length=1, max_length=None, pattern=None)] |  |
| analysis_attempt_id | str | required | [StringConstraints(strip_whitespace=True, to_upper=None, to_lower=None, strict=None, min_length=1, max_length=None, pattern=None)] |  |
| input_digest | str | required | [StringConstraints(strip_whitespace=None, to_upper=None, to_lower=None, strict=None, min_length=None, max_length=None, pattern='^[0-9a-f]{64}$')] |  |
| plan_ref | agent.schemas.data_analysis.common.CertifiedArtifactRef | required | [] |  |
| analysis_scope | tuple[agent.schemas.data_analysis.assets.LegacyPartitionScope \| agent.schemas.data_analysis.assets.TaskOpaqueScopeRef \| agent.schemas.data_analysis.assets.ArtifactIntrinsicScope, ...] | required | [] |  |
| executive_summary | str | required | [StringConstraints(strip_whitespace=True, to_upper=None, to_lower=None, strict=None, min_length=1, max_length=None, pattern=None)] |  |
| question_outcomes | tuple[agent.schemas.data_analysis.report.QuestionOutcome, ...] | required | [] |  |
| assets_inspected | tuple[Annotated[str, StringConstraints(strip_whitespace=True, to_upper=None, to_lower=None, strict=None, min_length=1, max_length=None, pattern=None)], ...] | required | [] |  |
| source_scope | agent.schemas.data_analysis.source_scope.AnalysisSourceScope \| None | None | [] |  |
| findings | tuple[agent.schemas.data_analysis.report.DataFinding, ...] | required | [] |  |
| skill_result_summaries | tuple[agent.schemas.data_analysis.report.SkillResultSummary, ...] | required | [] |  |
| skill_result_refs | tuple[agent.schemas.data_analysis.report.CertifiedResultRef, ...] | required | [] |  |
| artifacts | tuple[agent.schemas.data_analysis.common.CertifiedArtifactRef, ...] | () | [] |  |
| modeling_relevance | tuple[Annotated[str, StringConstraints(strip_whitespace=True, to_upper=None, to_lower=None, strict=None, min_length=1, max_length=None, pattern=None)], ...] | () | [] |  |
| limitations | tuple[agent.schemas.data_analysis.report.ReportLimitation, ...] | () | [] |  |
| unresolved_questions | tuple[Annotated[str, StringConstraints(strip_whitespace=True, to_upper=None, to_lower=None, strict=None, min_length=1, max_length=None, pattern=None)], ...] | () | [] |  |
| resource_usage | agent.schemas.data_analysis.report.AnalysisResourceSummary | required | [] |  |
| provenance | agent.schemas.data_analysis.report.DataAnalysisReportProvenance | required | [] |  |

Read the complete nested JSON Schema from the same public class:

```python
import json
from agent.schemas.data_analysis import DataAnalysisReport
print(json.dumps(DataAnalysisReport.model_json_schema(), indent=2))
```

This inspection uses the selected installation and does not instantiate an
agent or call a model provider. It does not grant access to a dataset.
