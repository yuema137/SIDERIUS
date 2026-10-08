"""Step 05b Stage-B — rung `05b-B`, two atomic subcases.

Design:
``docs/design/generic_framework_upgrade/step_05b_tuner_resource_time.md``
§8 (ONE rung, TWO subcases), §10 (failure classes 4 and 5).

    05b-B   every task-shaped term used by resource/time planning derives
            from the authority that already owns it, while calibration and
            runtime values keep their owners and their values.

    B1      vary ONLY a contract-owned Model-I/O fact
    B2      vary ONLY a DatasetProfile decomposition fact

Two subcases and not one, because 05b migrates two independent authority
families that fail in opposite directions. A single contrast moving both
facts at once would still pass if either half were migrated and the other
happened to agree — the partial-derivation false green §8 names.

**What this module adds that the per-commit tests do not.** The observations
themselves live where the behaviour lives: B1's realization contrast in
`tests/unit/agent/evaluate_vram_skill/test_step05b_c2_contract_aware_probe.py`
and at production scale in `tests/integration/nodes/test_step05b_checkpoint_c.py`;
B2's in `tests/unit/execute_tools/test_step05b_c5_run_bound_profile.py`.
What is missing there is the *rung* property: that each contrast is
**single-axis**. A contrast that quietly moved a second fact would make every
one of those assertions pass while proving nothing about which authority the
term followed. So this module machine-checks the fixtures rather than
restating the observations.
"""

from __future__ import annotations

from execute_tools.dataset_config import (
    TIDMAD_PROFILE,
    tidmad_topology,
)
from tests.helpers.step04a_fixtures import tidmad_model_io


def _diff(left: dict, right: dict, path: str = "") -> list[str]:
    """Every leaf path at which two dumped models differ."""
    if isinstance(left, dict) and isinstance(right, dict):
        out: list[str] = []
        for key in sorted(set(left) | set(right)):
            out += _diff(left.get(key), right.get(key), f"{path}.{key}" if path else str(key))
        return out
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [f"{path}[len]"]
        out = []
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            out += _diff(a, b, f"{path}[{index}]")
        return out
    return [] if left == right else [path]


# ---------------------------------------------------------------------------
# B1 — Model-I/O / probe realization
# ---------------------------------------------------------------------------


class TestB1IsSingleAxis:
    def test_the_contrast_moves_exactly_the_class_extent(self):
        """The B1 fixture differs from its baseline at ONE leaf.

        If it also moved the dtype, the axis order, the rank or the input
        declaration, then "the probe followed the contract" would be true of
        a contract that changed in several ways at once, and the observation
        would not identify which fact the probe followed.
        """
        moved = _diff(
            tidmad_model_io(num_classes=256).model_dump(mode="json"),
            tidmad_model_io(num_classes=16).model_dump(mode="json"),
        )
        assert moved == ["output.axes[1].dimension.fixed"], moved

    def test_the_contrast_leaves_the_dataset_authority_untouched(self):
        """B1 holds the OTHER family fixed. A Model-I/O contrast that also
        perturbed the topology would be a two-axis contrast wearing a
        one-axis name."""
        assert tidmad_model_io(num_classes=16).class_cardinality == 16
        assert tidmad_topology(TIDMAD_PROFILE).dataset.psd_segment_length == 10_000_000
        assert tidmad_topology(TIDMAD_PROFILE).encoding.num_classes == 256


# ---------------------------------------------------------------------------
# B2 — dataset / decomposition topology
# ---------------------------------------------------------------------------


class TestB2IsSingleAxis:
    def test_the_contrast_moves_exactly_the_decomposition_length(self):
        contrast = TIDMAD_PROFILE.model_copy(
            update={
                "dataset": tidmad_topology(TIDMAD_PROFILE).dataset.model_copy(
                    update={"psd_segment_length": 2_048_000}
                )
            }
        )
        moved = _diff(TIDMAD_PROFILE.to_wire(), contrast.to_wire())
        assert moved == ["dataset.psd_segment_length"], moved

    def test_the_contrast_leaves_the_model_io_authority_untouched(self):
        """B2 holds Model-I/O fixed. Its contrast changes no cardinality, so
        a probe shape moving under B2 would mean the two families are
        entangled — which is the thing the two-subcase split exists to
        detect."""
        contrast = TIDMAD_PROFILE.model_copy(
            update={
                "dataset": tidmad_topology(TIDMAD_PROFILE).dataset.model_copy(
                    update={"psd_segment_length": 2_048_000}
                )
            }
        )
        assert (
            tidmad_topology(contrast).encoding.num_classes
            == tidmad_topology(TIDMAD_PROFILE).encoding.num_classes
        )
        assert tidmad_model_io().class_cardinality == 256


# ---------------------------------------------------------------------------
# The rung's shared claim: calibration is fixed across BOTH subcases
# ---------------------------------------------------------------------------


def test_no_calibration_value_participates_in_either_contrast():
    """§8: calibration, hardware and policy are provably fixed across both.

    Asserted against the calibration modules directly, because a contrast
    that moved one of these would produce a term change attributable to
    calibration rather than to an authority — and both subcases would still
    look green.
    """
    from agent.skills.evaluate_time_skill.trigger_policy import SEG_SIZE_BOUNDS
    from agent.skills.evaluate_vram_skill.batch_resolver import _DEFAULT_CANDIDATE_BATCHES
    from agent.skills.evaluate_vram_skill.compute_intensity import _MAX_BATCH_TIMESTEPS
    from agent.skills.inference_skill.estimator import _INFERENCE_VS_TRAINING_RATIO
    from core.sandbox_executor import _ROLE_DEFAULT_RSS_GB

    assert _INFERENCE_VS_TRAINING_RATIO == 2.7
    assert _MAX_BATCH_TIMESTEPS == 800_000
    assert _DEFAULT_CANDIDATE_BATCHES == (64, 32, 16, 8, 4, 2, 1)
    assert SEG_SIZE_BOUNDS == (2500, 40_000)
    # Native launches have no implicit address-space cap. An explicitly
    # selected execution policy owns limits; topology contrasts cannot add one.
    assert _ROLE_DEFAULT_RSS_GB == {"training": None, "inference": None, "scoring": None}
