"""PR-02b B3 — the two serialization sites obey ONE boundary contract.

B1 pinned the round trip at each site independently: string keys out,
values preserved, invalid input rejected before launch. What it could not
express is a property *between* the sites — that they serialize the same
SampleSet to the same BYTES.

That gap is real and cheap to close. B1's assertions all go through
`json.load`, so a site that grew an `indent=`, a `sort_keys=` or a
different separator would still satisfy every one of them while changing
what actually crosses the process boundary.

Failure class guarded (design §8): **round-trip / key-coercion drift**,
in its cross-site form — the two boundaries diverging from each other.

Why B3 adds this test and NOT a shared helper
---------------------------------------------
The design leaves B3's shape open and warns against creating an
abstraction "merely to satisfy prose about centralization". The audit at
`sandbox_executor.py:1301-1308` (train) and `:1635-1640` (eval) found both
sites are already five lines of `validate -> path -> dump -> flag`, and
that they differ in exactly one respect that must NOT be unified: the eval
site wraps its validation in a `try/except ScopeViolationError` returning a
structured error dict, while the train site lets its outer handler convert
the failure (§13.4). A helper would have to leave that difference outside
itself, so it would remove three lines and add one indirection.

The contract is therefore enforced by an observable test rather than by a
new seam — which is what "freeze observable properties, not helper shape"
asks for.
"""

import json

import pytest

from core.sandbox_executor import TidmadSandbox
from tests.unit.execute_tools.test_step02b_b1_sampleset_roundtrip import (
    DIVERGENT_SS,
    RUN_NAME,
    _sample_set_json_path,
)


@pytest.fixture
def sandbox(tmp_path):
    return TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path))


class TestBothSitesEmitIdenticalBytes:
    def test_train_and_eval_serialize_to_byte_identical_json(self, sandbox):
        """One SampleSet, two boundaries, one byte string.

        Reads the raw file contents, not the parsed object: parsing is
        exactly what would hide a formatting divergence.
        """
        train_path = _sample_set_json_path(sandbox, "train", DIVERGENT_SS)
        eval_path = _sample_set_json_path(sandbox, "eval", DIVERGENT_SS)

        with open(train_path, "rb") as f:
            train_bytes = f.read()
        with open(eval_path, "rb") as f:
            eval_bytes = f.read()

        assert train_bytes == eval_bytes, (
            "the train and eval serialization sites no longer emit identical "
            f"bytes for the same SampleSet:\n  train: {train_bytes!r}\n"
            f"  eval:  {eval_bytes!r}"
        )

    def test_emitted_bytes_are_the_compact_default_form(self, sandbox):
        """Pins the TIDMAD wire format itself, not merely site agreement.

        Both sites could drift TOGETHER — a single edit adding `indent=4`
        to a shared pattern would keep them equal while changing every
        config file the subprocess reads. This asserts the actual bytes.
        """
        path = _sample_set_json_path(sandbox, "train", DIVERGENT_SS)
        with open(path) as f:
            written = f.read()

        expected = json.dumps({str(k): v for k, v in DIVERGENT_SS.items()})
        assert written == expected, (
            f"SampleSet wire format changed:\n  written:  {written!r}\n  expected: {expected!r}"
        )
