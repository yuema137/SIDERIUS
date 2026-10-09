# Task-owned candidate probe inputs

## Scope and ownership

`task_model_probe` resolves small, synthetic inputs for candidate forward and
gradient checks. `task_model_validation` applies those checks and transports
setup failures across generated pytest subprocesses. Neither helper trains,
reads datasets, computes scientific scores, or changes experiment budgets.

A task data-path implementation may expose:

```python
def model_validation_input(self, request: ModelProbeRequest) -> torch.Tensor:
    ...

# Optional fixture recipe, not a training batch setting:
model_validation_batch_sizes = (1, 2)
```

The provider must produce deterministic, data-free CPU inputs satisfying the
task's semantic constraints. It receives the validated model I/O contract,
concrete input shape and canonical Torch dtype name. It must return a finite,
strided tensor of exactly that shape and dtype. Framework checks establish
structural validity; the task author owns semantic validity. No raw dataset,
labels, model instance, or physical data directory is supplied. Returned values
are detached and cloned before candidate execution.

## Selection and identity

Only an explicitly callable `model_validation_input` enables this path. An
absent provider preserves legacy probe recipes, generated tests and prompt
text. A present, non-callable provider is a setup failure.

`build_task_composition_ref` projects `ModelProbeContext` from the composed task:
absolute manifest locator, semantic fingerprint and data-path ID. Implementor
outputs and the implementor-to-validator protocol carry it explicitly; generated
tests and isolated workers serialize it. Absent contexts are omitted from
serialized records. The context is not model-generated configuration.

The existing composer resolves the provider and verifies the composition
fingerprint, data-path identity and model I/O contract. Captured code packages
remain bound during provider lookup and execution, including lazy helper imports.
Full run/data bindings are not installed for a synthetic input. Keep the task
manifest and its declared sources available when rerunning generated tests;
identity drift fails closed instead of selecting current mutable code silently.

Batch cases default to 1 and 2. The optional `model_validation_batch_sizes`
sequence must be nonempty and contain strictly positive integers, excluding
booleans. It supplies concrete cases for constraints that cannot be inferred,
such as a task predicate. Fixed batch dimensions take precedence. Allowed values
and a range's lower integer bound may supply additional candidate sizes; every
candidate is resolved by the existing `train_config.batch_size` parameter-rule
owner. Exact rules can replace a suggestion. Resolved sizes are deduplicated.
If no suggested case is accepted, selection fails with guidance to declare
small legal cases; it does not search arbitrary sizes or claim the task has no
legal batch. This is probe coverage, not exhaustive validation of all batches.

Other geometry uses the existing `model_io_probe_skill`: fixed dimensions and
candidate temporal extent retain their existing meaning. This capability does
not override tensor contracts or authorize arbitrary model dimensions.

## Consumers and failures

The implementor smoke check, generated pytest and direct/isolated validator
checks share the same provider and geometry selection. Smoke uses evaluation
mode without gradients; validator/generated pytest use training mode and require
a successful backward pass. Finite output and the expected output shape are
required. These checks do not certify model quality or resource suitability.

`ModelProbeSetupError` identifies provider, declaration or source-identity
failures. It escapes model repair and validator LLM review, bypasses proposal
retries, and uses the existing workflow contract-failure halt. Pytest publishes a
structured parent-owned failure report; the isolated worker returns a typed
setup-error field. Neither parent infers this class by parsing stderr.

Candidate output-declaration, forward, output-shape and gradient errors remain
candidate verdicts. They must not be relabeled as broken task setup. Existing
code-package integrity failures retain their fail-closed behavior.

## Validation

`tests/unit/agent/test_task_model_probe.py` exercises constrained probability and
ordered inputs, both subprocess consumers, malformed providers, source identity,
captured helper imports, explicit predicate batches and protocol transport.
The implementor regression checks that setup failure cannot spend another repair
request. Existing generated-artifact and prompt goldens cover the absent-provider
path. Scientific fixtures and historical reproduction configuration belong in
siderius-exp; this interface contains no task-specific rules.
