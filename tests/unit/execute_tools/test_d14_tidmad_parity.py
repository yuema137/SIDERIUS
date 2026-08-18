"""D14-1 parity: the current implementation vs the FROZEN pre-relocation manifest.

Child design FROZEN rev 2 §5 (C2a) / §6. Two claims, deliberately separate:

1. the committed manifest is BYTE-IMMUTABLE and really was generated at the
   pre-relocation head — the recorded commit predates every relocation
   commit, which is what makes the comparison non-self-referential;
2. the CURRENT implementation reproduces it exactly.

Before C2b, (2) is a determinism proof. From C2b onward it is THE parity
oracle: the expected side comes from the committed artifact, never from a
second runtime call (the #221 self-reference rule, applied).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from tests.helpers.d14_tidmad_parity import MANIFEST_PATH, build_evidence, load_manifest

#: sha256 of the committed manifest file, hardcoded at capture time.
#: If this fails, someone edited the evidence — which is exactly the event
#: it exists to make loud (child §5: "BYTE-IMMUTABLE for the life of the PR").
MANIFEST_SHA256 = "341b232c9a1422f5a1fbaef874caab4c2faea31e52fe6d73a2aca4d28496546b"

#: The pre-relocation head the manifest was generated from (C1's commit —
#: TIDMADEpochDataset still lives at its original site there).
PRE_RELOCATION_COMMIT = "a715b84e8b980bbb378685c66046e71b77d3615c"


def test_the_manifest_is_byte_immutable_and_pre_relocation():
    raw = MANIFEST_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == MANIFEST_SHA256, (
        "the frozen parity manifest was MODIFIED. Expected values are frozen "
        "at the pre-relocation head; regenerate is forbidden for the life of "
        "PR D14-1 (child design §5 C2a)."
    )
    manifest = load_manifest()
    assert manifest["_provenance"]["generated_from_commit"] == PRE_RELOCATION_COMMIT


def test_current_implementation_reproduces_the_frozen_evidence(tmp_path: Path):
    """THE parity oracle. Expected = the committed artifact; actual = the
    implementation as it exists now, whichever side of the relocation we are
    on. A drifted fixture surfaces in the 'fixture' block first, so a
    dataset regression is never misattributed to fixture noise."""
    expected = load_manifest()["evidence"]
    actual = build_evidence(tmp_path)
    assert actual["fixture"] == expected["fixture"], "the FIXTURE drifted, not the dataset"
    assert actual["training_streams"] == expected["training_streams"]
    assert actual["validation"] == expected["validation"]
    assert actual["deliverable"] == expected["deliverable"]
