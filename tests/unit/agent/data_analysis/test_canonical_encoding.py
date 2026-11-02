"""UTF-8 identity migration: strict bytes, lossless readers and legacy witnesses."""

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pytest

from agent.data_analysis.persistence import AnalysisPersistenceError, AnalysisRunStore
from agent.schemas.data_analysis.common import (
    FrozenModel,
    canonical_json_bytes,
    canonical_sha256,
    replay_json_bytes,
)
from agent.schemas.data_analysis.skills import QuantitativeResult
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.record_encoding import ENCODING_VERSION, decode_record


class _Payload(FrozenModel):
    values: dict[str, Any]


def _refuse_constant(token: str) -> None:
    raise AssertionError(f"non-JSON constant: {token}")


@pytest.mark.parametrize("number", [float("inf"), float("-inf"), float("nan")])
def test_canonical_model_and_dictionary_preserve_float_types(number: float) -> None:
    """Reverting loses model floats or emits forbidden bare dictionary constants."""
    values = {"测量": [number, None, "NaN", "Infinity", "-Infinity", 3.0]}
    model = _Payload(values=values)
    data = canonical_json_bytes(model)
    assert data == canonical_json_bytes({"values": values})
    raw = json.loads(data, parse_constant=_refuse_constant)
    assert raw["$siderius_encoding"]["version"] == "siderius.nonfinite/v1"
    assert b"\\u6d4b" not in data
    restored = _Payload.model_validate_json(data).values["测量"]
    assert isinstance(restored[0], float)
    assert math.isnan(restored[0]) if math.isnan(number) else restored[0] == number
    assert restored[1:] == [None, "NaN", "Infinity", "-Infinity", 3.0]
    assert canonical_json_bytes(decode_record(raw)) == data
    assert len({canonical_sha256({"v": v}) for v in [number, None, str(number)]}) == 3


def test_fixed_legacy_utf8_and_nonfinite_archive_bytes() -> None:
    """Legacy dict constants and model nulls have different historical identities."""
    finite = {"标签": [None, 1.25, "Infinity"]}
    expected = '{"标签":[null,1.25,"Infinity"]}'.encode()
    assert canonical_json_bytes(finite) == expected
    assert replay_json_bytes(finite, version=None) == expected
    legacy_dict = '{"标签":Infinity}'.encode()
    value = {"标签": float("inf")}
    assert replay_json_bytes(value, version=None) == legacy_dict
    assert hashlib.sha256(legacy_dict).hexdigest() == (
        "6c7f5009282111875edfec91e86584ae1987a2035f72bb25dc2a372e67c81434"
    )
    legacy_model = b'{"values":{"score":null}}'
    assert replay_json_bytes(_Payload(values={"score": float("inf")}), version=None) == legacy_model
    archived = _Payload.model_validate_json(legacy_model)
    assert archived.values["score"] is None
    assert canonical_json_bytes(archived) == legacy_model
    assert canonical_json_bytes(_Payload(values={"score": float("inf")})) != legacy_model
    assert replay_json_bytes(value, version=ENCODING_VERSION) == canonical_json_bytes(value)


@pytest.mark.parametrize("number", [float("inf"), float("-inf"), float("nan"), 0.125])
def test_analysis_store_publishes_lossless_quantitative_record(
    tmp_path: Path, number: float
) -> None:
    """Exercise the production writer and inherited typed reader, not just helpers."""
    store = AnalysisRunStore(
        StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="encoding"),
        ),
        request_id="r",
    )
    measurement = QuantitativeResult(result_key="score", value=number, description="measurement")
    ref = store._write_model_once("measurement.json", measurement)
    data = store.resolve_and_verify(ref).read_bytes()
    json.loads(data, parse_constant=_refuse_constant)
    restored = QuantitativeResult.model_validate_json(data)
    assert isinstance(restored.value, float)
    assert math.isnan(restored.value) if math.isnan(number) else restored.value == number
    assert ref.sha256 == hashlib.sha256(data).hexdigest()


def test_scientific_input_projection_does_not_collapse_metadata(tmp_path: Path) -> None:
    """The host-independent identity must retain arbitrary numeric metadata."""
    from tests.unit.nodes.test_data_analysis_agent import _input

    original = _input(tmp_path)
    store = AnalysisRunStore(original.storage, request_id=original.request_id)
    store.root.mkdir(parents=True)
    identities = []
    for value in (float("inf"), float("nan"), None):
        asset = {
            **original.available_assets[0].model_dump(),
            "metadata": {"score": value},
            "metadata_sources": {"score": {"information_class": "identity"}},
        }
        inp = type(original).model_validate({**original.model_dump(), "available_assets": [asset]})
        identities.append(inp.canonical_scientific_digest())
        if value is not None:
            legacy = replay_json_bytes(inp, version=None)
            (store.root / "input.json").write_bytes(legacy)
            with pytest.raises(
                AnalysisPersistenceError, match="different canonical input identity"
            ):
                store.resume_completed_report(inp)
            assert (store.root / "input.json").read_bytes() == legacy
    assert len(set(identities)) == 3


def test_generated_interface_identity_survives_registry_and_discovery(tmp_path: Path) -> None:
    """Any-valued parameter schemas must survive every enclosing identity projection."""
    from agent.data_analysis.discovery import DiscoveredGeneratedExperimentSkill
    from agent.data_analysis.generated_skill_registry import promote_generated_program
    from agent.schemas.data_analysis.generated_skill import GeneratedExperimentSkillRegistry
    from agent.schemas.data_analysis.skills import ResolvedSkillInterface
    from tests.unit.agent.data_analysis.test_generated_skill_registry import (
        _persist_program,
        _promotion_draft,
    )

    source = tmp_path / "source"
    program, identity = _persist_program(source)
    registry, _ = promote_generated_program(
        source_root=source,
        registry_root=tmp_path / "registry",
        registry_id="encoding",
        existing=None,
        program=program,
        program_identity=identity,
        draft=_promotion_draft(),
        originating_request_id="r",
        originating_result_id="result",
    )
    skill = registry.skills[0]
    schema = {"default": float("inf"), "description": "用户 schema"}
    interface = ResolvedSkillInterface(
        skill_identity=skill.skill_identity,
        parameter_json_schema=schema,
        parameter_schema_sha256=canonical_sha256(schema),
        selected_skill_instructions="Measure.",
    )
    promoted = skill.model_copy(update={"resolved_interface": interface})
    executable = promoted.executable_identity_body()
    assert executable["resolved_interface"]["parameter_json_schema"]["default"] == float("inf")
    body = {
        "schema_version": 1,
        "registry_id": "encoding",
        "skills": [
            executable
            | {"promotion_provenance": promoted.promotion_provenance.model_dump(mode="json")}
        ],
    }
    updated = GeneratedExperimentSkillRegistry(**body, registry_sha256=canonical_sha256(body))
    restored = GeneratedExperimentSkillRegistry.model_validate_json(canonical_json_bytes(updated))
    assert restored.registry_sha256 == updated.registry_sha256
    discovered = DiscoveredGeneratedExperimentSkill(
        identity=promoted.skill_identity,
        card=promoted.declaration.card,
        program_identity=promoted.program_identity,
        resolved_interface=interface,
        registry_root=str(tmp_path),
        program_declaration_ref=promoted.program_declaration_ref,
    )
    assert discovered.identity_dump()["resolved_interface"]["parameter_json_schema"][
        "default"
    ] == float("inf")


@pytest.mark.allow_real_subprocess
def test_skill_worker_parameter_transport_and_digest_preserve_nonfinite(tmp_path: Path) -> None:
    """A real child must return distinct parameter identities and retain their values.

    The parameter is untyped because Pydantic's JSON-mode dump keeps non-finite
    floats in typed float fields but projects them to null in ``Any`` fields;
    only the untyped declaration discriminates the loader and worker encodings.
    """
    from agent.data_analysis.discovery import DiscoveredSkill, discover_skills
    from agent.data_analysis.executor import resolve_skill_interface, validate_skill_parameters
    from tests.unit.agent.data_analysis.test_skill_substrate import _make_pack, _skill_source

    source = _skill_source().replace(
        "max_items: int = Field(default=5, ge=1, le=10)",
        "max_items: __import__('typing').Any = 5.0",
    )
    skill = discover_skills((_make_pack(tmp_path / "pack", source),)).skills[0]
    assert isinstance(skill, DiscoveredSkill)
    interface = resolve_skill_interface(
        skill, control_directory=tmp_path / "interface", timeout_s=10.0
    )
    digests = []
    for index, value in enumerate((float("inf"), float("-inf"), float("nan"), None, 0.5)):
        validated = validate_skill_parameters(
            skill,
            interface,
            {"max_items": value},
            control_directory=tmp_path / f"validate-{index}",
            timeout_s=10.0,
        )
        restored = validated.parameters["max_items"]
        if isinstance(value, float) and math.isnan(value):
            assert isinstance(restored, float) and math.isnan(restored)
        else:
            assert restored == value
        assert validated.validated_parameters_sha256 == canonical_sha256({"max_items": value})
        digests.append(validated.validated_parameters_sha256)
    assert len(set(digests)) == 5
