"""Prompt rendering for the caller-independent Data Analysis capability."""

from __future__ import annotations

import json

from agent.data_analysis.discovery import (
    DiscoveredAnalysisSkill,
    DiscoveredGeneratedExperimentSkill,
    DiscoverySnapshot,
)
from agent.schemas.data_analysis.action_identity import GeneratedProgramIdentity
from agent.schemas.data_analysis.common import canonical_sha256
from agent.schemas.data_analysis.context import DataAnalysisInput
from agent.schemas.data_analysis.generated_program import GeneratedAnalysisProgram
from agent.schemas.data_analysis.generated_skill import GeneratedSkillPromotionDraft
from agent.schemas.data_analysis.plan import AnalysisPlan
from agent.schemas.data_analysis.skills import ResolvedSkillInterface, SkillPayload, SkillResult
from agent.schemas.data_analysis.view_formats import GENERATED_PROGRAM_VIEW_FORMATS_V1


def _json(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")

    def encode_nested(item):
        if hasattr(item, "model_dump"):
            return item.model_dump(mode="json")
        return str(item)

    return json.dumps(value, sort_keys=True, indent=2, default=encode_nested)


def _literature_context_block(analysis_input: DataAnalysisInput) -> str:
    evidence = analysis_input.literature_evidence
    if evidence is None:
        return ""
    return (
        "Literature-derived hypotheses/caveats (reasoning context only; no "
        f"authorization):\n{_json(evidence)}\n\n"
    )


def _source_scope_block(analysis_input: DataAnalysisInput) -> str:
    scope = analysis_input.effective_source_scope()
    return (
        f"Analysis sources: {scope.mode}. This single run-wide scope permits only declared "
        "raw input and immutable prior models, subject to separate access policy. "
        "Ground truth and persisted model outputs are not analysis sources. "
        "Prior models may process authorized raw input to produce transient predictions.\n"
        f"{_json(scope)}\n\n"
    )


def _planning_input(analysis_input: DataAnalysisInput) -> dict:
    payload = analysis_input.model_dump(mode="json")
    # The declaration is a caller-side ceiling and may name locked-out assets.
    # The planner receives only the resolved scope and its filtered descriptors.
    payload.pop("declared_scope", None)
    payload["available_assets"] = [
        item.model_dump(mode="json") for item in analysis_input.planning_assets()
    ]
    payload["source_scope"] = analysis_input.effective_source_scope().model_dump(mode="json")
    return payload


def _source_catalog_block(analysis_input: DataAnalysisInput) -> str:
    return (
        "Source identities visible under this request (not an access grant):\n"
        f"{_json(analysis_input.effective_source_scope())}\n\n"
    )


def render_skill_selection_prompt(
    analysis_input: DataAnalysisInput,
    candidates: tuple[DiscoveredAnalysisSkill, ...],
    *,
    output_schema: dict,
) -> tuple[str, str]:
    system = """Choose how to answer scientific analysis questions using supplied SkillCards and
safe asset descriptors. Prefer a validated skill whenever it cleanly answers the question. If and
only if the toolbox is insufficient or materially awkward, list the exact question IDs requiring
one bounded experiment-local generated program. Generated code grants no additional data access.
You cannot inspect data, invent fields, or use a skill outside the cards. If no requested
question can be addressed legally and meaningfully, return empty skill/program selections
with an explicit non_execution_reason; this reports no evidence and does not grant access.
Otherwise non_execution_reason must be null. Never select irrelevant work just to avoid an
empty selection. Return strict JSON."""
    user = f"""Analysis brief:
{_json(analysis_input.analysis_brief)}

Task context:
{_json(analysis_input.task_context)}

Human advice:
{analysis_input.human_advice or "None"}

{_source_scope_block(analysis_input)}{_literature_context_block(analysis_input)}Resource envelope:
{_json(analysis_input.resource_envelope)}

Safe asset descriptors:
{_json(analysis_input.planning_assets())}

{_source_catalog_block(analysis_input)}Candidate SkillCards:
{_json([item.card for item in candidates])}

Authoritative output JSON schema:
{_json(output_schema)}
"""
    return system, user


def render_analysis_plan_prompt(
    analysis_input: DataAnalysisInput,
    discovery: DiscoverySnapshot,
    selected: tuple[DiscoveredAnalysisSkill, ...],
    interfaces: dict[str, ResolvedSkillInterface],
    generated_programs: tuple[tuple[GeneratedAnalysisProgram, GeneratedProgramIdentity], ...] = (),
) -> tuple[str, str]:
    system = """Produce one executable AnalysisPlan as strict JSON. Use exact IDs, slots,
formats, information classes, metadata fields, parameters, cost hints, and question IDs from the
supplied contracts. Metadata parameters grant no access: the binding must request the exact field.
For each binding, requested_information must include the selected slot's required_information
and may add only information declared by that same slot's optional_information (plus exact
invocation-selected metadata when the slot declares it). The access policy may permit target on
a split, but that does not make target valid for a data-only slot. For a slot requiring only data
with no optional information, request only {"information_class":"data","fields":[]}; do not add
target to that binding. Use a declared target-capable slot if the question needs target evidence.
RequestedInformation.fields is conditional: use explicit names only when information_class is
"metadata". For "identity", "data", "target", "prediction", or "residual", fields must be empty.
Examples: {"information_class":"data","fields":[]} and
{"information_class":"prediction","fields":[]} are valid;
{"information_class":"metadata","fields":["snr"]} is valid; and
{"information_class":"prediction","fields":["prediction"]} is invalid.
For historical-model predictions, bind the trained-model asset with operation="infer"
only to a declared predictions slot. Its requested_information must be exactly
[{"information_class":"prediction","fields":[]}], with one explicit inference_inputs
binding for the authorized raw model input and the model's declared input format/information.
HistoricalInferenceConfiguration with determinism="deterministic" must omit seed or set it to
null; a numeric seed is valid only for determinism="stochastic_seeded". Do not add seed=0 to a
deterministic model just because other analysis actions use a sampling seed.
This also applies to generated programs and generated experiment skills: trusted inference
produces a certified prediction view before untrusted analysis code runs. Generated code must
not load or execute the model itself. At most one inference binding is supported per generated
invocation. Never request metadata fields absent from the split access policy.
Use one invocation-level sampling plan for aligned bindings. Never materialize or infer hidden data.
An invocation's scope must be valid for EVERY bound asset, including the nested inference input.
For task-owned opaque scopes, do not copy a legacy file-partition scope from a different raw
asset. When all assets bound to an invocation share one exact certified scope, use
requested_scope={"kind":"certified_asset_scope","asset_id":"<one bound asset ID>"}.
The executor resolves this short reference from the certified asset descriptor; it grants no
new access. Never reference an unbound asset or use it to combine different certified scopes.
Choose explicit nperseg/frequency/lag/bin parameters when required. Invocation IDs must be safe
portable path components. Do not include commentary outside JSON."""
    if analysis_input.literature_evidence is not None:
        system += (
            "\nLiterature evidence is reasoning context only and must never change assets, "
            "access policy, information visibility, preprocessing authority, or skill "
            "authorization."
        )
    interface_payload = [
        {
            "card": skill.card.model_dump(mode="json"),
            "resolved_interface": interfaces[skill.card.skill_id].model_dump(mode="json"),
            "required_action_kind": (
                "generated_experiment_skill"
                if isinstance(skill, DiscoveredGeneratedExperimentSkill)
                else "skill"
            ),
        }
        for skill in selected
    ]
    generated_payload = [
        {
            "identity": identity.model_dump(mode="json"),
            "declaration": program.model_dump(
                mode="json",
                exclude={"source_ref", "source_sha256", "generation_provenance"},
            ),
        }
        for program, identity in generated_programs
    ]
    input_label = "DataAnalysisInput (source-scoped descriptors)"
    user = f"""{input_label}:
{_json(_planning_input(analysis_input))}

{_source_scope_block(analysis_input)}Required identity fields:
input_digest = {canonical_sha256(analysis_input)}
access_policy_digest = {canonical_sha256(analysis_input.access_policy)}
discovery_snapshot_digest = {discovery.snapshot_digest}

Selected interfaces:
{_json(interface_payload)}

Persisted generated programs available to the final plan:
{_json(generated_payload)}

Generated programs already exist and are immutable. A generated-program invocation must use
action_kind="generated_program" and reference one exact supplied program_identity. Never embed
source code or request code generation in AnalysisPlan.

A selected interface marked required_action_kind="generated_experiment_skill" is a promoted,
untrusted local skill. Invoke it with that exact action_kind and skill_id. It remains sandboxed;
never rewrite it as action_kind="skill" or request source regeneration.

AnalysisPlan JSON schema:
{_json(AnalysisPlan.model_json_schema())}
"""
    return system, user


def render_generated_program_prompt(
    analysis_input: DataAnalysisInput,
    *,
    question_ids: tuple[str, ...],
    output_schema: dict,
) -> tuple[str, str]:
    """Render the source-generation stage that precedes the final plan."""

    questions = [
        item.model_dump(mode="json")
        for item in analysis_input.analysis_brief.questions
        if item.question_id in question_ids
    ]
    system = """Create one bounded experiment-local scientific analysis program only because the
reference/configured toolbox was judged insufficient. Return strict JSON matching the authoritative
schema. Source must define exactly:

    def analyze(inputs, parameters, output_directory): ...

`source_code` is Python, not JSON. Inside source_code use Python literals `None`, `True`,
and `False`; never use JSON literals `null`, `true`, or `false`. JSON `null` remains valid in
the surrounding generated-program declaration where the declared schema permits it.

`inputs` maps final-plan binding IDs to read-only objects with `descriptor` and `arrays` mappings.
These mappings are read-only Mapping objects, not necessarily built-in dicts. Use mapping
operations (`obj["descriptor"]`, `descriptor["slot_id"]`, `arrays.get(...)`) or
`isinstance(value, collections.abc.Mapping)`; never use `isinstance(value, dict)` to decide
whether an authorized binding, descriptor, or array exists.
Binding IDs are chosen after source generation and need not equal declared slot IDs. Never
hard-code a binding ID or look up `inputs[slot_id]`; locate inputs by the certified
`descriptor["slot_id"]`, and support the declared slot cardinality. `arrays`
contains only the executor-authorized NPZ arrays: `example_ids`, `information__<class>`,
`metadata__<field>`, optional `valid_mask`, and for time-series views `channel_ids` plus exactly one
certified time-axis encoding (`time` or `time_start_seconds`/`time_step_seconds`). Never open task
paths yourself. `example_ids` are structural alignment values supplied with every authorized view;
do not declare `information_class="identity"` to obtain them. Identity information is available
only in safe discovery descriptors and cannot be requested for split materialization. `parameters`
contains validated scalar values. `output_directory` is the only
writable artifact directory. Return a plain JSON-serializable payload matching the SkillPayload
shape: summary, quantitative_results, produced_artifacts, analysis_usage, warnings. Write declared
artifacts below output_directory and declare paths relative to that same directory. For example,
writing `output_directory / "measurement.json"` requires `relative_path="measurement.json"`.
Do not prepend `artifacts/` unless you actually wrote into that subdirectory. Do not import SIDERIUS internals, inspect the workspace,
access credentials or network, install packages, alter data, or perform modeling/training. Declare
only concrete input information and view formats. A predictions input slot may consume certified
transient output from the trusted historical-inference capability; generated source never loads a
model or reads its raw inference inputs. Do not require metadata fields that the supplied access
policy does not authorize on the analysis split. Prefer a generic measurement based on certified
input properties and validated parameters when that keeps the operation clear. Do not embed a task
name, file number, fixed sample rate, or supposed signal answer where the same scientific question
can be expressed generically. A one-off program may remain task-local; only a genuinely reusable
operation should later be promoted. Generated parameter declarations obey this
conditional rule: `required=true` means the caller must supply the value and therefore `default`
must be null; a parameter with a usable default must set `required=false`. Do not redundantly mark
a parameter required while also assigning its value. The source and declaration will be persisted
and content-addressed before any executable plan exists. If `determinism` is `deterministic`,
declare an explicit non-negative `seed`; do not leave it null.

The raw runner ABI has these fixed shapes. Numeric views use `example_ids[N]`, information arrays
whose leading axis is N, optional scalar or `[N]` metadata, and optional per-example
`valid_mask[N]`. Time-series views use information arrays `[N,C,T]`, `channel_ids[C]`, and
per-observation `valid_mask[N,T]`; the mask is not an example-level boolean. A regular time axis is
`time_start_seconds[N]` plus `time_step_seconds[N]`; an explicit axis is `time[N,T]`. Do not guess
or transpose these certified axes.

SkillPayload also has validator-owned rules not fully expressed by JSON Schema: `analysis_usage`
counts the certified `descriptor["population_unit"]` (usually examples), not channel-series or
windows. `effective_count + dropped_count` must equal the certified selected/materialized count;
every dropped population unit has exactly one reason, drop reasons are unique, and their counts
must sum exactly to `dropped_count`. Every emitted quantitative result must copy its declared
`result_key`, `unit`, and `description` exactly, including description wording; only `value` is
computed at runtime. Artifact type and media type must likewise match their declarations exactly.
An absent required artifact, approximate field/description, or unbalanced usage count will be
rejected rather than normalized."""
    system += (
        "\nUse only these exact v1 accepted_view_formats identifiers: "
        + ", ".join(sorted(GENERATED_PROGRAM_VIEW_FORMATS_V1))
        + ". Do not invent spelling variants.\n"
    )
    user = f"""Questions requiring custom analysis:
{_json(questions)}

Task context:
{_json(analysis_input.task_context)}

{_source_scope_block(analysis_input)}{_literature_context_block(analysis_input)}Safe asset descriptors:
{_json(analysis_input.planning_assets())}

{_source_catalog_block(analysis_input)}Analysis access policy (authority remains enforced later):
{_json(analysis_input.access_policy)}

Resource envelope:
{_json(analysis_input.resource_envelope)}

Authoritative GeneratedProgramDraft JSON schema:
{_json(output_schema)}

Authoritative JSON schema for the payload returned by analyze(...):
{_json(SkillPayload.model_json_schema())}
"""
    return system, user


def render_report_synthesis_prompt(
    analysis_input: DataAnalysisInput,
    results: tuple[SkillResult, ...],
    *,
    output_schema: dict,
) -> tuple[str, str]:
    system = """Synthesize scientific analysis evidence into bounded JSON. Measurements are
evidence; do not prescribe architectures, preprocessing, dataset mutation, or training changes.
Every finding must cite exactly one completed result_id and only quantitative result_key values
present in that result. Prioritize measurements that answer the supplied questions or distinguish
plausible explanations; do not restate the same raw-data fact in multiple findings. If certified
historical-model predictions were analyzed, report their measured behavior and any supported
between-model contrast, naming the compared scopes and avoiding claims about unmeasured targets.
If model-aware analysis was attempted but not completed, say so explicitly rather than implying
the model was inspected. State limitations and sampling coverage honestly. Authorized asset
descriptors are declared context, not new measurements or permission to read additional data.
Use their units/acquisition metadata only for the matching measured asset; do not invent missing
artifact contents from a reference. Return JSON only."""
    bounded_results = [
        {
            "result_id": result.result_id,
            "execution_origin": result.execution_origin,
            "skill_id": (
                result.skill_identity.skill_id if result.skill_identity is not None else None
            ),
            "generated_program_id": (
                result.generated_program_identity.program_id
                if result.generated_program_identity is not None
                else None
            ),
            "status": result.status,
            "summary": result.summary,
            "quantitative_results": [
                item.model_dump(mode="json") for item in result.quantitative_results[:32]
            ],
            "coverage": None
            if result.coverage is None
            else result.coverage.model_dump(mode="json"),
            "warnings": list(result.warnings[:16]),
            "artifact_refs": [item.model_dump(mode="json") for item in result.artifact_refs[:16]],
        }
        for result in results
    ]
    user = f"""Task context:
{_json(analysis_input.task_context)}

Authorized asset descriptors (same scope projection used for planning):
{_json(analysis_input.planning_assets())}

Questions:
{_json(analysis_input.analysis_brief.questions)}

{_literature_context_block(analysis_input)}Certified bounded SkillResults:
{_json(bounded_results)}

Authoritative output JSON schema:
{_json(output_schema)}
"""
    return system, user


def render_generated_skill_promotion_prompt(
    analysis_input: DataAnalysisInput,
    *,
    completed_programs: list[dict],
    output_schema: dict,
) -> tuple[str, str]:
    """Ask for an explicit reuse decision; promotion never changes code."""

    system = """Decide whether any successfully executed one-off generated analysis program is
a generic scientific operation plausibly reusable across unrelated datasets and later iterations.
One-off analysis may be task-specific; promotion must not disguise task-specific source with a
generic SkillCard. Inspect the supplied exact declaration and source. Do not promote source that
hard-codes a task name, dataset/file index, sampling rate, frequency range, or supposed correct
signal value in place of a certified input property or validated parameter. If the source cannot
be judged reusable, return no promotion. Promotion only adds a discoverable SkillCard;
it does not change source, parameters, inputs, outputs, authority, or trust. Do not promote every
program automatically. Promote only when the same scientific operation is plausibly useful for a
later question or iteration. Return strict JSON. Each promotion must reference an exact supplied
program_id and describe that same operation without adding new semantics."""
    user = f"""Analysis questions:
{_json(analysis_input.analysis_brief.questions)}

Completed generated programs and certified results:
{_json(completed_programs)}

Promotion draft schema:
{_json(GeneratedSkillPromotionDraft.model_json_schema())}

Authoritative output schema:
{_json(output_schema)}
"""
    return system, user


def render_structured_output_repair_prompt(
    *,
    output_schema: dict,
    original_output: object,
    validation_errors: list[dict],
) -> tuple[str, str]:
    """Render one representation-only repair request from the schema authority."""

    system = """Repair one structured output so it conforms to the supplied authoritative JSON
schema. Preserve every recoverable semantic decision, identifier, ordering, parameter, and claim.
Correct representation/schema conformance only. Do not replan, add reasoning, expand scope, change
priorities, or select different skills. For RequestedInformation, deleting `fields` from a
non-metadata information class is representation repair; changing information_class or any metadata
field name is not. For deterministic historical inference, deleting a forbidden numeric `seed`
or replacing it with null is representation repair; changing determinism, model, input binding,
batch size, or device is not. Return only the repaired JSON object."""
    user = f"""Authoritative output JSON schema:
{_json(output_schema)}

Original structured output:
{_json(original_output)}

Concrete validation errors:
{_json(validation_errors)}
"""
    return system, user
