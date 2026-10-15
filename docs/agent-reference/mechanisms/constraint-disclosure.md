# Execution-constraint disclosure

## Scope and owners

`agent.schemas.constraint_disclosure.ConstraintContext` is read-only advisory
context for existing deterministic authorities. It does not resolve parameters,
choose priorities, authorize data access, or enforce constraints. ParameterRules,
task objectives, workflow overrides and execution policy retain those duties.

`workflows.constraint_disclosure.workflow_constraint_context` projects the
launch configuration and task composition. The normal workflow supplies this
context to interpreter, literature review and optional Data Analysis inputs.
Downstream proposal, implementation, validation and tuning still use their
existing input contracts; this shared transport does not yet cover those nodes.

## Payload and meaning

`known_sections` identifies supplied sections of a finite disclosure surface:
`task_rules`, `workflow_rules`, `objective`, `overrides`, `execution`.
A supplied rule/objective section with `None` means no declaration. An omitted
section is unknown, not unrestricted. A known execution section requires an
`ExecutionConstraintFacts` object. Direct callers may provide partial context;
absent context renders an explicit incomplete-information notice. Arbitrary
plugin restrictions are outside the completeness claim.

Task and workflow rules both apply. Exact rules remain locks even if an authored
value already matches. Ranges, allowed sets and registered predicates restrict
choices without choosing a value. Effective baseline values alone do not imply
locks. Operator override projection reuses `frozen_portion_overrides`; it does
not introduce another resolver. Trial portion overrides do not freeze Formal
portions. `formal_training_scope_source` controls training-scope ownership;
Formal evaluation remains operator-owned via `formal_eval_portion`. Time
budgets do not imply a hard kill deadline. Optional `timing` carries the existing
`PlannerTimingContext`; it does not calculate inheritance itself.

The disclosure supplements current-run recommendations. It must not rewrite
historical evidence or source-paper methods. Literature source extraction and
cache consolidation are deliberately excluded: they preserve source facts and
prior findings rather than select current-run interventions. Literature search
and synthesis receive constraints. Interpreter per-model interpretation,
synthesis, vocabulary deduplication and optional analysis-brief generation
receive them. Data Analysis structured generation, repair, planning, synthesis
and generated-skill promotion share the same append path.

## Identity, persistence and historical compatibility

`constraints.disclosure` is an existing-system prompt-rendering boundary. Its
native renderer appends one block; an explicit experiment-owned renderer may
return an empty string, preserving the original prompt bytes. No execution
rule changes when a historical renderer is selected. Rendering identity covers
schemas, templates, affected upstream nodes and the workflow projection.
Analysis-brief receipts hash the final transmitted prompt; changed disclosure
cannot reuse an incompatible brief. Data Analysis input identity includes
present advisory context, so removing it in a renderer alone cannot recover
historical executable plan digests.

`WorkflowLaunchConfig.disclose_execution_constraints` defaults to `True`.
Standard CLI exposes `--disclose_execution_constraints` and
`--no-disclose_execution_constraints`. `False` stops transporting this new
context; deterministic constraints remain enforced. Native prompts still state
that context is incomplete. Exact historical reproduction therefore requires
both an explicit experiment-owned launch configuration disabling transport
and its qualified historical rendering profile. Absent optional contexts are
omitted from serialized inputs. No archived inputs or locks are rewritten.

The selection is carried through the validator-to-tuner protocol and recorded
in the existing canonical run identity. An old lock without this field has
unknown (`None`) selection and cannot silently resume under explicit `True` or
`False`. Use a separately configured new workspace for historical migration.
Changing the selection in an existing new workspace is also rejected.

## Validation boundary

Offline tests capture real node calls, including a schema repair; verify
source-extraction exclusion; compare actual analysis-brief receipt hashes;
exercise context changes on resume; and verify CLI/protocol/lock transport.
Existing enforcement regression tests remain applicable. These tests establish
information transport and deterministic contracts, not LLM compliance or
stochastic scientific-result equality. Historical paper prompt qualification
is maintained by the external experiment compatibility package.
