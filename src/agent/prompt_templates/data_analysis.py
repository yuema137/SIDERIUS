"""Prompt rendering for the caller-independent Data Analysis capability."""

from __future__ import annotations

import json

from agent.data_analysis.discovery import DiscoveredSkill, DiscoverySnapshot
from agent.schemas.data_analysis.common import canonical_sha256
from agent.schemas.data_analysis.context import DataAnalysisInput
from agent.schemas.data_analysis.plan import AnalysisPlan
from agent.schemas.data_analysis.skills import ResolvedSkillInterface, SkillResult


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
    candidates: tuple[DiscoveredSkill, ...],
    *,
    output_schema: dict,
) -> tuple[str, str]:
    system = """You plan scientific data analysis using only supplied SkillCards and safe asset
descriptors. Select a small sufficient candidate set. You cannot inspect data, invent fields,
or use a skill outside the cards. Return JSON with skill_ids and rationale."""
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
    selected: tuple[DiscoveredSkill, ...],
    interfaces: dict[str, ResolvedSkillInterface],
) -> tuple[str, str]:
    system = """Produce one executable AnalysisPlan as strict JSON. Use exact IDs, slots,
formats, information classes, metadata fields, parameters, cost hints, and question IDs from the
supplied contracts. Metadata parameters grant no access: the binding must request the exact field.
Use one invocation-level sampling plan for aligned bindings. Never materialize or infer hidden data.
Choose explicit nperseg/frequency/lag/bin parameters when required. Invocation IDs must be safe
portable path components. Do not include commentary outside JSON."""
    interface_payload = [
        {
            "card": skill.card.model_dump(mode="json"),
            "resolved_interface": interfaces[skill.card.skill_id].model_dump(mode="json"),
        }
        for skill in selected
    ]
    user = f"""DataAnalysisInput:
{_json(analysis_input)}

Required identity fields:
input_digest = {canonical_sha256(analysis_input)}
access_policy_digest = {canonical_sha256(analysis_input.access_policy)}
discovery_snapshot_digest = {discovery.snapshot_digest}

Selected interfaces:
{_json(interface_payload)}

AnalysisPlan JSON schema:
{_json(AnalysisPlan.model_json_schema())}
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
            "skill_id": result.skill_identity.skill_id,
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
priorities, or select different skills. Return only the repaired JSON object."""
    user = f"""Authoritative output JSON schema:
{_json(output_schema)}

Original structured output:
{_json(original_output)}

Concrete validation errors:
{_json(validation_errors)}
"""
    return system, user
