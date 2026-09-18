# Model-output retention

Per-sample predictions and task deliverables are temporary execution data. A
run keeps its trained models, aggregate scores, Health verdicts, bounded
analysis evidence and receipts whether or not it keeps those large outputs.

## One policy, two producers

`retain_model_outputs` is the run-wide switch. Its default is `false`. A
standalone Data Analysis call has the same field on `DataAnalysisInput`; the
reference workflow transports the one launch value to both Data Analysis and
the tuner. The resolved value participates in the run lock and the Analysis
input identity, so a resumed run cannot silently reverse output lifetime.

| Producer | Last consumer before retirement | Retained evidence |
|---|---|---|
| Ordinary task inference | scoring and round Health | attempt record and `model_output_retention_receipts.jsonl` |
| Historical-model inference requested by Data Analysis | the specific analysis action | inference receipt, SkillResult, DataAnalysisReport and `prediction_retention_receipts.jsonl` |

`--retain_model_outputs` explicitly retains the output bytes. The legacy
`--cleanup_denoised` flag remains accepted as a compatibility request for
cleanup, but cleanup is already the default; using both flags is refused.
The chain wrapper's old `--no-cleanup_denoised` spelling is an explicit
retention request and is translated into `--retain_model_outputs` on the
child argv. The Slurm wrapper does not inject cleanup over that request.
Neither flag controls training-original checkpoint or TrainedModelArtifact retention. Neither
grants Data Analysis access to ground truth or previously saved outputs.

## Ordinary task outputs

An operator-approved task implementation may implement the optional
`TaskOutputArtifactCapability.enumerate_output_artifacts` method. Given an
`EvaluationReadRequest` naming the output root and exact run, experiment
attempt and model, it returns a typed `TaskOutputArtifactInventory` of paths
relative to that root. It must include every per-sample output for this
attempt, including sidecars and partial files, and exclude checkpoints,
source data and other attempts' outputs. An empty inventory is valid when
inference produced no files.

The framework verifies the returned attempt identity, rejects traversal and
symlinks, requires regular files, hashes their bytes and deletes only listed
files when retention is off. It does not discover a composed task's outputs
by globbing its workspace. A missing or invalid inventory creates a typed
refusal and stops the run as an infrastructure condition; it is never a
candidate/model failure. The task declaration is trusted plugin code, not a
security sandbox. Containment checks protect against mistakes in its path
inventory, but cannot independently prove the task's ownership claim.

An uncomposed indexed legacy run uses its existing deliverable-naming
authority's *attempt-scoped* pattern as a compatibility inventory. The former
experiment-wide cleanup glob could match another model under the same
experiment ID and is not used by the new retention path.

The receipt stores exact relative paths, SHA-256 digests, byte counts and
`retained`/`retired` dispositions. A cleanup refusal or failure is visible
even if inference or scoring had already failed. Scoring and Health consume
outputs before this finalization; no output is deleted before those consumers
return or fail.

## Historical predictions and resume

Historical inference writes an exact certified `prediction.npz` under its
own execution identity. The consuming analysis action can cite only its
certified SkillResult, never generated source or an unverified prediction
file. After the action returns, the injected inference capability verifies
the prediction digest and either retains or retires that exact file. It
never touches the source checkpoint or model artifact. Partial outputs from
a failed inference worker are discarded before a failed receipt is returned.

When a prediction is retired, the capability keeps the inference receipt and
an explicit `prediction_retention.json` tombstone. A completed report resumes
from persisted certified results. A replay of the *same incomplete action*
cannot misread the missing prediction as a cache hit: it receives the typed
`inference_prediction_retired` refusal and needs a new invocation identity
to recompute. An invalid or missing tombstone yields the separate
`inference_identity_incomplete` refusal. No path silently regenerates code,
model outputs or analysis evidence under an existing execution identity.

## Limits and integration rule

These receipts certify what the local executor observed and retired. They do
not make a task plugin untrusted, authorize new data, or prove that an external
process could not copy an output beforehand. A composed scientific task must
provide its own exact artifact inventory before the default-delete policy can
be used in an effectful run. The task's existing deliverable codec and
evaluation semantics remain the scientific authorities; inventory only
describes the lifetime of their output files.
