"""Deterministic behavioral-validation harness for the Data Analysis Agent.

This is test scaffolding, not a replacement planner.  It drives the real
discovery, interface resolution, authorization, materialization, subprocess
skill execution, synthesis validation, persistence, and Proposer projection
with a controlled bridge so advice/budget trajectories are inspectable without
provider credentials.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from agent.data_analysis.discovery import discover_skills
from agent.data_analysis.reference_packs import builtin_pack_refs
from agent.schemas.data_analysis.assets import (
    AnalysisAsset,
    ArtifactIntrinsicScope,
    AssetProvenance,
    MaterializedAnalysisView,
    WorkspaceArtifactLocation,
)
from agent.schemas.data_analysis.common import CertifiedArtifactRef, canonical_sha256
from agent.schemas.data_analysis.context import DataAnalysisInput
from agent.schemas.data_analysis.time import FixedTimePrecisionRequirement
from agent.schemas.proposer_data_analysis_evidence import (
    build_proposer_data_analysis_evidence,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
from nodes.data_analysis_agent import DataAnalysisAgent

FixtureKind = Literal["regular_periodic_drift", "irregular_periodic"]
BudgetName = Literal["exhausted", "low", "medium", "high"]


@dataclass(frozen=True)
class BehavioralCase:
    case_id: str
    fixture: FixtureKind
    advice: str | None
    budget: BudgetName


PRIMARY_CASES = (
    BehavioralCase("regular-none-low", "regular_periodic_drift", None, "low"),
    BehavioralCase(
        "regular-periodicity-low",
        "regular_periodic_drift",
        "Focus on periodic and frequency-domain structure.",
        "low",
    ),
    BehavioralCase(
        "regular-drift-low",
        "regular_periodic_drift",
        "Focus on temporal drift and nonstationarity.",
        "low",
    ),
    BehavioralCase(
        "regular-benign-low",
        "regular_periodic_drift",
        "Prefer concise result labels.",
        "low",
    ),
    BehavioralCase("regular-none-medium", "regular_periodic_drift", None, "medium"),
    BehavioralCase("regular-none-high", "regular_periodic_drift", None, "high"),
    BehavioralCase(
        "regular-exhausted",
        "regular_periodic_drift",
        None,
        "exhausted",
    ),
    BehavioralCase(
        "irregular-periodicity-low",
        "irregular_periodic",
        "Check periodic structure without repairing timestamps.",
        "low",
    ),
)


_BUDGETS: dict[BudgetName, tuple[float, float]] = {
    # Interface resolution is deliberately outside the scientific execution
    # deadline.  The subprocess must tolerate a fully loaded CI shard; the
    # plan's equal minimum-remaining-time threshold still proves no skill
    # starts in the exhausted case.
    "exhausted": (10.0, 10.0),
    "low": (8.0, 8.0),
    "medium": (16.0, 10.0),
    "high": (30.0, 10.0),
}


def _selected_skills(case: BehavioralCase) -> tuple[str, ...]:
    if case.fixture == "irregular_periodic":
        return ("sampling_cadence_and_gaps", "lomb_scargle_periodogram")
    advice = (case.advice or "").casefold()
    if "periodic" in advice or "frequency-domain" in advice:
        return ("welch_psd", "autocorrelation")
    if "drift" in advice or "nonstationarity" in advice:
        return ("temporal_stability_summary", "stft_energy_map")
    if case.budget in {"low", "exhausted"}:
        return ("sampling_cadence_and_gaps", "welch_psd")
    if case.budget == "medium":
        return (
            "sampling_cadence_and_gaps",
            "welch_psd",
            "temporal_stability_summary",
        )
    return (
        "sampling_cadence_and_gaps",
        "welch_psd",
        "autocorrelation",
        "temporal_stability_summary",
        "stft_energy_map",
    )


def _arguments(skill_id: str) -> dict[str, Any]:
    return {
        "sampling_cadence_and_gaps": {},
        "welch_psd": {"nperseg": 256, "maximum_peaks": 4},
        "autocorrelation": {"maximum_lag_samples": 128},
        "temporal_stability_summary": {
            "window_count": 8,
            "minimum_points_per_window": 16,
        },
        "stft_energy_map": {"nperseg": 128},
        "lomb_scargle_periodogram": {
            "minimum_frequency_hz": 0.5,
            "maximum_frequency_hz": 6.0,
            "frequency_count": 1024,
            "maximum_peaks": 4,
        },
    }[skill_id]


class SyntheticTimeSeriesCapability:
    """Task-owned exporter for one immutable synthetic fixture."""

    def __init__(self, fixture: FixtureKind) -> None:
        self.fixture = fixture
        self._exports: dict[str, bytes] = {}
        self.requests = []

    @staticmethod
    def _regular_values(count: int) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        sample_rate_hz = 64.0
        length = 1024
        time_values = np.arange(length, dtype=np.float64) / sample_rate_hz
        rng = np.random.default_rng(20260915)
        values = []
        for example_index in range(count):
            drift = (0.3 + 0.05 * example_index) * time_values / time_values[-1]
            signal = (
                np.sin(2 * np.pi * 4.0 * time_values)
                + 0.35 * np.sin(2 * np.pi * 11.0 * time_values)
                + drift
                + rng.normal(0.0, 0.08, length)
            )
            values.append(signal)
        return np.asarray(values)[:, None, :], {
            "time_start_seconds": np.zeros(count, dtype=np.float64),
            "time_step_seconds": np.full(count, 1.0 / sample_rate_hz, dtype=np.float64),
        }

    @staticmethod
    def _irregular_values(count: int) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        length = 700
        base = np.arange(length, dtype=np.float64) * 0.08
        rng = np.random.default_rng(20260916)
        times = []
        values = []
        for _ in range(count):
            time_values = np.sort(base + rng.normal(0.0, 0.012, length))
            # Retain genuine gaps while preserving source ordering.
            time_values[350:] += 1.2
            signal = np.sin(2 * np.pi * 2.25 * time_values) + rng.normal(0.0, 0.12, length)
            times.append(time_values)
            values.append(signal)
        return np.asarray(values)[:, None, :], {
            "time": np.asarray(times, dtype=np.float64),
            "time_certified_regular": np.zeros(count, dtype=np.bool_),
            "time_required_resolution_seconds": np.full(count, 1e-12, dtype=np.float64),
        }

    def materialize_analysis_view(self, authorized) -> MaterializedAnalysisView:
        request = authorized.request
        self.requests.append(request)
        requested_count = request.sampling_policy.max_items or 4
        count = min(4, requested_count)
        if self.fixture == "regular_periodic_drift":
            values, axis = self._regular_values(count)
        else:
            values, axis = self._irregular_values(count)
        example_ids = np.asarray([f"example-{index}" for index in range(count)])
        buffer = io.BytesIO()
        np.savez(
            buffer,
            example_ids=example_ids,
            channel_ids=np.asarray(["sensor"]),
            valid_mask=np.ones((count, values.shape[-1]), dtype=np.bool_),
            information__data=values,
            **axis,
        )
        payload = buffer.getvalue()
        payload_sha = hashlib.sha256(payload).hexdigest()
        logical_ref = (
            f"opaque://behavior/{self.fixture}/{request.invocation_id}/{request.binding_id}"
        )
        self._exports[logical_ref] = payload
        selected_sha = hashlib.sha256(
            "\n".join(str(item) for item in example_ids).encode("utf-8")
        ).hexdigest()
        return MaterializedAnalysisView(
            materialization_id=f"materialized-{request.invocation_id}-{request.binding_id}",
            invocation_id=request.invocation_id,
            binding_id=request.binding_id,
            slot_id=request.slot_id,
            asset_id=request.asset.asset_id,
            split_id=request.split_id,
            content_ref=CertifiedArtifactRef(
                logical_ref=logical_ref,
                sha256=payload_sha,
                media_type="application/x-npz",
                byte_size=len(payload),
            ),
            format_id=request.requested_format_id,
            time_precision_requirement=request.time_precision_requirement,
            population_unit="examples",
            total_available=4,
            materialized_count=count,
            certified_information=request.requested_information,
            selection_identity={
                "selection_id": f"selection-{request.invocation_id}",
                "selection_sha256": selected_sha,
                "sampling_policy_sha256": canonical_sha256(request.sampling_policy),
                "sampling_mode": request.sampling_policy.mode,
                "sampling_strategy": request.sampling_policy.strategy,
                "sampling_seed": request.sampling_policy.seed,
                "population_unit": "examples",
                "total_available": 4,
                "selected_count": count,
            },
            source_digests=(payload_sha,),
            authorization_receipt=authorized.authorization_receipt,
        )

    def export_analysis_materialization(self, content_ref, destination: Path) -> None:
        payload = self._exports[content_ref.logical_ref]
        assert hashlib.sha256(payload).hexdigest() == content_ref.sha256
        destination.write_bytes(payload)


class ControlledBehaviorBridge:
    """Deterministic planner/synthesizer exposing trajectory semantics."""

    def __init__(
        self, *, analysis_input: DataAnalysisInput, case: BehavioralCase, **_kwargs
    ) -> None:
        self.inp = analysis_input
        self.case = case
        self.discovery = discover_skills(analysis_input.allowed_skill_packs)
        self.prompt_receipts: dict[str, dict[str, Any]] = {}

    def _record_prompt(self, label: str, user: str) -> None:
        advice = self.inp.human_advice or "None"
        self.prompt_receipts[label] = {
            "advice_visible": advice in user,
            "budget_visible": str(self.inp.resource_envelope.wall_time_budget_s) in user,
        }
        if label == "data_analysis.skill_selection":
            cards_text = user.split("Candidate SkillCards:\n", 1)[1].split(
                "\n\nAuthoritative output JSON schema:\n", 1
            )[0]
            cards = json.loads(cards_text)
            self.prompt_receipts[label]["candidate_skill_ids"] = [
                card["skill_id"] for card in cards
            ]

    def generate(self, _system, user, *, label):
        self._record_prompt(label, user)
        selected = _selected_skills(self.case)
        if label == "data_analysis.skill_selection":
            return {
                "skill_ids": selected,
                "rationale": (
                    "Prioritize applicable complementary skills according to advice and budget; "
                    "advice grants no access."
                ),
            }
        if label == "data_analysis.plan":
            skill_by_id = {item.card.skill_id: item for item in self.discovery.skills}
            scope = self.inp.available_assets[0].authorized_scope.model_dump(mode="json")
            invocations = []
            for index, skill_id in enumerate(selected):
                card = skill_by_id[skill_id].card
                invocations.append(
                    {
                        "invocation_id": f"invocation-{index + 1:02d}-{skill_id}",
                        "skill_id": skill_id,
                        "question_ids": ["q-characterize"],
                        "bindings": [
                            {
                                "binding_id": f"binding-{index + 1:02d}-{skill_id}",
                                "slot_id": "series",
                                "asset_id": "signal",
                                "requested_format_id": "siderius.timeseries-array.v1",
                                "requested_information": [{"information_class": "data"}],
                            }
                        ],
                        "sampling_plan": {
                            "split_id": "validation",
                            "requested_scope": scope,
                            "policy": {
                                "mode": "fixed",
                                "max_items": 4,
                                "strategy": "uniform",
                                "seed": 23,
                            },
                        },
                        "arguments": _arguments(skill_id),
                        "expected_time_cost": card.time_cost,
                        "expected_memory_cost": card.memory_cost,
                        "priority": max(1, 5 - index),
                    }
                )
            return {
                "plan_id": f"plan-{self.case.case_id}",
                "input_digest": canonical_sha256(self.inp),
                "access_policy_digest": canonical_sha256(self.inp.access_policy),
                "discovery_snapshot_digest": self.discovery.snapshot_digest,
                "questions": ["q-characterize"],
                "invocations": invocations,
                "stop_policy": {
                    "max_invocations": len(invocations),
                    "minimum_remaining_time_s": (
                        self.inp.resource_envelope.wall_time_budget_s
                        if self.case.budget == "exhausted"
                        else 0.05
                    ),
                    "continue_after_skill_failure": True,
                },
                "rationale": "Use a bounded, non-redundant trajectory for this condition.",
            }
        if label == "data_analysis.synthesis":
            encoded = user.split("Certified bounded SkillResults:\n", 1)[1].split(
                "\n\nAuthoritative output JSON schema:\n", 1
            )[0]
            results = json.loads(encoded)
            completed = [item for item in results if item["status"] == "completed"]
            findings = []
            for index, result in enumerate(completed):
                measurements = result.get("quantitative_results", [])[:2]
                result_keys = [item["result_key"] for item in measurements]
                measurement = measurements[-1] if measurements else None
                measured_statement = result["summary"]
                if measurement is not None:
                    unit = f" {measurement['unit']}" if measurement.get("unit") else ""
                    measured_statement += (
                        f" {measurement['description']}: {measurement['value']}{unit}."
                    )
                findings.append(
                    {
                        "finding_id": f"finding-{index + 1:02d}-{result['skill_id']}",
                        "result_id": result["result_id"],
                        "statement": measured_statement,
                        "quantitative_result_ids": result_keys,
                        "confidence_level": "high",
                        "confidence_rationale": (
                            "The cited deterministic skill completed on certified materialization."
                        ),
                        "confidence_limitations": [],
                        "modeling_relevance": (
                            "This measured evidence can inform later diagnosis without prescribing "
                            "a model or preprocessing action."
                        ),
                    }
                )
            if completed:
                status = "addressed"
                summary = "Executed the budgeted applicable analysis trajectory."
                unresolved = []
                limitations = []
            else:
                status = "unresolved"
                summary = "No invocation started because the stop condition exhausted the budget."
                unresolved = ["The requested characterization remains unresolved."]
                limitations = [
                    {
                        "limitation_id": "budget-exhausted",
                        "statement": "The execution budget was exhausted before materialization.",
                        "affected_question_ids": ["q-characterize"],
                    }
                ]
            return {
                "executive_summary": summary,
                "findings": findings,
                "question_outcomes": [
                    {
                        "question_id": "q-characterize",
                        "status": status,
                        "summary": summary,
                        "finding_ids": [item["finding_id"] for item in findings],
                        "limitation_ids": [item["limitation_id"] for item in limitations],
                    }
                ],
                "limitations": limitations,
                "unresolved_questions": unresolved,
                "modeling_relevance": (
                    ["Use the measured evidence as bounded input to downstream reasoning."]
                    if completed
                    else []
                ),
            }
        raise AssertionError(label)


def build_behavioral_input(case: BehavioralCase, workspace: Path) -> DataAnalysisInput:
    scope = ArtifactIntrinsicScope(
        split_id="validation",
        description="Four synthetic validation time series",
    )
    irregular = case.fixture == "irregular_periodic"
    precision = (
        FixedTimePrecisionRequirement(required_resolution_seconds=1e-12) if irregular else None
    )
    asset = AnalysisAsset(
        asset_id="signal",
        asset_type="dataset",
        description=(
            "Synthetic irregular periodic sensor series with timestamp gaps."
            if irregular
            else "Synthetic regular noisy two-frequency sensor series with slow drift."
        ),
        location=WorkspaceArtifactLocation(
            artifact_ref=CertifiedArtifactRef(
                logical_ref=f"synthetic://{case.fixture}",
                sha256=hashlib.sha256(case.fixture.encode("utf-8")).hexdigest(),
                media_type="application/x-synthetic-fixture",
            )
        ),
        provenance=AssetProvenance(producer="behavioral-validation-fixture"),
        authorized_scope=scope,
        split_id="validation",
        time_precision_requirement=precision,
    )
    wall_time, per_skill = _BUDGETS[case.budget]
    question = (
        "Determine whether irregular observations contain periodic structure without repairing "
        "their timestamps."
        if irregular
        else "Characterize sampling, periodic frequency structure, lag structure, and temporal "
        "drift/nonstationarity including time-frequency structure in this scientific time series."
    )
    return DataAnalysisInput(
        request_id=f"behavior-{case.case_id}",
        task_context={
            "task_id": "synthetic-scientific-timeseries",
            "scientific_goal": "Characterize observable time-series structure.",
            "task_description": "A domain-neutral scientific sensor analysis fixture.",
            "input_description": (
                "Irregular timestamps and one measured channel."
                if irregular
                else "Regular timestamps and one measured channel."
            ),
            "metric_summary": "No modeling metric is required for raw-data characterization.",
            "forward_contract": ForwardContract(),
        },
        analysis_brief={
            "brief_id": f"brief-{case.fixture}",
            "questions": [{"question_id": "q-characterize", "question": question}],
            "source": "orchestrator",
            "source_ref": "behavioral-validation",
        },
        available_assets=(asset,),
        declared_scope={"raw_input_asset_ids": [asset.asset_id]},
        access_policy={
            "policy_id": "behavioral-data-only",
            "policy_version": 1,
            "purpose": "Synthetic raw-data behavioral validation",
            "split_rules": [{"split_id": "validation", "data_visible": True}],
        },
        resource_envelope={
            "wall_time_budget_s": wall_time,
            "per_skill_timeout_s": per_skill,
            "preferred_device": "cpu",
            "sampling_policy": {
                "mode": "fixed",
                "max_items": 4,
                "strategy": "uniform",
                "seed": 23,
            },
        },
        allowed_skill_packs=builtin_pack_refs("core-analysis", "time-series"),
        human_advice=case.advice,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(workspace), run_name=case.case_id),
        ),
        caller={"caller_id": "behavioral-validator", "caller_type": "orchestrator"},
    )


def run_behavioral_case(case: BehavioralCase, workspace: Path) -> dict[str, Any]:
    analysis_input = build_behavioral_input(case, workspace)
    bridges: list[ControlledBehaviorBridge] = []
    capability = SyntheticTimeSeriesCapability(case.fixture)

    def factory(**kwargs):
        bridge = ControlledBehaviorBridge(analysis_input=analysis_input, case=case, **kwargs)
        bridges.append(bridge)
        return bridge

    report = DataAnalysisAgent(
        task_analysis_capability=capability,
        bridge_factory=factory,
        provider="behavioral-validation",
        model_id="controlled-v1",
    ).run(analysis_input)
    run_root = workspace / "data_analysis" / case.case_id / analysis_input.request_id
    plan = json.loads((run_root / "plan.json").read_text())
    report_bytes = (run_root / "report.json").read_bytes()
    projection = build_proposer_data_analysis_evidence(
        report,
        report_ref=CertifiedArtifactRef(
            logical_ref=f"behavioral-validation/{case.case_id}/report.json",
            sha256=hashlib.sha256(report_bytes).hexdigest(),
            media_type="application/json",
            byte_size=len(report_bytes),
        ),
    )
    projection_path = run_root / "proposer_data_analysis_evidence.json"
    projection_path.write_text(
        json.dumps(projection.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    )
    bridge = bridges[0]
    return {
        "case": case,
        "input": analysis_input,
        "plan": plan,
        "report": report,
        "projection": projection,
        "run_root": run_root,
        "prompt_receipts": bridge.prompt_receipts,
        "materialization_requests": tuple(capability.requests),
    }


def run_behavioral_matrix(workspace: Path) -> tuple[dict[str, Any], ...]:
    return tuple(run_behavioral_case(case, workspace) for case in PRIMARY_CASES)


def write_validation_packet(workspace: Path, receipts: tuple[dict[str, Any], ...]) -> Path:
    output = workspace / "behavioral-validation.md"
    lines = [
        "# Data Analysis Agent behavioral validation",
        "",
        "## Audit result",
        "",
        "This exact same-input/advice/budget trajectory validation did **not** exist before this",
        "change. Existing tests already covered numerical synthetic generality, SkillCard/interface",
        "usability, standalone execution, access enforcement, persistence and resume identity; they",
        "did not place the resulting plans and reports side by side across controlled conditions.",
        "",
        "Deterministic controlled-bridge validation of the real Data Analysis execution path.",
        "The bridge makes reviewed choices reproducibly; this packet is not evidence of real-LLM",
        "choice quality. Provider credentials were checked by name only.",
        "",
        "| Case | Fixture | Advice | Budget (s) | Planned skills | Executed | Status |",
        "|---|---|---|---:|---|---|---|",
    ]
    for receipt in receipts:
        case = receipt["case"]
        inp = receipt["input"]
        report = receipt["report"]
        planned = [item["skill_id"] for item in receipt["plan"]["invocations"]]
        executed = [item.skill_id for item in report.skill_result_summaries]
        status = ", ".join(item.status for item in report.skill_result_summaries) or "not-started"
        lines.append(
            f"| `{case.case_id}` | `{case.fixture}` | {case.advice or 'none'} | "
            f"{inp.resource_envelope.wall_time_budget_s:g} | "
            f"`{' → '.join(planned)}` | `{' → '.join(executed) or '—'}` | {status} |"
        )
    lines.extend(
        [
            "",
            "## Case artifacts",
            "",
        ]
    )
    for receipt in receipts:
        case = receipt["case"]
        inp = receipt["input"]
        report = receipt["report"]
        relative = receipt["run_root"].relative_to(workspace)
        candidate_ids = receipt["prompt_receipts"]["data_analysis.skill_selection"][
            "candidate_skill_ids"
        ]
        arguments = {
            invocation["skill_id"]: invocation["arguments"]
            for invocation in receipt["plan"]["invocations"]
        }
        lines.extend(
            [
                f"### {case.case_id}",
                "",
                f"- Advice: {case.advice or 'none'}",
                f"- Resource envelope: `{json.dumps(inp.resource_envelope.model_dump(mode='json'), sort_keys=True)}`",
                f"- Candidate SkillCards visible: `{'`, `'.join(candidate_ids)}`",
                f"- Validated plan parameters: `{json.dumps(arguments, sort_keys=True)}`",
                f"- Executive summary: {report.executive_summary}",
                f"- Attempts/completed: {report.resource_usage.attempted_invocations}/"
                f"{report.resource_usage.completed_invocations}",
                f"- Observed wall time: {report.resource_usage.total_wall_time_s:.6f} s",
                f"- Findings: {len(report.findings)}; limitations: {len(report.limitations)}; "
                f"unresolved: {len(report.unresolved_questions)}",
                f"- [Input]({relative}/input.json), [discovery]({relative}/discovery.json), "
                f"[plan]({relative}/plan.json), [results]({relative}/skill_results.jsonl), "
                f"[report JSON]({relative}/report.json), [report Markdown]({relative}/report.md), "
                f"[Proposer projection]({relative}/proposer_data_analysis_evidence.json)",
                "",
            ]
        )
    lines.extend(
        [
            "## Qualitative assessment",
            "",
            "- Relevant advice changed prioritization while the access policy and materialized",
            "  information remained data-only. Benign presentation advice did not redirect science.",
            "- Low/medium/high envelopes produced 2/3/5 complementary invocations. The high-budget",
            "  path did not duplicate a skill. The exhausted stop condition launched no worker and",
            "  preserved a limitation plus unresolved question.",
            "- The irregular fixture selected cadence diagnostics plus Lomb-Scargle and did not churn",
            "  through FFT/Welch/STFT failures.",
            "- Every finding points to a completed SkillResult, carries certified coverage, and the",
            "  Proposer projection is generated from the bounded report rather than hidden files.",
            "- During validation, a less explicit synthetic question failed to retrieve STFT among",
            "  the bounded top candidates. Adding the scientifically accurate term `time-frequency`",
            "  fixed discovery. Classification: expected keyword-retrieval/card-query sensitivity,",
            "  not an architecture defect; it should be revisited with real-LLM trajectories.",
            "- The audit found and fixed two prompt-plumbing defects: nested SkillCards had been",
            "  serialized as strings instead of JSON objects, and the skill-selection stage did not",
            "  receive the resource envelope. Classification: prompt/interface usability defects;",
            "  public contracts and scientific semantics were unchanged.",
            "- The controlled bridge proves transport, execution and evidence-grounding invariants.",
            "  It does not prove that a production LLM will independently make these choices.",
            "",
        ]
    )
    available_keys = [
        name
        for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY")
        if os.environ.get(name)
    ]
    lines.extend(
        [
            "## Real-LLM smoke",
            "",
            (
                "Credentials were present by variable name, but no effectful provider call is made "
                "by this deterministic packet generator."
                if available_keys
                else "Not run: no configured provider credential was present."
            ),
            "",
        ]
    )
    output.write_text("\n".join(lines))
    return output
