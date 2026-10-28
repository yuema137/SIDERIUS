"""Custom adaptor manifest, catalog authority sets and output rules (no child process)."""

from __future__ import annotations

import json
import shutil
import types
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel

from workflows.custom_adaptors.admission import write_admission
from workflows.custom_adaptors.contracts import READABLE_CONTRACT_TYPES
from workflows.custom_adaptors.errors import CustomAdaptorError
from workflows.custom_adaptors.invocation import PortValues
from workflows.custom_adaptors.manifest import LoadedAdaptor, load_adaptor
from workflows.custom_adaptors.protected import stamp_protected
from workflows.custom_adaptors.runner import validate_output
from workflows.custom_adaptors.self_test import FixtureResult, SelfTestReport
from workflows.definition.catalog import CONTRACTS, CUSTOM_EMITTABLE, PROTECTED_FIELDS

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "custom_adaptors" / "sibling_digest"


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "project" / "adaptors" / "sibling_digest"
    shutil.copytree(FIXTURE, target)
    return target / "adaptor.json"


def _rewrite(manifest: Path, **changes: object) -> None:
    data = json.loads(manifest.read_text())
    data.update(changes)
    manifest.write_text(json.dumps(data))


def _model_of(annotation: object) -> object:
    """Strip Optional/list wrappers until a model or scalar remains."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        options = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        return _model_of(options[0])
    if origin in (list, tuple):
        return _model_of(typing.get_args(annotation)[0])
    return annotation


def test_every_protected_path_names_a_real_native_field() -> None:
    # Defect: the stamping walker yields nothing for a missing key, so a typo in
    # PROTECTED_FIELDS would silently stop protecting that field.
    assert set(PROTECTED_FIELDS) == set(CUSTOM_EMITTABLE)
    for contract, rules in PROTECTED_FIELDS.items():
        for rule in rules:
            current = _model_of(READABLE_CONTRACT_TYPES[contract])
            for part in rule.path.replace("[]", "").split("."):
                if not part:
                    continue
                assert isinstance(current, type) and issubclass(current, BaseModel), rule
                assert part in current.model_fields, (contract, rule.path)
                current = _model_of(current.model_fields[part].annotation)


def test_readable_types_match_catalog_contract_strings() -> None:
    # Defect: this module resolving a contract id to a different native model
    # than the catalog names would validate custom values against the wrong schema.
    for contract, value_type in READABLE_CONTRACT_TYPES.items():
        model = _model_of(value_type)
        if isinstance(model, type) and issubclass(model, BaseModel):
            assert f"{model.__module__}.{model.__qualname__}" in CONTRACTS[contract]


def test_identity_covers_helper_members_not_only_the_entry(tmp_path: Path) -> None:
    manifest = _copy(tmp_path)
    before = load_adaptor(manifest)
    helper = manifest.parent / "ranking.py"
    helper.write_text(helper.read_text() + "\n# edited helper\n")
    after = load_adaptor(manifest)
    assert after.identity_sha256 != before.identity_sha256
    assert after.manifest.digest == before.manifest.digest


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"output": {"contract": "validation.output"}}, "not emittable"),
        ({"output": {"contract": "tuning.output"}}, "not emittable"),
        ({"deterministic": False}, "deterministic"),
        ({"llm": {"roles": ["judge"]}}, "llm"),
        ({"entry": "missing.py:adapt"}, "not listed in members"),
    ],
)
def test_manifest_refuses_authority_outputs_and_v1_exclusions(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    manifest = _copy(tmp_path)
    _rewrite(manifest, **changes)
    with pytest.raises(CustomAdaptorError) as caught:
        load_adaptor(manifest)
    assert caught.value.reason == "manifest_invalid"
    assert message in str(caught.value)


def _loaded(tmp_path: Path, **changes: object) -> LoadedAdaptor:
    manifest = _copy(tmp_path)
    _rewrite(manifest, **changes)
    return load_adaptor(manifest)


def _item(**overrides: object) -> dict[str, object]:
    return {"source": "", "kind": "literature", "content": "c", "source_ref": "r", **overrides}


def test_combine_stamps_source_and_refuses_author_set_protected_fields(tmp_path: Path) -> None:
    loaded = _loaded(tmp_path)
    ports = (PortValues(name="reviews", contract="literature.output", values=[]),)
    output = validate_output(loaded, ports, [[_item()]])
    assert output.author[0][0]["source"] == ""
    assert output.stamped[0][0]["source"] == loaded.source_label
    for bad in (_item(source="human-expert"), _item(kind="human")):
        with pytest.raises(CustomAdaptorError) as caught:
            validate_output(loaded, ports, [[bad]])
        assert caught.value.reason == "custom_invalid_output"


def _review() -> dict[str, object]:
    case = json.loads((FIXTURE / "fixtures" / "two_reviews.input.json").read_text())
    review = case["inputs"]["reviews"][0]
    review["run_name"] = ""
    review["agent_card"]["agent_name"] = ""
    for finding in review["findings"]:
        finding["source"] = ""
    return review


def test_literature_output_cannot_claim_constraint_authority_or_chain_findings(
    tmp_path: Path,
) -> None:
    # Defect: a custom literature.output could set trust_level="hard_limit"
    # (constraint authority) or forge chain-mode findings and run attribution.
    loaded = _loaded(tmp_path, output={"contract": "literature.output"})
    ports = (PortValues(name="reviews", contract="literature.output", values=[]),)
    stamped = validate_output(loaded, ports, [_review()]).stamped[0]
    assert stamped["run_name"] == stamped["agent_card"]["agent_name"] == loaded.source_label
    forged_trust = _review()
    forged_trust["agent_card"]["trust_level"] = "hard_limit"
    forged_run = {**_review(), "run_name": "iteration-7"}
    forged_kind = _review()
    forged_kind["findings"][0]["kind"] = "findings"
    for bad in (forged_trust, forged_run, forged_kind):
        with pytest.raises(CustomAdaptorError) as caught:
            validate_output(loaded, ports, [bad])
        assert caught.value.reason == "custom_invalid_output"


def test_admission_record_is_write_once_unless_replaced(tmp_path: Path) -> None:
    manifest = _copy(tmp_path)
    project = tmp_path / "project"
    loaded = load_adaptor(manifest)

    def report(digest: str) -> SelfTestReport:
        return SelfTestReport(
            adaptor_id=loaded.manifest.id,
            identity_sha256=loaded.identity_sha256,
            manifest_sha256=loaded.manifest.digest,
            fixtures=(
                FixtureResult(
                    input="i", input_sha256=digest, expected_sha256=digest, output_sha256=digest
                ),
            ),
        )

    path = write_admission(project, loaded, report("a" * 64))
    first = path.read_bytes()
    assert write_admission(project, loaded, report("a" * 64)) == path
    with pytest.raises(CustomAdaptorError) as caught:
        write_admission(project, loaded, report("b" * 64))
    assert caught.value.reason == "admission_conflict"
    assert path.read_bytes() == first
    write_admission(project, loaded, report("b" * 64), replace=True)
    assert path.read_bytes() != first


def test_proposal_output_with_author_candidate_id_is_refused() -> None:
    # Only the framework mints candidate identity (D3-B protected field).
    proposal = {"candidate_id": "forged", "model_name": "m"}
    with pytest.raises(ValueError, match="candidate_id"):
        stamp_protected("proposal.output", [proposal], "adaptor:x@0")
    stamped = stamp_protected("proposal.output", [{"model_name": "m"}], "adaptor:x@0")
    assert stamped == [{"model_name": "m"}]


def test_select_indices_must_be_unique_in_range_and_bounded(tmp_path: Path) -> None:
    loaded = _loaded(
        tmp_path,
        role="select",
        output={"contract": "literature.output", "count": 2},
    )
    ports = (PortValues(name="reviews", contract="literature.output", values=[{}, {}, {}]),)
    assert validate_output(loaded, ports, [2, 0]).author == [2, 0]
    for bad in ([3], [0, 0], [0, 1, 2], ["0"], [True]):
        with pytest.raises(CustomAdaptorError) as caught:
            validate_output(loaded, ports, bad)
        assert caught.value.reason == "custom_invalid_output", bad


def test_distribute_partition_must_match_count_and_be_disjoint(tmp_path: Path) -> None:
    loaded = _loaded(
        tmp_path,
        role="distribute",
        output={"contract": "literature.output", "count": 2},
    )
    ports = (PortValues(name="reviews", contract="literature.output", values=[{}, {}]),)
    assert validate_output(loaded, ports, [[1], []]).author == [[1], []]
    for bad in ([[0]], [[0], [0]], [[2], []]):
        with pytest.raises(CustomAdaptorError):
            validate_output(loaded, ports, bad)
