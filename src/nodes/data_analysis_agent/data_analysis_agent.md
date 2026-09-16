# DataAnalysisAgent

> Selects and executes authorized scientific-analysis skills under a bounded resource envelope, then returns a structured `DataAnalysisReport`.

## Position in the pipeline

- **CLI entry**: **absent** — standalone callers use the Python capability API because task-owned materialization is an executable protocol object, not an arbitrary filesystem convention.
- **Upstream**: any caller that can construct `DataAnalysisInput`; the reference workflow uses `local_analysis_input` after interpretation.
- **Downstream**: humans and external orchestrators may consume `DataAnalysisReport` directly; the reference Proposer path uses `local_typed_evidence`.
- **Protocol**: `local_analysis_input` constructs the capability input; `local_typed_evidence` owns the bounded Proposer projection.

## Input

**Schema**: `DataAnalysisInput` in `agent/schemas/data_analysis/context.py`

| Field | Type | Required | Default | Description |
|---|---|:---:|---|---|
| `schema_version` | `Literal[1]` | No | `1` | Public contract version. |
| `request_id` | non-empty string | Yes | — | Stable analysis-attempt identity. |
| `task_context` | `AnalysisTaskContext` | Yes | — | Caller-independent scientific task meaning. |
| `analysis_brief` | `AnalysisBrief` | Yes | — | Questions describing what to investigate, not how to execute. |
| `available_assets` | tuple of `AnalysisAsset` | Yes | — | Safe descriptors and identities only; never bulk content. |
| `prior_evidence` | tuple of `PriorEvidenceRef` | No | `()` | Explicitly referenced prior evidence. |
| `access_policy` | `AnalysisAccessPolicy` | Yes | — | Split-, information-, and field-level anti-leakage authority. |
| `resource_envelope` | `AnalysisResourceEnvelope` | Yes | — | Overall deadline, per-skill timeout, device, memory, and sampling policy. |
| `allowed_skill_packs` | tuple of `SkillPackRef` | Yes | — | Caller-approved, content-pinned packs available for discovery. |
| `human_advice` | string or `None` | No | `None` | Auditable priorities or scope guidance; grants no data access. |
| `storage` | `StorageConfig` | Yes | — | Capability-owned persistence destination. |
| `caller` | `CallerIdentity` | Yes | — | Identity of the workflow, human, orchestrator, or capability making the request. |

## Output

**Schema**: `DataAnalysisReport` in `agent/schemas/data_analysis/report.py`

| Field | Type | Description |
|---|---|---|
| `schema_version` | `Literal[1]` | Public report-contract version. |
| `report_id` | string | Stable report identity. |
| `analysis_attempt_id` | string | Request/attempt that produced the report. |
| `input_digest` | SHA-256 | Canonical input identity. |
| `plan_ref` | `CertifiedArtifactRef` | Persisted validated plan identity. |
| `analysis_scope` | tuple of scope descriptors | Exact requested scopes represented by executed invocations. |
| `executive_summary` | string | Bounded synthesis of the measured evidence. |
| `question_outcomes` | tuple of `QuestionOutcome` | Disposition of every brief question. |
| `assets_inspected` | tuple of strings | Asset identities actually materialized. |
| `findings` | tuple of `DataFinding` | Structured, cited scientific findings. |
| `skill_result_summaries` | tuple of `SkillResultSummary` | Bounded summaries of full append-only results. |
| `skill_result_refs` | tuple of `CertifiedResultRef` | Identities of full result rows. |
| `artifacts` | tuple of `CertifiedArtifactRef` | Certified plots/tables/files produced by skills. |
| `modeling_relevance` | tuple of strings | Scientific relevance statements; never modeling decisions. |
| `limitations` | tuple of `ReportLimitation` | Explicit limitations and affected questions. |
| `unresolved_questions` | tuple of strings | Questions the executed evidence did not resolve. |
| `resource_usage` | `AnalysisResourceSummary` | Attempt count and observed runtime/memory summary. |
| `provenance` | `DataAnalysisReportProvenance` | Input, policy, plan, discovery, and result-set identities. |

## CLI usage

N/A. The v0.1 public standalone surface is the Python API below.

### CLI arguments

None.

## Python API usage

```python
from nodes.data_analysis_agent import DataAnalysisAgent

# `inp` is a validated DataAnalysisInput. `task_capability` implements the
# public TaskAnalysisCapability materialization/export protocol.
report = DataAnalysisAgent(
    task_analysis_capability=task_capability,
    # Optional caller-approved capability for active inference from immutable
    # TrainedModelArtifact descriptors. The analysis agent never loads a
    # checkpoint or resolves a model plugin itself.
    historical_model_inference_capability=historical_inference_capability,
    provider="gemini",
    model_id="gemini-3.1-pro-preview",
).run(inp)
```

## Storage outputs

For local storage, the node writes beneath
`{workspace}/data_analysis/{run_name}/{request_id}/`: `input.json`,
`discovery.json`, `plan.json`, append-only `skill_results.jsonl`, append-only
`inference_receipts.jsonl` when historical inference is requested, immutable
certified artifacts, and bounded `report.json` / `report.md`. Materialization
copies and staging directories are removed after the bounded worker exits.

## Key behavioral notes

- Discovery reads manifests only. Selected implementations are imported in a bounded worker after interface resolution.
- Planning keeps `RequestedInformation` strict: only `metadata` may name explicit `fields`; `data`, `target`, `prediction`, `residual`, and `identity` use no fields. One bounded repair may delete an illegal non-metadata `fields` value because it carries no access authority, but it may not change the information class, metadata field identity, binding, format, sampling, parameters, or other plan semantics.
- A skill receives only already-authorized `MaterializedAnalysisView` content and cannot resolve asset IDs or scan the workspace.
- Full results remain append-only; the canonical report contains bounded summaries and certified references.
- Existing predictions, residuals, histories, and evaluation artifacts may be analyzed when supplied and authorized.
- Active historical inference is an injected capability. A validated plan must identify the immutable `TrainedModelArtifact`, exact input binding, split, selection, prediction contract and evaluation configuration. The inference worker receives no target; target-dependent diagnostics use a separate authorized materialization.
- `TrainedModelArtifact` is descriptive and immutable. It records checkpoint/config/plugin/construction/I/O identities but carries no Python callable or executable path. The approved inference capability owns reconstruction and emits an executor-certified receipt.
- Skill packs are trusted operator-approved Python code. Process limits provide resource containment, not a security sandbox.

## Dependencies

- **LLM**: three bounded schema-validated stages in a normal run: candidate selection, executable planning, and report synthesis.
- **GPU**: optional. An enabled skill or caller-injected historical-inference capability may use one only within the caller's resource envelope.
- **External services**: none beyond the configured LLM provider; task data remain behind `TaskAnalysisCapability`.
