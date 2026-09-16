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


def _json(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")

    def encode_nested(item):
        if hasattr(item, "model_dump"):
            return item.model_dump(mode="json")
        return str(item)

    return json.dumps(value, sort_keys=True, indent=2, default=encode_nested)


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
You cannot inspect data, invent fields, or use a skill outside the cards. Return strict JSON."""
    user = f"""Analysis brief:
{_json(analysis_input.analysis_brief)}

Task context:
{_json(analysis_input.task_context)}

Human advice:
{analysis_input.human_advice or "None"}

Resource envelope:
{_json(analysis_input.resource_envelope)}

Safe asset descriptors:
{_json(analysis_input.available_assets)}

Candidate SkillCards:
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
RequestedInformation.fields is conditional: use explicit names only when information_class is
"metadata". For "identity", "data", "target", "prediction", or "residual", fields must be empty.
Examples: {"information_class":"data","fields":[]} and
{"information_class":"prediction","fields":[]} are valid;
{"information_class":"metadata","fields":["snr"]} is valid; and
{"information_class":"prediction","fields":["prediction"]} is invalid.
Use one invocation-level sampling plan for aligned bindings. Never materialize or infer hidden data.
Choose explicit nperseg/frequency/lag/bin parameters when required. Invocation IDs must be safe
portable path components. Do not include commentary outside JSON."""
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
    user = f"""DataAnalysisInput:
{_json(analysis_input)}

Required identity fields:
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

`inputs` maps final-plan binding IDs to read-only objects with `descriptor` and `arrays` mappings.
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
artifacts below output_directory and use paths relative to the sandbox output root (therefore
prefix artifact paths with `artifacts/`). Do not import SIDERIUS internals, inspect the workspace,
access credentials or network, install packages, alter data, or perform modeling/training. Declare
only concrete input information and view formats. Generated parameter declarations obey this
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
    user = f"""Questions requiring custom analysis:
{_json(questions)}

Task context:
{_json(analysis_input.task_context)}

Safe asset descriptors:
{_json(analysis_input.available_assets)}

Analysis access policy (authority remains enforced later):
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
present in that result. State limitations and sampling coverage honestly. Return JSON only."""
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
    user = f"""Questions:
{_json(analysis_input.analysis_brief.questions)}

Certified bounded SkillResults:
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
likely to be reused later in this same experiment. Promotion only adds a discoverable SkillCard;
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
field name is not. Return only the repaired JSON object."""
    user = f"""Authoritative output JSON schema:
{_json(output_schema)}

Original structured output:
{_json(original_output)}

Concrete validation errors:
{_json(validation_errors)}
"""
    return system, user
