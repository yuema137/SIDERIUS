# DataAnalysisAgent

> Selects and executes authorized scientific-analysis skills under a bounded resource envelope, then returns a structured `DataAnalysisReport`.

## Position in the pipeline

- **CLI entry**: **absent** — standalone callers use the Python capability API because task-owned materialization is an executable protocol object, not an arbitrary filesystem convention.
- **Upstream**: any caller that can construct `DataAnalysisInput`; workflow-owned edges may combine an Interpretation-produced `AnalysisBrief` with optional Literature Review evidence. The node has no knowledge of workflow order.
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
| `declared_scope` | `DeclaredAnalysisScope` | Yes | — | Task/caller-declared raw-input assets and ordered certified prior models; a ceiling, not an access grant. |
| `prior_evidence` | tuple of `PriorEvidenceRef` | No | `()` | Explicitly referenced prior evidence. |
| `literature_evidence` | `DataAnalysisLiteratureEvidence` or `None` | No | `None` | Source-backed hypotheses/caveats supplied by a typed workflow edge. Reasoning context only; it grants no asset, information, skill or preprocessing authority. |
| `access_policy` | `AnalysisAccessPolicy` | Yes | — | Split-, information-, and field-level anti-leakage authority. |
| `resource_envelope` | `AnalysisResourceEnvelope` | Yes | — | Overall deadline, per-skill timeout, device, memory, and sampling policy. |
| `allowed_skill_packs` | tuple of `SkillPackRef` | Yes | — | Caller-approved, content-pinned packs available for discovery. |
| `generated_skill_registry` | `GeneratedExperimentSkillRegistryRef` or `None` | No | `None` | Exact run-scoped generated-skill snapshot explicitly supplied by the caller. |
| `allow_generated_skill_promotion` | boolean | No | `False` | Allows one bounded reuse decision after successful generated-program execution; grants no data authority. |
| `human_advice` | string or `None` | No | `None` | Auditable priorities or scope guidance; grants no data access. |
| `source_scope` | `AnalysisSourceScope` or `None` | No | `None` | One resolved run-wide raw-input/model scope. `None` allows automatic choice only within `declared_scope`; a lock narrows that ceiling. |
| `retain_model_outputs` | boolean | No | `False` | Output lifetime only. Historical predictions generated for an action are retired after its consumer unless explicitly retained; this does not change source authorization. The value participates in the input/plan identity. |
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
| `source_scope` | `AnalysisSourceScope` or `None` | Exact effective raw-input/model scope echoed beside actual inspected assets. |
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

The standalone capability remains a Python API because materialization is an
executable protocol object, not a file path. The fixed workflow accepts an
inline `--analysis_source_prompt` string; no advice file or YAML edit is needed.
The accepted, inspectable syntax is `auto` or one lock of the form
`lock: raw=<asset IDs|all>; models=<all|none|last:N|last_rounds:N|ids:IDs>`. The raw IDs
and model IDs must already be in the caller's declaration. For example:

```text
--analysis_source_prompt "lock: raw=validation-input; models=last_rounds:2"
```

The scope never includes ground truth or a previously saved prediction dataset.
An eligible prior model may process explicitly bound raw input; the resulting
prediction is transient evidence, not another selectable source. `last:N`
selects the most recent N certified models; `last_rounds:N` selects models
trained in the previous N workflow iterations, counting an iteration with no
model as a round. The latter requires a caller-declared chronological iteration
history; the fixed workflow supplies it from its own iteration sequence.
Absent/`auto` and `models=all` retain all eligible prior models. The workflow
certifies each prior artifact against its exact tuning record, task composition,
and current chain workspace; the model's training iteration need not equal the
current analysis iteration. Unknown IDs and ambiguous directives fail closed.
AnalysisAccessPolicy independently checks
the split, operation and concrete metadata fields; neither the prompt nor
literature/advice grants access. Online material is cited reasoning context,
not implicit data or sandbox network access.
Task-certified model-compatible input views may inherit a selected raw input
only when they are already declared and provenance names that exact parent.

### CLI arguments

Fixed-workflow entry points accept `--analysis_source_prompt`. Standalone callers
may use `agent.data_analysis.source_scope.apply_source_prompt(inp, prompt)` or
construct a validated `DataAnalysisInput.source_scope` directly; both routes use
the same plan-resolution and materialization guards.

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
`inference_receipts.jsonl` and `prediction_retention_receipts.jsonl` when historical inference is requested, immutable
certified artifacts, and bounded `report.json` / `report.md`. When a capability
gap requires custom analysis, exact generated source and its validated
declaration are stored content-addressed below `generated_analysis/` before the
final executable plan is created. Materialization copies and staging
directories are removed after the bounded worker exits.
Promoted skill source/declarations and immutable registry manifests live below
`{workspace}/data_analysis/{run_name}/generated_skill_registry/`; the next
request sees them only when its typed input carries the exact registry ref
returned in the prior report's provenance. The fixed workflow restores that ref only from an
explicitly committed prior iteration in the same chain workspace, verifies its
content, and passes it through the Interpreter-to-Analysis typed adapter.
An additional promotion copies verified prior program content into the new
iteration's registry before publishing a new immutable snapshot; it never
mutates the prior registry. Standalone callers may pass the same typed ref
directly.

## Key behavioral notes

- Discovery reads manifests only. Selected implementations are imported in a bounded worker after interface resolution.
- Reference/configured skills are preferred when they cleanly answer a question. A real toolbox gap may instead trigger a separate source-generation stage. That stage validates and persists one immutable `GeneratedAnalysisProgram`; only then may the final `AnalysisPlan` reference its exact `GeneratedProgramIdentity`. Resume never regenerates equivalent source.
- `AnalysisPlan.invocations` is a discriminated union of trusted skill invocations, already-persisted one-off generated-program invocations, and discovered generated-experiment-skill invocations. Pre-union persisted skill wire forms remain readable.
- Promotion is optional and explicit. A bounded structured decision may add a completed program to an immutable run-scoped registry. The decision sees the exact verified declaration and complete source (at most 24 KiB); larger programs remain one-off rather than being promoted from a truncated preview. The review asks whether the operation is generic across unrelated datasets, not merely useful again on the present task. This is an LLM judgment, not proof of scientific correctness. The resulting local skill exposes a normal `SkillCard`, `SkillDeclaration`, and resolved parameter interface, but its exact originating program identity remains the execution authority. No directory scanning or mutable global registry is used.
- Planning keeps `RequestedInformation` strict: only `metadata` may name explicit `fields`; `data`, `target`, `prediction`, `residual`, and `identity` use no fields. Each binding must include its selected input slot's required information and may add only that slot's declared optional information or validated invocation-selected metadata. Split-level target visibility does not make target valid for a data-only slot. One bounded repair may delete an illegal non-metadata `fields` value because it carries no access authority. It may also remove a forbidden seed from deterministic historical inference; a stochastic seed, determinism posture, model, binding, format, sampling, parameters, and other plan semantics remain protected.
- A `SamplingPlan.requested_scope` may retain its existing explicit descriptor or use `{"kind":"certified_asset_scope","asset_id":"..."}`. The latter resolves only after plan binding, from an asset bound by that same invocation (including a declared inference input), and only when every bound asset has the identical certified scope. This avoids asking an LLM to reprint a large task-owned opaque scope. It is not an access grant: materialization receives the resolved exact descriptor and still runs the ordinary scope and information authorization checks. Mixed-scope invocations fail before execution.
- A skill receives only already-authorized `MaterializedAnalysisView` content and cannot resolve asset IDs or scan the workspace.
- A generated program receives the same authorized materializations through a narrow JSON/NPZ runner ABI. It proposes a bounded `SkillPayload`; the trusted parent validates measurement semantics, certifies effective coverage and artifacts, records resources, and constructs the canonical result. Source code is never itself scientific evidence.
- The generated-program v1 runner accepts exactly `siderius.numeric-array.v1` and `siderius.timeseries-array.v1`. Its declaration is validated against those exact IDs before persistence and final planning; the task materializer may still refuse a request, which becomes a typed failed invocation rather than changing formats or aborting the workflow.
- Execution origin selects the trust path. `reference_skill` and `configured_external_skill` use the operator-approved skill worker. `generated_program` and `generated_experiment_skill` use `AnalysisCodeSandbox`; promotion never converts code into trusted code and no ordinary-subprocess fallback exists. The result/report surfaces retain the exact origin and mutually exclusive skill or generated-program identity.
- Full results remain append-only; the canonical report contains bounded summaries and certified references. Its Markdown rendering also lists the bounded certified measurements for each attempted action, including failures, so a human can inspect the quantitative basis without opening every artifact. This display does not turn failed results into findings.
- The run-wide source scope covers authorized raw inputs and certified historical models. Per-sample historical predictions are generated on demand for a consuming action, not treated as a long-lived source inventory. Targets and stored historical outputs do not enter this scope.
- Active historical inference is an injected capability. A validated plan must identify the immutable `TrainedModelArtifact`, exact input binding, split, selection, prediction contract and evaluation configuration. The inference worker receives no target; target-dependent diagnostics use a separate authorized materialization.
- A generated one-off program or promoted experiment-local skill may bind one historical model through `operation="infer"` when its declared slot accepts certified predictions. The trusted inference capability receives the exact authorized raw input and emits a certified transient prediction view; the inference binding exposes only that view to the untrusted analysis sandbox. Generated code never receives the checkpoint, plugin, or private inference-input path. Any separate ordinary data or target input still requires its own declared slot, binding and authorization. The same inference and retention receipts are recorded for trusted and generated consumers.
- After the consuming action, the injected capability verifies and either retains or retires its exact certified prediction according to `retain_model_outputs`; failures are recorded and cannot produce a completed finding. A retirement tombstone prevents a deleted prediction from being mistaken for a resumable cache hit. See [model-output retention](../../../docs/reference/model-output-retention.md).
- In the fixed workflow, an optional caller-owned `historical_inference_base_asset_id` can make prior certified training records available as model assets. The task-owned `TaskHistoricalInferenceInputCapability` derives candidate-compatible inference input geometry from verified model/profile content within the declared base region. This workflow edge only prepares plan-visible assets and a run-bound inference capability; the Data Analysis node still chooses explicit bindings under the same access policy. No artifact is inferred from a legacy checkpoint path.
- The fixed workflow may transport an explicit `data_analysis_enabled` treatment from its launcher. `None` preserves composition behavior, `False` bypasses the Interpreter brief and analysis edge, and `True` requires a composed analysis binding. This is workflow routing only; the standalone Data Analysis input and its authorization contract are unchanged.
- `TrainedModelArtifact` is descriptive and immutable. It records checkpoint/config/plugin/construction/I/O identities but carries no Python callable or executable path. The approved inference capability owns reconstruction and emits an executor-certified receipt.
- Skill packs are trusted operator-approved Python code. Their existing process limits provide resource containment, not a security sandbox.
- Generated analysis is untrusted. The Linux v1 sandbox requires both `unshare` user/network namespaces and Bubblewrap. It exposes only the exact Python runtime, dependency environment, runner, immutable source/request, read-only authorized materializations, a private `/tmp`, and the writable invocation output directory. It clears inherited credentials/environment, omits the checkout and user home, creates PID/IPC/UTS namespaces, denies external network connectivity in the qualified runtime, applies CPU/address-space/file/process limits, monitors output count/bytes, and kills the process group on exit or timeout. Capability probing is mandatory and failure is closed. Local socket creation is not itself treated as network access; qualification verifies that an outbound connection from the isolated network namespace cannot be established.
- The v1 sandbox does not claim a seccomp filter, cgroup accounting, arbitrary dependency installation, GPU access, or protection on hosts whose namespace/Bubblewrap probe fails. `RLIMIT_AS` bounds virtual address space, while RSS is observed separately; CPU time is not yet measured per process group. Linux `RLIMIT_NPROC` counts host-UID tasks (including threads) rather than namespace-local processes, so the executor preserves the observed pre-launch UID task baseline and permits only a fixed additional task headroom; process-group cleanup remains mandatory. Historical-model execution remains outside the sandbox; the sandbox receives only its certified prediction materialization.

## Dependencies

- **LLM**: three bounded schema-validated stages in a skill-only run: candidate selection, executable planning, and report synthesis. A generated-program run adds one bounded schema-validated source/declaration stage before executable planning. When promotion is explicitly enabled and a generated program completed, one bounded promotion decision is added; reuse does not regenerate source.
- **GPU**: optional. An enabled skill or caller-injected historical-inference capability may use one only within the caller's resource envelope.
- **External services**: none beyond the configured LLM provider; task data remain behind `TaskAnalysisCapability`.
