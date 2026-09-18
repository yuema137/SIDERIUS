# Typed artifact handoffs

These are existing functions in `agent.schemas.protocols`. The table maps
compatible evidence, not a prescribed execution sequence. A caller may hold
several outputs, select applicable evidence or invoke a capability repeatedly.
The target's full input contract still applies after a projection. When a listed
protocol covers a transfer, use it before caller-owned adjustments; do not
manually recreate its field mapping. This also applies to recovery from saved
native output. Direct input construction remains appropriate for supplied
candidates with no native upstream output or fields the protocol does not carry.

| Module and function | Input → result | Caller responsibility |
| --- | --- | --- |
| `ml_result_interp_to_ml_model_propose.local_full_context` | InterpretationOutput + storage + optional context → ProposalInput | Populate the task/forward contract, routing and constraints that the projection does not supply |
| `ml_model_propose_to_ml_model_impl.local_full_spec` | ProposalOutput + storage + optional task reference → ImplementorInput | Supply task I/O context and disjoint attempt paths; preserves candidate identity, output type and custom loss |
| `ml_model_impl_to_ml_model_valid.local_all_fields` | ImplementorOutput + storage + provider/model → ValidatorInput | Preserves immediate upstream candidate and I/O contract; populate additional enabled context explicitly |
| `ml_model_valid_to_ml_model_tune.local_validated_model` | ValidatorOutput + ProposalOutput + storage + explicit tuning context → HyperparamTuningInput | Check `passed` before calling; preserve candidate linkage and supply real task/resource/Health bindings |
| `ml_model_tune_to_ml_result_interp.local_all_records` | HyperparamTuningOutput + storage → InterpretationInput | Uses native record/metric reconciliation; carry additional task interpretation context |
| `interpreter_to_ml_literature_review.local_typed_evidence` | InterpretationOutput → recipient-specific evidence | Use it in LiteratureReviewInput with permitted sources and task description |
| `ml_literature_review_to_ml_model_propose.local_typed_evidence` | LiteratureReviewOutput + keyword proposal_input → rebuilt ProposalInput | Attaches the typed literature projection; preserves citations and confidence |
| `ml_literature_review_to_ml_model_propose.local_all_channels` | LiteratureReviewOutput → protocol channel mapping | This mapping is a protocol projection, not permission to execute raw LLM dictionaries |
| `interpreter_to_data_analysis.local_analysis_input` | InterpretationOutput + explicit analysis context → DataAnalysisInput | Requires an actual analysis_brief on the interpretation plus authorized assets, envelope, policy and executable task capability |
| `data_analysis_to_ml_model_propose.local_typed_evidence` | DataAnalysisReport + keyword report_ref and proposal_input → rebuilt ProposalInput | Requires a CertifiedArtifactRef; only enabled, authorized findings may cross |
| `data_analysis_to_ml_literature_review.local_typed_evidence` | DataAnalysisReport → literature evidence | Preserve certified source references and scope |
| `ml_literature_review_to_data_analysis.local_typed_evidence` | LiteratureReviewOutput → analysis evidence | Literature is context, not a replacement for measured data |

Inspect an exact installed signature, including optional arguments, before
using a projection with rich context:

```python
import inspect
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_validated_model
print(inspect.signature(local_validated_model))
```

For example, this performs one proposal-to-implementation projection without
calling a provider or executing generated code:

```python
from pathlib import Path
from agent.schemas.proposal import ProposalOutput
from agent.schemas.implementor import ImplementorInput
from agent.schemas.storage import StorageConfig
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec


def implementation_request(proposal_path, storage_json, task_ref, task_fields):
    proposal = ProposalOutput.model_validate_json(Path(proposal_path).read_text())
    storage = StorageConfig.model_validate_json(storage_json)
    projected = local_full_spec(proposal, storage, task_composition_ref=task_ref)
    # task_fields contains the actual contract and paths from the run declaration.
    # Revalidate the combined input; do not bypass validation with model_copy.
    return ImplementorInput.model_validate(projected.model_dump() | task_fields)
```

The caller must not use task_fields to replace the proposal's identity or
scientific output contract. Read the target field inventory for exact names.
Recovery can load the caller's persisted native output and apply the same
projection. Peers do not scan another node's storage to choose a latest result.
The `database_*` alternatives are unimplemented placeholders at this revision.

### Restored implementation artifacts

A saved `ImplementorOutput` still uses the implementation-to-validation protocol.
Path relocation does not require a replacement mapping. Verify restored files
against the supplied artifact identities first; retain the original output as
provenance. Then project its validated native object and revalidate only the
authorized path changes:

```python
from pathlib import Path
from agent.schemas.implementor import ImplementorOutput
from agent.schemas.validator import ValidatorInput
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields


def restored_validation_request(output_path, storage, verified_paths, provider, model_id):
    allowed = {"model_file_path", "test_file_path", "description_file_path"}
    if set(verified_paths) - allowed:
        raise ValueError("Unexpected restoration field")
    output = ImplementorOutput.model_validate_json(Path(output_path).read_text())
    projected = local_all_fields(output, storage, llm_provider=provider,
                                 llm_model_id=model_id)
    return ValidatorInput.model_validate(projected.model_dump() | verified_paths)
```

`verified_paths` is caller-supplied restoration context, not a new schema or an
automatic integrity check. It must not conceal changed artifact contents. A
restored request is not a new validation verdict; old results remain associated
with the artifacts and context actually checked.

Fan-in does not establish comparable metrics or valid lineage. Preserve native
score specifications, Health eligibility and statuses; use task-owned metric
ordering rather than hand-averaging scores from unrelated records.
