"""Recompute adaptor digests under the encoding recorded by their writer."""

import hashlib

from core.canonical_json import replay_json_bytes
from core.record_encoding import EncodingVersion
from workflows.adaptors import AdaptorOutcome, AdaptorRecord
from workflows.definition import AdaptorInstance


def replay_record(
    record: AdaptorRecord,
    outcome: AdaptorOutcome,
    adaptor: AdaptorInstance,
    version: EncodingVersion | None,
) -> AdaptorRecord:
    """Legacy hashes are reproduced here, never selected by the write path."""
    parameters = {
        "combine": adaptor.combine.model_dump(mode="json"),
        "select": adaptor.select.model_dump(mode="json"),
        "distribute": adaptor.distribute.model_dump(mode="json"),
    }
    outputs = tuple(
        digest.model_copy(
            update={
                "sha256": hashlib.sha256(
                    replay_json_bytes(output.value, version=version)
                ).hexdigest()
                if output.value is not None
                else None
            }
        )
        for digest, output in zip(record.outputs, outcome.outputs, strict=True)
    )
    return record.model_copy(
        update={
            "encoding_version": version,
            "parameters_sha256": hashlib.sha256(
                replay_json_bytes(parameters, version=version)
            ).hexdigest(),
            "outputs": outputs,
        }
    )
