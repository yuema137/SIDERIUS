"""Generated analysis can consume certified transient historical predictions."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from agent.data_analysis.analysis_code_sandbox import AnalysisCodeSandbox
from agent.schemas.data_analysis.assets import (
    AnalysisAsset,
    AssetProvenance,
    TrainedModelArtifactLocation,
)
from agent.schemas.data_analysis.common import canonical_sha256
from agent.schemas.data_analysis.context import DataAnalysisInput
from nodes.data_analysis_agent import DataAnalysisAgent
from tests.unit.agent.data_analysis.test_historical_model_inference import _fixture
from tests.unit.nodes.test_data_analysis_agent import _GeneratedProgramBridge, _input


class _ModelInputCapability:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def materialize_analysis_view(self, authorized):
        from agent.schemas.data_analysis.assets import MaterializedAnalysisView
        from agent.schemas.data_analysis.common import CertifiedArtifactRef

        request = authorized.request
        digest = hashlib.sha256(self.payload).hexdigest()
        return MaterializedAnalysisView(
            materialization_id=f"materialized-{request.binding_id}",
            invocation_id=request.invocation_id,
            binding_id=request.binding_id,
            slot_id=request.slot_id,
            asset_id=request.asset.asset_id,
            split_id=request.split_id,
            content_ref=CertifiedArtifactRef(
                logical_ref=f"opaque://synthetic/{request.binding_id}",
                sha256=digest,
                media_type="application/x-npz",
                byte_size=len(self.payload),
            ),
            format_id=request.requested_format_id,
            population_unit="examples",
            total_available=2,
            materialized_count=2,
            certified_information=request.requested_information,
            selection_identity={
                "selection_id": "synthetic-model-selection",
                "selection_sha256": "4" * 64,
                "sampling_policy_sha256": canonical_sha256(request.sampling_policy),
                "sampling_mode": request.sampling_policy.mode,
                "sampling_strategy": request.sampling_policy.strategy,
                "sampling_seed": request.sampling_policy.seed,
                "population_unit": "examples",
                "total_available": 2,
                "selected_count": 2,
            },
            source_digests=(digest,),
            authorization_receipt=authorized.authorization_receipt,
        )

    def export_analysis_materialization(self, content_ref, destination: Path) -> None:
        assert content_ref.logical_ref.startswith("opaque://synthetic/")
        destination.write_bytes(self.payload)


class _PredictionBridge(_GeneratedProgramBridge):
    def __init__(self, *, repair_seed: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.repair_seed = repair_seed
        self.initial_plan = None

    def generate(self, system, user, *, label):
        if label == "data_analysis.plan.repair":
            self.calls.append(label)
            assert self.initial_plan is not None
            repaired = copy.deepcopy(self.initial_plan)
            del repaired["invocations"][0]["bindings"][0]["inference_configuration"]["seed"]
            return repaired
        if label == "data_analysis.generated_program":
            draft = super().generate(system, user, label=label)
            draft["program_id"] = "historical-prediction-mean"
            draft["source_code"] = (
                "import numpy as np\n\n"
                "def analyze(inputs, parameters, output_directory):\n"
                "    assert set(inputs) == {'predictions-view'}\n"
                "    predictions = inputs['predictions-view']['arrays']['information__prediction']\n"
                "    measured = float(np.mean(predictions))\n"
                "    return {\n"
                "        'summary': 'Measured certified historical prediction mean.',\n"
                "        'quantitative_results': [{\n"
                "            'result_key': 'mean_prediction', 'value': measured,\n"
                "            'unit': None, 'description': 'Mean certified prediction',\n"
                "        }],\n"
                "        'produced_artifacts': [],\n"
                "        'analysis_usage': {'effective_count': 2, 'dropped_count': 0, "
                "'drop_reasons': []},\n"
                "        'warnings': [],\n"
                "    }\n"
            )
            draft["input_slots"] = [
                {
                    "slot_id": "predictions",
                    "description": "Certified historical model predictions",
                    "accepted_asset_types": ["predictions"],
                    "accepted_view_formats": ["siderius.numeric-array.v1"],
                    "required_information": [{"information_class": "prediction", "fields": []}],
                }
            ]
            draft["expected_measurements"] = [
                {
                    "result_key": "mean_prediction",
                    "description": "Mean certified prediction",
                    "value_type": "number",
                }
            ]
            draft["resource_request"]["wall_time_s"] = 10.0
            return draft
        if label == "data_analysis.plan":
            plan = super().generate(system, user, label=label)
            invocation = plan["invocations"][0]
            invocation["bindings"] = [
                {
                    "binding_id": "predictions-view",
                    "slot_id": "predictions",
                    "asset_id": "historical-model",
                    "operation": "infer",
                    "requested_format_id": "siderius.numeric-array.v1",
                    "requested_information": [{"information_class": "prediction", "fields": []}],
                    "inference_inputs": [
                        {
                            "binding_id": "model-input",
                            "asset_id": "dataset",
                            "requested_format_id": "siderius.numeric-array.v1",
                            "requested_information": [{"information_class": "data", "fields": []}],
                        }
                    ],
                    "inference_configuration": {"batch_size": 2, "device": "cpu"},
                }
            ]
            invocation["sampling_plan"]["policy"]["max_items"] = 2
            if self.repair_seed:
                invocation["bindings"][0]["inference_configuration"].update(
                    determinism="deterministic", seed=0
                )
                self.initial_plan = copy.deepcopy(plan)
            return plan
        if label == "data_analysis.synthesis":
            self.calls.append(label)
            return {
                "executive_summary": "Two certified predictions average 1.5.",
                "findings": [
                    {
                        "finding_id": "finding-prediction-mean",
                        "result_id": f"{self.inp.request_id}.generated-invocation.result",
                        "statement": "The two certified historical predictions average 1.5.",
                        "quantitative_result_ids": ["mean_prediction"],
                        "confidence_level": "high",
                        "confidence_rationale": "Both selected predictions were measured.",
                        "confidence_limitations": [],
                        "modeling_relevance": "The historical prediction scale was measured.",
                    }
                ],
                "question_outcomes": [
                    {
                        "question_id": "q-summary",
                        "status": "addressed",
                        "summary": "Historical predictions were characterized.",
                        "finding_ids": ["finding-prediction-mean"],
                    }
                ],
                "limitations": [],
                "unresolved_questions": [],
                "modeling_relevance": ["Prediction scale is explicit."],
            }
        return super().generate(system, user, label=label)


@pytest.mark.allow_real_subprocess
@pytest.mark.parametrize("repair_seed", (False, True))
def test_generated_program_consumes_only_certified_transient_predictions(
    tmp_path: Path, repair_seed: bool
) -> None:
    probe = AnalysisCodeSandbox().probe()
    if not probe.available:
        pytest.skip(f"host cannot enforce sandbox: {probe.reason}")

    inference, historical_request, runtime_inputs, _ = _fixture(tmp_path)
    model = historical_request.model_artifact
    base = _input(tmp_path)
    payload = base.model_dump(mode="json")
    payload["available_assets"].append(
        AnalysisAsset(
            asset_id="historical-model",
            asset_type="trained_model",
            description="Exact synthetic trained model",
            location=TrainedModelArtifactLocation(
                artifact_ref=historical_request.model_artifact_ref.artifact_ref,
                artifact=model,
            ),
            provenance=AssetProvenance(producer="training", run_id=model.training_run.run_name),
            authorized_scope=base.available_assets[0].authorized_scope,
            split_id="validation",
            allowed_operations=("infer",),
        ).model_dump(mode="json")
    )
    payload["declared_scope"] = {
        "raw_input_asset_ids": ["dataset"],
        "historical_model_asset_ids": ["historical-model"],
        "history_run_names": [model.training_run.run_name],
    }
    payload["access_policy"]["allow_model_inference"] = True
    payload["access_policy"]["split_rules"][0]["predictions_visible"] = True
    payload["resource_envelope"]["wall_time_budget_s"] = 90
    payload["resource_envelope"]["per_skill_timeout_s"] = 45
    inp = DataAnalysisInput.model_validate(payload)
    bridge = _PredictionBridge(analysis_input=inp, repair_seed=repair_seed)
    agent = DataAnalysisAgent(
        task_analysis_capability=_ModelInputCapability(
            Path(runtime_inputs.paths[0].path).read_bytes()
        ),
        historical_model_inference_capability=inference,
        bridge_factory=lambda **_kwargs: bridge,
        provider="test",
        model_id="fake",
    )

    report = agent.run(inp)

    assert report.skill_result_summaries[0].status == "completed"
    assert report.skill_result_summaries[0].key_quantitative_results[0].value == 1.5
    assert report.findings[0].method_generated_program_ids == ("historical-prediction-mean",)
    assert report.source_scope == inp.effective_source_scope()
    assert set(report.assets_inspected) == {"dataset", "historical-model"}
    root = tmp_path / "data_analysis" / "standalone" / "request"
    inference_receipts = [
        json.loads(line) for line in (root / "inference_receipts.jsonl").read_text().splitlines()
    ]
    assert len(inference_receipts) == 1
    assert inference_receipts[0]["target_exposed_to_inference"] is False
    assert inference_receipts[0]["prediction_count"] == 2
    retention = [
        json.loads(line)
        for line in (root / "prediction_retention_receipts.jsonl").read_text().splitlines()
    ]
    assert len(retention) == 1
    assert retention[0]["status"] == "retired"
    if repair_seed:
        receipts = [
            json.loads(line)
            for line in (root / "structured_output_receipts.jsonl").read_text().splitlines()
        ]
        plan_receipt = next(item for item in receipts if item["stage"] == "data_analysis.plan")
        assert plan_receipt["initial_validation_passed"] is False
        assert plan_receipt["repair_attempted"] is True
        assert plan_receipt["repair_passed"] is True
    assert agent.run(inp) == report
    assert bridge.calls.count("data_analysis.generated_program") == 1
