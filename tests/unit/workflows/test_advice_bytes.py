"""The advice owner's bytes entrypoint and its path loader share one parser.

Defects caught: a path-free caller (the candidate console) accepting an
artifact the CLI refuses, or the CLI loader losing a refusal or changing its
message text once it delegates to ``parse_advice_bytes``.
"""

import hashlib
import json

import pytest

from workflows.advice import AdviceArtifactError, load_advice_artifact, parse_advice_bytes

# One witness per non-equivalent input class, with the phrase its refusal must carry.
REFUSALS = {
    "invalid_json": (b"{not json", "is not valid JSON"),
    "not_object": (b'["propose"]', "must be a JSON object of advice keys; got list."),
    "misspelled_key": (b'{"propse": "x"}', "declares top-level keys no agent reads: 'propse'"),
    "ill_typed": (b'{"propose": {"a": 1}}', "neither a string nor a list of strings"),
    "empty_join": (b'{"propose": ["", ""]}', "with empty content"),
    "no_recognised_key": (b'{"_meta": "x"}', "carries no recognised advice key"),
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_bytes_and_path_entrypoints_refuse_with_identical_text(case, tmp_path):
    data, phrase = REFUSALS[case]
    path = tmp_path / "advice.json"
    path.write_bytes(data)
    with pytest.raises(AdviceArtifactError) as from_path:
        load_advice_artifact(str(path))
    with pytest.raises(AdviceArtifactError) as from_bytes:
        parse_advice_bytes(data, label=str(path))
    assert phrase in str(from_path.value)
    assert str(from_bytes.value) == str(from_path.value)
    assert f"sha256={hashlib.sha256(data).hexdigest()}" in str(from_bytes.value)


def test_bytes_entrypoint_returns_the_path_loaders_artifact(tmp_path):
    data = json.dumps({"propose": ["a", "b"], "tune": "c", "_meta": "inert"}).encode()
    path = tmp_path / "advice.json"
    path.write_bytes(data)
    artifact = parse_advice_bytes(data, label=str(path))
    assert artifact == load_advice_artifact(str(path))
    assert artifact.sha256 == hashlib.sha256(data).hexdigest()
    assert artifact.content == json.loads(data)


def test_path_loader_keeps_digest_certification_and_missing_file_refusals(tmp_path):
    """The two refusals only the path loader owns still fire before any parse."""
    path = tmp_path / "advice.json"
    with pytest.raises(AdviceArtifactError, match="advice artifact not found"):
        load_advice_artifact(str(path))
    path.write_bytes(b"{not json")  # certification precedes parsing
    with pytest.raises(AdviceArtifactError, match="identity cannot be certified"):
        load_advice_artifact(str(path), declared_sha256="0" * 64)
