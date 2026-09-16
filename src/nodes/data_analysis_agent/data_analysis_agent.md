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
| `generated_skill_registry` | `GeneratedExperimentSkillRegistryRef` or `None` | No | `None` | Exact run-scoped generated-skill snapshot explicitly supplied by the caller. |
| `allow_generated_skill_promotion` | boolean | No | `False` | Allows one bounded reuse decision after successful generated-program execution; grants no data authority. |
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
| `skill_result_summaries` | tuple of `SkillResultSummary` | Legacy-named bounded summaries of full append-only certified analysis-execution results. |
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
certified artifacts, and bounded `report.json` / `report.md`. When a capability
gap requires custom analysis, exact generated source and its validated
declaration are stored content-addressed below `generated_analysis/` before the
final executable plan is created. Materialization copies and staging
directories are removed after the bounded worker exits.
Promoted skill source/declarations and immutable registry manifests live below
`{workspace}/data_analysis/{run_name}/generated_skill_registry/`; the next
request sees them only when its typed input carries the exact registry ref
returned in report provenance.

## Key behavioral notes

- Discovery reads manifests only. Selected implementations are imported in a bounded worker after interface resolution.
- Reference/configured skills are preferred when they cleanly answer a question. A real toolbox gap may instead trigger a separate source-generation stage. That stage validates and persists one immutable `GeneratedAnalysisProgram`; only then may the final `AnalysisPlan` reference its exact `GeneratedProgramIdentity`. Resume never regenerates equivalent source.
- `AnalysisPlan.invocations` is a discriminated union of trusted skill invocations, already-persisted one-off generated-program invocations, and discovered generated-experiment-skill invocations. Pre-union persisted skill wire forms remain readable.
- Promotion is optional and explicit. A bounded structured decision may add a completed program to an immutable run-scoped registry. The resulting local skill exposes a normal `SkillCard`, `SkillDeclaration`, and resolved parameter interface, but its exact originating program identity remains the execution authority. No directory scanning or mutable global registry is used.
- Planning keeps `RequestedInformation` strict: only `metadata` may name explicit `fields`; `data`, `target`, `prediction`, `residual`, and `identity` use no fields. One bounded repair may delete an illegal non-metadata `fields` value because it carries no access authority, but it may not change the information class, metadata field identity, binding, format, sampling, parameters, or other plan semantics.
- A skill receives only already-authorized `MaterializedAnalysisView` content and cannot resolve asset IDs or scan the workspace.
- A generated program receives the same authorized materializations through a narrow JSON/NPZ runner ABI. It proposes a bounded `SkillPayload`; the trusted parent validates measurement semantics, certifies effective coverage and artifacts, records resources, and constructs the canonical result. Source code is never itself scientific evidence.
- Execution origin selects the trust path. `reference_skill` and `configured_external_skill` use the operator-approved skill worker. `generated_program` and `generated_experiment_skill` use `AnalysisCodeSandbox`; promotion never converts code into trusted code and no ordinary-subprocess fallback exists. The result/report surfaces retain the exact origin and mutually exclusive skill or generated-program identity.
- Full results remain append-only; the canonical report contains bounded summaries and certified references.
- Existing predictions, residuals, histories, and evaluation artifacts may be analyzed when supplied and authorized.
- Active historical inference is an injected capability. A validated plan must identify the immutable `TrainedModelArtifact`, exact input binding, split, selection, prediction contract and evaluation configuration. The inference worker receives no target; target-dependent diagnostics use a separate authorized materialization.
- `TrainedModelArtifact` is descriptive and immutable. It records checkpoint/config/plugin/construction/I/O identities but carries no Python callable or executable path. The approved inference capability owns reconstruction and emits an executor-certified receipt.
- Skill packs are trusted operator-approved Python code. Their existing process limits provide resource containment, not a security sandbox.
- Generated analysis is untrusted. The Linux v1 sandbox requires both `unshare` user/network namespaces and Bubblewrap. It exposes only the exact Python runtime, dependency environment, runner, immutable source/request, read-only authorized materializations, a private `/tmp`, and the writable invocation output directory. It clears inherited credentials/environment, omits the checkout and user home, creates PID/IPC/UTS namespaces, denies external network connectivity in the qualified runtime, applies CPU/address-space/file/process limits, monitors output count/bytes, and kills the process group on exit or timeout. Capability probing is mandatory and failure is closed. Local socket creation is not itself treated as network access; qualification verifies that an outbound connection from the isolated network namespace cannot be established.
- The v1 sandbox does not claim a seccomp filter, cgroup accounting, arbitrary dependency installation, GPU access, or protection on hosts whose namespace/Bubblewrap probe fails. `RLIMIT_AS` bounds virtual address space, while RSS is observed separately; CPU time is not yet measured per process group. Linux `RLIMIT_NPROC` counts host-UID tasks (including threads) rather than namespace-local processes, so the executor preserves the observed pre-launch UID task baseline and permits only a fixed additional task headroom; process-group cleanup remains mandatory. One-off generated programs may consume ordinary authorized materializations only and cannot request historical inference.

## Dependencies

- **LLM**: three bounded schema-validated stages in a skill-only run: candidate selection, executable planning, and report synthesis. A generated-program run adds one bounded schema-validated source/declaration stage before executable planning. When promotion is explicitly enabled and a generated program completed, one bounded promotion decision is added; reuse does not regenerate source.
- **GPU**: optional. An enabled skill or caller-injected historical-inference capability may use one only within the caller's resource envelope.
- **External services**: none beyond the configured LLM provider; task data remain behind `TaskAnalysisCapability`.
