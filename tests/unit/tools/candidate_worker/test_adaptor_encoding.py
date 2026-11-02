"""Version dispatch at the real adaptor readback boundary, without launches."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from core.canonical_json import canonical_json_bytes
from core.record_encoding import ENCODING_VERSION
from tests.helpers.candidate_fanout import selection_request
from tools.candidate_worker import adaptor_phase
from tools.candidate_worker.layout import adaptor_output_path
from workflows.adaptors import build_adaptor_record
from workflows.adaptors.run import AdaptorOutcome, AdaptorOutput

from .test_graph import initial


class Value(BaseModel):
    score: float


@pytest.mark.parametrize("legacy", [True, False])
@pytest.mark.parametrize("number", [float("inf"), float("-inf"), float("nan")])
def test_adaptor_replay_uses_recorded_version_and_preserves_bytes(
    prepared, monkeypatch, legacy, number
):
    """Legacy bytes/digests are built independently, never by the replay helper."""
    request = selection_request(prepared)
    parent = initial(request)
    workspace = Path(parent.workspace)
    adaptor = request.preview.document.definition.adaptors[0]
    outcome = AdaptorOutcome(
        status="succeeded",
        admissions=(),
        outputs=(AdaptorOutput(index=None, status="emitted", value=Value(score=number)),),
    )
    record = build_adaptor_record(
        adaptor_id=adaptor.id,
        iteration=1,
        combine=adaptor.combine,
        select=adaptor.select,
        distribute=adaptor.distribute,
        outcome=outcome,
    )
    monkeypatch.setattr(adaptor_phase, "decide", lambda *args, **kwargs: (outcome, record))
    (slot,) = adaptor_phase.expected_adaptors(request, parent)
    path = Path(slot.record_path)
    path.parent.mkdir(parents=True)
    output_path = adaptor_output_path(workspace, adaptor.id, "result", None)
    if legacy:
        # This is the exact pre-1111 encoding, including bare constants.
        output_bytes = json.dumps({"score": number}, sort_keys=True, separators=(",", ":")).encode()
        raw = record.model_dump(mode="json", exclude={"encoding_version"})
        raw["outputs"][0]["sha256"] = hashlib.sha256(output_bytes).hexdigest()
        record_bytes = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    else:
        assert record.encoding_version == ENCODING_VERSION
        output_bytes = canonical_json_bytes(outcome.outputs[0].value)
        record_bytes = canonical_json_bytes(record)
    path.write_bytes(record_bytes)
    output_path.write_bytes(output_bytes)
    entry = slot.model_copy(
        update={"state": "succeeded", "record_sha256": hashlib.sha256(record_bytes).hexdigest()}
    )
    result = adaptor_phase.verify_adaptors(
        request, parent, (), (entry,), workspace=workspace, iteration=1
    )
    assert result[adaptor.id] is outcome
    assert path.read_bytes() == record_bytes
    assert output_path.read_bytes() == output_bytes
    # A changed output cannot be laundered by recomputing its encoding version.
    output_path.write_bytes(b'{"score":0}')
    with pytest.raises(ValueError, match="output does not match"):
        adaptor_phase.verify_adaptors(
            request, parent, (), (entry,), workspace=workspace, iteration=1
        )
