"""Step 02c C3 — the recording checks' all-files tier is DERIVED topology.

Design: ``docs/design/generic_framework_upgrade/step_02_dataset_sample_topology/
pr_02c_systematic_groups.md`` §2.3, §11.3, §11.4.

``range(20)`` was never a group. Its only meaning is "every file", and
that already has an authority — ``DatasetProfile.dataset.num_files``. So
it is DERIVED, and 02c must not turn it into a declared ``all_files``
field, which would create a second topology authority beside the one
Step 02a owns.

Why this file exists at all: under TIDMAD the derived population and the
literal ``range(20)`` are the same twenty numbers, so
``test_health_scope.py``'s full-fallback oracle — which stays the TIDMAD
compatibility pin and is deliberately NOT duplicated here — cannot tell
"derives from the profile" from "still assumes 20". Only a bound profile
with a different ``num_files`` separates them.

Scope discipline: this varies ONLY ``num_files``, and only to prove
derivation. It is not the Stage-B 4.8-C contrast, which varies the two
DECLARATIONS and is where all-files is explicitly *not* an axis.
"""

from __future__ import annotations

import pytest

from execute_tools.dataset_config import (
    TIDMAD_PROFILE,
    bind_dataset_profile,
    tidmad_topology,
)
from execute_tools.health_checks._composition import (
    VALUE_SCALE_PARAMETER,
    VALUE_SCALE_UNIT_PARAMETER,
)
from execute_tools.health_checks.pearson_dispersion import PearsonDispersionCheck
from execute_tools.health_checks.per_file_output_std import PerFileOutputStdCheck
from execute_tools.health_checks.schemas import HealthCheckContext
from execute_tools.health_checks.spectral_peak_ratio import SpectralPeakRatioCheck

RECORDING_CHECKS = [
    PearsonDispersionCheck(),
    SpectralPeakRatioCheck(),
    PerFileOutputStdCheck(),
]


_TIDMAD_VALUE_SCALE: dict[str, object] = {
    VALUE_SCALE_PARAMETER: 40.0 / 128.0,
    VALUE_SCALE_UNIT_PARAMETER: "mV",
}
"""What composition injects for TIDMAD (Step 08b C5).

Supplied explicitly because these tests invoke checks DIRECTLY, bypassing
composition. A check that scales samples now refuses to guess a physical
scale rather than falling back to a literal of its own."""


class _RecordingCtx:
    """Records every file index a check asks for a path to.

    Paths point at nonexistent files; the resulting I/O failures are
    irrelevant here — the requested INDEX SET is the observable.
    """

    def __init__(self, tmp_path):
        self.requested: set[int] = set()

        def _path(prefix: str):
            def _fn(i: int) -> str:
                self.requested.add(i)
                return str(tmp_path / f"{prefix}_{i:04d}.h5")

            return _fn

        self.ctx = HealthCheckContext(
            model_name="m",
            run_name="r",
            round_index=1,
            denoised_filename_fn=_path("denoised"),
            target_path_fn=_path("target"),
        )


class TestAllFilesTracksTheDeclaredTopology:
    @pytest.mark.parametrize("check", RECORDING_CHECKS, ids=lambda c: c.name)
    @pytest.mark.parametrize("num_files", [7, 32], ids=["fewer", "more"])
    def test_fallback_population_follows_num_files(self, check, num_files, tmp_path):
        """Both directions. ``7`` would still pass if the code silently
        clamped to a hardcoded 20 via a min(); ``32`` catches the plain
        surviving literal. One of the two alone proves less than it looks.
        """
        profile = TIDMAD_PROFILE.model_copy(
            update={
                "dataset": tidmad_topology(TIDMAD_PROFILE).dataset.model_copy(
                    update={"num_files": num_files}
                ),
                # The declared sets must be legal for the topology this
                # profile declares — `model_copy` does not revalidate, and
                # an incoherent fixture would only surface on a round-trip.
                "anchor_selection_files": [0],
                "health_peek_files": [1],
            }
        )
        rec = _RecordingCtx(tmp_path)
        with bind_dataset_profile(profile):
            check.run(rec.ctx, {**_TIDMAD_VALUE_SCALE})
        assert rec.requested == set(range(num_files)), (
            f"{check.name} evaluated {sorted(rec.requested)} — the all-files "
            f"tier must derive from the bound profile's num_files={num_files}, "
            f"not from a hardcoded topology"
        )

    def test_all_files_is_not_a_declared_field(self):
        """§2.3 / §12.2 stop condition, asserted mechanically.

        "Every file" must keep deriving from ``num_files``. A declared
        list would be a SECOND authority for the same fact, and the two
        could disagree — which is the failure mode the Dataset Profile
        exists to prevent.
        """
        declared = set(TIDMAD_PROFILE.to_wire())
        assert "all_files" not in declared
        for name in declared:
            assert "all_file" not in name, (
                f"DatasetProfile declares {name!r} — 'every file' derives from "
                f"dataset.num_files and must never be restated as a field"
            )
