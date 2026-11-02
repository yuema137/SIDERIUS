"""Lossless strict record encoding, including ambiguous strings and old bytes."""

import json
import math
from typing import Any

import pytest
from pydantic import ConfigDict

from core.canonical_json import canonical_json_bytes, replay_json_bytes
from core.record_encoding import (
    ENCODING_VERSION,
    METADATA,
    RecordModel,
    decode_record,
    encoded_record,
    record_json,
)


class Record(RecordModel):
    model_config = ConfigDict(strict=True)
    values: tuple[Any, ...]


def strict_json(payload):
    def refuse(token):
        raise AssertionError(f"bare JSON constant: {token}")

    return json.loads(payload, parse_constant=refuse)


@pytest.mark.parametrize("number", [float("inf"), float("-inf"), float("nan")])
def test_versioned_round_trip_preserves_type_sign_and_strict_json_semantics(number):
    value = Record(values=(number, "NaN", "Infinity", None, {"nested": [number]}))
    payload = record_json(value)
    raw = strict_json(payload)
    assert raw[METADATA]["version"] == ENCODING_VERSION
    assert raw["values"][0] is not None
    restored = Record.model_validate_json(payload)
    result = restored.values[0]
    assert type(result) is float
    assert math.isnan(result) if math.isnan(number) else result == number
    assert restored.values[1:4] == ("NaN", "Infinity", None)
    assert record_json(restored) == payload


def test_canonical_new_and_legacy_bytes_are_separate_and_finite_bytes_stay_identical():
    value = {"score": float("-inf")}
    new = canonical_json_bytes(value)
    strict_json(new)
    assert decode_record(json.loads(new)) == value
    assert replay_json_bytes(value, version=None) == b'{"score":-Infinity}'
    assert replay_json_bytes(value, version=ENCODING_VERSION) == new
    assert canonical_json_bytes({"b": 2, "a": "é"}) == b'{"a":"\\u00e9","b":2}'
    old = b'{"values":[-Infinity,"NaN",null]}'
    assert Record.model_validate_json(old).values == (float("-inf"), "NaN", None)


@pytest.mark.parametrize(
    "metadata",
    [
        {"version": "future", "floats": []},
        {"version": ENCODING_VERSION, "floats": [["missing"]]},
        {"version": ENCODING_VERSION, "floats": [["score"], ["score"]]},
        {"version": ENCODING_VERSION, "floats": [[]]},
    ],
)
def test_malformed_encoding_is_not_silently_treated_as_legacy(metadata):
    with pytest.raises(ValueError):
        decode_record({"score": "NaN", METADATA: metadata})


def test_metadata_collision_is_refused_before_publication():
    with pytest.raises(ValueError, match="reserved"):
        encoded_record({METADATA: "task-owned data"})


def test_local_recorder_preserves_float_evidence_and_old_summary_bytes(tmp_path):
    from core.recorders import LocalRecorder

    summary = tmp_path / "summary.json"
    legacy = b'[{"exp_id":"old","loss":null}]'
    summary.write_bytes(legacy)
    recorder = LocalRecorder(str(tmp_path / "records"), str(summary), "run")
    assert recorder.get_summary() == [{"exp_id": "old", "loss": None}]
    assert summary.read_bytes() == legacy
    recorder.save_record({"exp_id": "new", "loss": float("nan"), "history": [1.0, float("-inf")]})
    rows = recorder.get_summary()
    assert rows[0] == {"exp_id": "old", "loss": None}
    assert math.isnan(rows[1]["loss"])
    assert rows[1]["history"] == [1.0, float("-inf")]
    strict_json(summary.read_bytes())
    for line in (tmp_path / "records/run/records.jsonl").read_bytes().splitlines():
        strict_json(line)


def test_canonical_wrapping_cannot_collide_with_a_record_having_a_value_field():
    scalar = canonical_json_bytes(float("inf"))
    mapping = canonical_json_bytes({"value": float("inf")})
    sequence = canonical_json_bytes([float("inf")])
    assert len({scalar, mapping, sequence}) == 3
    assert decode_record(strict_json(scalar)) == float("inf")
    assert decode_record(strict_json(sequence)) == [float("inf")]


def test_nonfinite_canonical_bytes_ignore_dictionary_insertion_order():
    left = {"a": float("inf"), "b": {"x": float("nan"), "y": float("-inf")}}
    right = {"b": {"y": float("-inf"), "x": float("nan")}, "a": float("inf")}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert canonical_json_bytes([left]) == canonical_json_bytes([right])


@pytest.mark.parametrize("count", [0, 1, 20, 2048])
def test_record_paths_preserve_array_positions_at_small_and_large_sizes(count):
    value = Record(values=tuple(float("-inf") if i % 2 else float("inf") for i in range(count)))
    payload = record_json(value)
    strict_json(payload)
    restored = Record.model_validate_json(payload)
    assert restored.values == value.values
    assert record_json(restored) == payload


@pytest.mark.parametrize(
    "floats",
    [[["score"], ["score"]], [["values", 0], ["values", 1], ["values", 0]]],
    ids=["duplicate", "duplicate-after-another-path"],
)
def test_duplicate_float_paths_are_refused_by_the_seen_path_check(floats):
    """Defect (#1326): a repeated typed path is accepted or refused only incidentally.

    Without the seen-path check the second dereference reaches an already-restored
    float and fails with the generic reference error; this asserts the explicit
    duplicate refusal, so removing the check fails the ``match``.
    """
    record = {"score": "NaN", "values": ["Infinity", "-Infinity"]}
    with pytest.raises(ValueError, match="duplicate non-finite float path"):
        decode_record({**record, METADATA: {"version": ENCODING_VERSION, "floats": floats}})


@pytest.mark.parametrize(
    "floats",
    [[["values"], ["values", 0]], [["values", 0], ["values"]]],
    ids=["parent-first", "child-first"],
)
def test_overlapping_float_paths_cannot_restore_a_container(floats):
    """Defect: overlapping paths (a container and one of its leaves) decode to a value.

    Neither order may succeed: the container is not a token, and after it is
    restored its leaf cannot be dereferenced.
    """
    record = {"values": ["Infinity"], METADATA: {"version": ENCODING_VERSION, "floats": floats}}
    with pytest.raises(ValueError, match="invalid non-finite float reference"):
        decode_record(record)
