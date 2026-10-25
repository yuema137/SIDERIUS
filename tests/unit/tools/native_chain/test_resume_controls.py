"""Private shell controls cannot turn a direct launch into an adopted successor."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.native_writer.ownership import TRANSPORT_ENV
from tools.native_chain.models import NativeChainCaptureReference
from tools.native_chain.resume_admit import admit_resume


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "no_descriptor"])
def test_resume_controls_refuse_before_writer_adoption(monkeypatch, mutation):
    # Capture identity is owned/tested by load_capture; this fixture isolates
    # the extra resume authorization that valid capture bytes cannot grant.
    monkeypatch.setattr(
        "tools.native_chain.resume_admit.load_capture", lambda *a: SimpleNamespace()
    )
    monkeypatch.delenv(TRANSPORT_ENV, raising=False)
    monkeypatch.setattr(
        "tools.native_chain.resume_admit.inherit",
        lambda *a: pytest.fail("invalid controls reached writer"),
    )
    reference = NativeChainCaptureReference(
        path=Path("/capture.json"), sha256="a" * 64, input_max_bytes=4096
    )
    controls = (
        "--chain_resume_predecessor",
        str(uuid4()),
        "--chain_resume_successor",
        str(uuid4()),
        "--chain_resume_reservation_sha256",
        "b" * 64,
    )
    if mutation == "missing":
        controls = controls[:-2]
    elif mutation == "duplicate":
        controls = (*controls, *controls[:2])
    with pytest.raises(ValueError, match=r"resume_controls_changed|resume_writer_required"):
        admit_resume(reference, controls)
