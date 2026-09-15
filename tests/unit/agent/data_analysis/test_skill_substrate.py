from __future__ import annotations

import hashlib
import importlib.metadata
import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from agent.data_analysis.discovery import (
    SkillDiscoveryError,
    compute_pack_content_sha256,
    discover_skills,
    search_skill_cards,
)
from agent.data_analysis.executor import (
    SkillExecutorError,
    execute_skill,
    resolve_skill_interface,
    validate_skill_parameters,
)
from agent.data_analysis.loader import load_selected_skill
from agent.data_analysis.persistence import AnalysisRunStore
from agent.data_analysis.view_formats import MaterializedViewFormatError, load_materialized_view
from agent.data_analysis.worker_protocol import SkillWorkerRequest
from agent.schemas.data_analysis.assets import (
    AnalysisAuthorizationReceipt,
    MaterializedAnalysisView,
)
from agent.schemas.data_analysis.common import (
    CertifiedArtifactRef,
    canonical_json_bytes,
)
from agent.schemas.data_analysis.context import SkillPackRef
from agent.schemas.data_analysis.environment import AnalysisEnvironmentLock, EnvironmentPackage
from agent.schemas.data_analysis.skills import (
    SkillContentFile,
    SkillInput,
    SkillPackManifest,
    implementation_identity_sha256,
)
from agent.schemas.data_analysis.time import FixedTimePrecisionRequirement
from agent.schemas.storage import LocalStorageConfig, StorageConfig


def _skill_source(
    marker: Path | None = None,
    *,
    sleep: bool = False,
    invalid_usage: bool = False,
    artifact_type: str = "table",
) -> str:
    marker_line = "" if marker is None else f"Path({str(marker)!r}).write_text('imported')"
    if sleep:
        body = """
    import subprocess, sys, time
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    runtime.artifact_path("child.pid").write_text(str(child.pid))
    time.sleep(60)
"""
    else:
        usage = (
            "analysis_usage=SkillAnalysisUsage(effective_count=6, dropped_count=0),"
            if invalid_usage
            else ""
        )
        body = """
    view = runtime.load_materialization("binding-1")
    observed_mean = float(view.information["data"].mean())
    runtime.artifact_path("summary.json").write_text(json.dumps({"mean": observed_mean}))
    return SkillPayload(
        summary="Computed a deterministic summary.",
        quantitative_results=(QuantitativeResult(
            result_key="mean", value=observed_mean, description="Observed mean"
        ),),
        produced_artifacts=(ProducedArtifact(
            artifact_type="__ARTIFACT_TYPE__", logical_name="summary", media_type="application/json",
            relative_path="summary.json", description="Summary table"
        ),),
        __ANALYSIS_USAGE__
    )
""".replace("__ANALYSIS_USAGE__", usage).replace("__ARTIFACT_TYPE__", artifact_type)
    return f"""from pathlib import Path
import json
from pydantic import BaseModel, ConfigDict, Field
from agent.schemas.data_analysis.skills import (
    ProducedArtifact, QuantitativeResult, SkillAnalysisUsage, SkillPayload
)

{marker_line}

SKILL_INSTRUCTIONS = "Compute a deterministic mean over the selected numeric values."

class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_items: int = Field(default=5, ge=1, le=10)

def run(skill_input, parameters, runtime):
{body}
"""


def _make_pack(
    root: Path,
    source: str,
    *,
    skill_id: str = "summary_statistics",
    extra_files: dict[str, str] | None = None,
    environment_lock: AnalysisEnvironmentLock | None = None,
) -> SkillPackRef:
    root.mkdir()
    implementation = root / "skill.py"
    implementation.write_text(source)
    for relative_path, content in (extra_files or {}).items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    environment_ref = None
    if environment_lock is not None:
        lock_payload = canonical_json_bytes(environment_lock)
        lock_path = root / "environment-lock.json"
        lock_path.write_bytes(lock_payload)
        environment_ref = CertifiedArtifactRef(
            logical_ref="environment-lock.json",
            sha256=hashlib.sha256(lock_payload).hexdigest(),
            media_type="application/json",
            byte_size=len(lock_payload),
        )
    content_files = (
        SkillContentFile(
            relative_path="skill.py",
            sha256=hashlib.sha256(implementation.read_bytes()).hexdigest(),
        ),
    )
    implementation_sha = implementation_identity_sha256(content_files)
    body = {
        "schema_version": 1,
        "pack_id": "external-test-pack",
        "pack_version": "1.0.0",
        "title": "External test pack",
        "description": "A pack outside SIDERIUS source used by architecture tests.",
        "skills": [
            {
                "card": {
                    "skill_id": skill_id,
                    "title": "Summary statistics",
                    "one_line_description": "Computes a bounded deterministic summary.",
                    "keywords": ["summary", "statistics"],
                    "aliases": ["describe"],
                    "tags": ["core"],
                    "input_slots": [
                        {
                            "slot_id": "series",
                            "description": "Numeric series input.",
                            "accepted_asset_types": ["dataset"],
                            "accepted_view_formats": ["siderius.numeric-array.v1"],
                            "required_information": [{"information_class": "data", "fields": []}],
                            "optional_information": [],
                            "required": True,
                            "cardinality": "one",
                        }
                    ],
                    "produced_artifact_types": ["table"],
                    "applicable_when": "A materialized numeric summary view is available.",
                    "time_cost": "cheap",
                    "memory_cost": "low",
                    "preferred_device": "cpu",
                    "supports_sampling": True,
                    "skill_version": "1.0.0",
                    "determinism": "deterministic",
                    "numerical_tolerance": None,
                    "determinism_notes": None,
                },
                "entrypoint": {
                    "module_path": "skill.py",
                    "callable_symbol": "run",
                    "parameter_schema_symbol": "Parameters",
                    "instructions_symbol": "SKILL_INSTRUCTIONS",
                },
                "implementation_files": [item.model_dump(mode="json") for item in content_files],
                "implementation_sha256": implementation_sha,
            }
        ],
        "pack_content_sha256": "0" * 64,
    }
    manifest = SkillPackManifest.model_validate(body)
    manifest_path = root / "manifest.json"
    manifest = manifest.model_copy(
        update={
            "pack_content_sha256": compute_pack_content_sha256(
                root, manifest, manifest_path=manifest_path
            )
        }
    )
    payload = canonical_json_bytes(manifest)
    manifest_path.write_bytes(payload)
    return SkillPackRef(
        pack_id="external-test-pack",
        pack_root=str(root),
        manifest_ref=CertifiedArtifactRef(
            logical_ref="manifest.json",
            sha256=hashlib.sha256(payload).hexdigest(),
            media_type="application/json",
            byte_size=len(payload),
        ),
        environment_lock_ref=environment_ref,
    )


def _skill_input(tmp_path: Path, skill, deadline: float) -> tuple[SkillInput, Path]:
    data = tmp_path / "materialized.npz"
    np.savez(
        data,
        example_ids=np.arange(5),
        information__data=np.asarray([1.0, 2.0, 2.5, 3.0, 4.0]),
    )
    payload = data.read_bytes()
    receipt = AnalysisAuthorizationReceipt(
        invocation_id="invocation-1",
        binding_id="binding-1",
        slot_id="series",
        request_digest="1" * 64,
        policy_digest="2" * 64,
        asset_digest="3" * 64,
        authorized_at="2026-09-14T00:00:00+00:00",
    )
    view = MaterializedAnalysisView(
        materialization_id="view-1",
        invocation_id="invocation-1",
        binding_id="binding-1",
        slot_id="series",
        asset_id="asset-1",
        split_id="validation",
        content_ref=CertifiedArtifactRef(
            logical_ref="materialized.npz",
            sha256=hashlib.sha256(payload).hexdigest(),
            media_type="application/x-npz",
            byte_size=len(payload),
        ),
        format_id="siderius.numeric-array.v1",
        population_unit="examples",
        total_available=10,
        materialized_count=5,
        certified_information=({"information_class": "data"},),
        selection_identity={
            "selection_id": "selection-1",
            "selection_sha256": "5" * 64,
            "sampling_policy_sha256": "6" * 64,
            "sampling_mode": "fixed",
            "sampling_strategy": "uniform",
            "sampling_seed": 0,
            "population_unit": "examples",
            "total_available": 10,
            "selected_count": 5,
        },
        source_digests=(hashlib.sha256(payload).hexdigest(),),
        authorization_receipt=receipt,
    )
    skill_input = SkillInput(
        invocation_id="invocation-1",
        skill_identity=skill.identity,
        materializations=(view,),
        question_ids=("question-1",),
        deadline_monotonic_s=deadline,
        artifact_output_contract={
            "output_directory_ref": "staging/invocation-1",
            "allowed_media_types": ["application/json"],
        },
    )
    return skill_input, data


def test_out_of_tree_discovery_does_not_import_and_loads_only_after_selection(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "import-marker"
    pack_ref = _make_pack(tmp_path / "external-pack", _skill_source(marker))

    snapshot = discover_skills((pack_ref,))

    assert not marker.exists()
    selected = search_skill_cards(snapshot, "describe dataset", limit=1)
    assert selected[0].card.skill_id == "summary_statistics"
    interface = resolve_skill_interface(
        selected[0], control_directory=tmp_path / "interface", timeout_s=3.0
    )
    assert marker.read_text() == "imported"
    assert "max_items" in interface.parameter_json_schema["properties"]
    assert interface.selected_skill_instructions.startswith("Compute a deterministic mean")


@pytest.mark.allow_real_subprocess
def test_parameters_are_validated_against_the_resolved_schema(tmp_path: Path) -> None:
    skill = discover_skills((_make_pack(tmp_path / "external-pack", _skill_source()),)).skills[0]
    interface = resolve_skill_interface(
        skill, control_directory=tmp_path / "interface", timeout_s=3.0
    )

    with pytest.raises(SkillExecutorError, match="parameter validation failed"):
        validate_skill_parameters(
            skill,
            interface,
            {"max_items": 100},
            control_directory=tmp_path / "validation",
            timeout_s=3.0,
        )


def test_interface_resolution_transport_cannot_carry_materialized_data(tmp_path: Path) -> None:
    skill = discover_skills((_make_pack(tmp_path / "external-pack", _skill_source()),)).skills[0]

    with pytest.raises(ValidationError, match="cannot carry parameters, materialized data"):
        SkillWorkerRequest(
            mode="resolve_interface",
            discovered_skill=skill,
            materialization_paths={"binding-1": str(tmp_path / "secret.npz")},
        )


def test_runtime_owned_numeric_view_is_read_only_and_rejects_hidden_fields(
    tmp_path: Path,
) -> None:
    skill = discover_skills((_make_pack(tmp_path / "external-pack", _skill_source()),)).skills[0]
    skill_input, data = _skill_input(tmp_path, skill, time.monotonic() + 5.0)
    descriptor = skill_input.materializations[0]

    loaded = load_materialized_view(descriptor, data)
    assert loaded.information["data"].shape == (5,)
    with pytest.raises(ValueError, match="read-only"):
        loaded.information["data"][0] = 99.0

    np.savez(
        data,
        example_ids=np.arange(5),
        information__data=np.arange(5.0),
        metadata__secret=np.arange(5.0),
    )
    payload = data.read_bytes()
    broader_descriptor = descriptor.model_copy(
        update={
            "content_ref": CertifiedArtifactRef(
                logical_ref="materialized.npz",
                sha256=hashlib.sha256(payload).hexdigest(),
                media_type="application/x-npz",
                byte_size=len(payload),
            ),
            "source_digests": (hashlib.sha256(payload).hexdigest(),),
        }
    )
    with pytest.raises(MaterializedViewFormatError, match="not listed"):
        load_materialized_view(broader_descriptor, data)


def test_runtime_owned_time_series_view_has_a_versioned_shape_contract(tmp_path: Path) -> None:
    skill = discover_skills((_make_pack(tmp_path / "external-pack", _skill_source()),)).skills[0]
    skill_input, data = _skill_input(tmp_path, skill, time.monotonic() + 5.0)
    descriptor = skill_input.materializations[0]
    np.savez(
        data,
        example_ids=np.arange(5),
        time=np.tile(np.arange(4.0), (5, 1)),
        time_certified_regular=np.ones(5, dtype=np.bool_),
        time_required_resolution_seconds=np.full(5, 1e-12, dtype=np.float64),
        channel_ids=np.asarray(["strain", "aux"]),
        valid_mask=np.ones((5, 4), dtype=np.bool_),
        information__data=np.ones((5, 2, 4)),
    )
    payload = data.read_bytes()
    timeseries_descriptor = descriptor.model_copy(
        update={
            "format_id": "siderius.timeseries-array.v1",
            "time_precision_requirement": FixedTimePrecisionRequirement(
                required_resolution_seconds=1e-12
            ),
            "content_ref": CertifiedArtifactRef(
                logical_ref="materialized.npz",
                sha256=hashlib.sha256(payload).hexdigest(),
                media_type="application/x-npz",
                byte_size=len(payload),
            ),
            "source_digests": (hashlib.sha256(payload).hexdigest(),),
        }
    )

    loaded = load_materialized_view(timeseries_descriptor, data)

    assert loaded.time_axis.kind == "explicit"
    assert loaded.time_seconds(0).shape == (4,)
    assert loaded.is_time_certified_regular(0)
    assert loaded.information["data"].shape == (5, 2, 4)
    assert loaded.valid_mask.shape == (5, 4)


def test_pack_digest_conservatively_covers_undeclared_pack_helpers(tmp_path: Path) -> None:
    pack_root = tmp_path / "external-pack"
    pack_ref = _make_pack(
        pack_root,
        _skill_source(),
        extra_files={"helpers/constants.py": "VALUE = 1\n", "README.md": "pack docs\n"},
    )
    skill = discover_skills((pack_ref,)).skills[0]

    (pack_root / "helpers" / "constants.py").write_text("VALUE = 2\n")

    with pytest.raises(SkillDiscoveryError, match="pack content digest mismatch"):
        load_selected_skill(skill)


@pytest.mark.allow_real_subprocess
def test_environment_lock_is_verified_before_selected_import(tmp_path: Path) -> None:
    matching_lock = AnalysisEnvironmentLock(
        python_version=".".join(str(value) for value in sys.version_info[:3]),
        packages=(
            EnvironmentPackage(
                name="pydantic",
                version=importlib.metadata.version("pydantic"),
            ),
        ),
    )
    matching_skill = discover_skills(
        (
            _make_pack(
                tmp_path / "matching-pack",
                _skill_source(),
                environment_lock=matching_lock,
            ),
        )
    ).skills[0]
    assert load_selected_skill(matching_skill).environment_lock_verified is True
    assert matching_skill.identity.environment_lock_sha256 is not None

    marker = tmp_path / "import-marker"
    mismatched_lock = matching_lock.model_copy(
        update={
            "packages": (
                EnvironmentPackage(
                    name="pydantic",
                    version=f"{importlib.metadata.version('pydantic')}.not-active",
                ),
            )
        }
    )
    skill = discover_skills(
        (
            _make_pack(
                tmp_path / "mismatched-pack",
                _skill_source(marker),
                environment_lock=mismatched_lock,
            ),
        )
    ).skills[0]

    with pytest.raises(SkillExecutorError, match="active runtime has"):
        resolve_skill_interface(skill, control_directory=tmp_path / "interface", timeout_s=3.0)
    assert not marker.exists()


def test_skill_input_refuses_independently_sampled_aligned_bindings(tmp_path: Path) -> None:
    pack_ref = _make_pack(tmp_path / "external-pack", _skill_source())
    skill = discover_skills((pack_ref,)).skills[0]
    skill_input, _data = _skill_input(tmp_path, skill, time.monotonic() + 5.0)
    payload = skill_input.model_dump(mode="json")
    second = dict(payload["materializations"][0])
    second["materialization_id"] = "view-2"
    second["binding_id"] = "binding-2"
    second["authorization_receipt"] = dict(second["authorization_receipt"])
    second["authorization_receipt"]["binding_id"] = "binding-2"
    second["selection_identity"] = dict(second["selection_identity"])
    second["selection_identity"]["selection_id"] = "selection-2"
    second["selection_identity"]["selection_sha256"] = "7" * 64
    payload["materializations"].append(second)

    with pytest.raises(ValidationError, match="share one certified selection"):
        SkillInput.model_validate(payload)


@pytest.mark.allow_real_subprocess
def test_bounded_executor_validates_runs_and_certifies_artifacts(tmp_path: Path) -> None:
    pack_ref = _make_pack(tmp_path / "external-pack", _skill_source())
    skill = discover_skills((pack_ref,)).skills[0]
    store = AnalysisRunStore(
        StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path / "workspace"), run_name="run-1"),
        ),
        request_id="request-1",
    )
    validated = validate_skill_parameters(
        skill,
        resolve_skill_interface(
            skill,
            control_directory=store.root / "control" / "interface-1",
            timeout_s=3.0,
        ),
        {"max_items": 5},
        control_directory=store.root / "control" / "validate-1",
        timeout_s=3.0,
    )
    staging = store.staging_directory("invocation-1")
    skill_input, data = _skill_input(tmp_path, skill, time.monotonic() + 5.0)

    result = execute_skill(
        result_id="result-1",
        skill=skill,
        validated_parameters=validated,
        skill_input=skill_input,
        materialization_paths={"binding-1": str(data)},
        store=store,
        staging_directory=staging,
        control_directory=store.root / "control" / "execute-1",
        plan_sha256="4" * 64,
        timeout_s=3.0,
    )

    assert result.status == "completed"
    assert result.coverage is not None and result.coverage.analyzed_count == 5
    assert len(result.artifact_refs) == 1
    store.resolve_and_verify(result.artifact_refs[0])


@pytest.mark.allow_real_subprocess
def test_timeout_terminates_the_worker_process_tree(tmp_path: Path) -> None:
    pack_ref = _make_pack(
        tmp_path / "timeout-pack", _skill_source(sleep=True), skill_id="slow_skill"
    )
    skill = discover_skills((pack_ref,)).skills[0]
    store = AnalysisRunStore(
        StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path / "workspace"), run_name="run-1"),
        ),
        request_id="request-1",
    )
    validated = validate_skill_parameters(
        skill,
        resolve_skill_interface(
            skill,
            control_directory=store.root / "control" / "interface-1",
            timeout_s=3.0,
        ),
        {"max_items": 5},
        control_directory=store.root / "control" / "validate-1",
        timeout_s=3.0,
    )
    staging = store.staging_directory("invocation-1")
    skill_input, data = _skill_input(tmp_path, skill, time.monotonic() + 1.0)

    result = execute_skill(
        result_id="result-1",
        skill=skill,
        validated_parameters=validated,
        skill_input=skill_input,
        materialization_paths={"binding-1": str(data)},
        store=store,
        staging_directory=staging,
        control_directory=store.root / "control" / "execute-1",
        plan_sha256="4" * 64,
        timeout_s=0.3,
    )

    assert result.status == "timed_out"
    child_pid = int((staging / "child.pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


@pytest.mark.allow_real_subprocess
@pytest.mark.parametrize(
    ("source", "expected_failure"),
    [
        (_skill_source(invalid_usage=True), "invalid_analysis_usage"),
        (_skill_source(artifact_type="plot"), "artifact_certification"),
    ],
)
def test_executor_rejects_uncertified_skill_claims(
    tmp_path: Path,
    source: str,
    expected_failure: str,
) -> None:
    skill = discover_skills((_make_pack(tmp_path / "external-pack", source),)).skills[0]
    store = AnalysisRunStore(
        StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path / "workspace"), run_name="run-1"),
        ),
        request_id="request-1",
    )
    interface = resolve_skill_interface(
        skill,
        control_directory=store.root / "control" / "interface-1",
        timeout_s=3.0,
    )
    validated = validate_skill_parameters(
        skill,
        interface,
        {"max_items": 5},
        control_directory=store.root / "control" / "validate-1",
        timeout_s=3.0,
    )
    skill_input, data = _skill_input(tmp_path, skill, time.monotonic() + 5.0)

    result = execute_skill(
        result_id="result-1",
        skill=skill,
        validated_parameters=validated,
        skill_input=skill_input,
        materialization_paths={"binding-1": str(data)},
        store=store,
        staging_directory=store.staging_directory("invocation-1"),
        control_directory=store.root / "control" / "execute-1",
        plan_sha256="4" * 64,
        timeout_s=3.0,
    )

    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.failure_type == expected_failure
