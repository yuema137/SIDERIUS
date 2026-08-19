"""
DataScope-aware HealthGate config surface (DS4).

Covers:
  * apply_monitored_files — one shared run-level list applied uniformly to
    ALL six file-accessing checks (blocking + recording-only); pure.
  * validate_health_scope — every check validated; a check without an
    explicit peek_file_indices counts as full-dataset access (violation
    under a partial scope). No intersection, no fallback.
  * materialize_effective_config — atomic write, body-sha reuse, mismatch
    diagnostics (operator inputs vs source drift).
  * Attempted-open sets: under health_gate_files=[4,7,9], none of the six
    checks may request a path for any file outside {4,7,9}.

See docs/design/enable_partial_file_list.md (Commit DS4).
"""

from __future__ import annotations

import pytest

from execute_tools.health_checks._composition import (
    VALUE_SCALE_PARAMETER,
    VALUE_SCALE_UNIT_PARAMETER,
)
from execute_tools.health_checks.amplitude_collapse import AmplitudeCollapseCheck
from execute_tools.health_checks.config import (
    EFFECTIVE_CONFIG_BASENAME,
    apply_monitored_files,
    clear_health_gates_config_cache,
    load_health_gates_config,
    materialize_effective_config,
    validate_health_scope,
)
from execute_tools.health_checks.output_diversity import OutputDiversityCheck
from execute_tools.health_checks.output_std import OutputStdCheck
from execute_tools.health_checks.pearson_dispersion import PearsonDispersionCheck
from execute_tools.health_checks.per_file_output_std import PerFileOutputStdCheck
from execute_tools.health_checks.schemas import HealthCheckContext
from execute_tools.health_checks.spectral_peak_ratio import SpectralPeakRatioCheck

REPO_DEFAULT_YAML = "configs/health_checks.yaml"
SCOPE_4_9 = [4, 5, 6, 7, 8, 9]
FULL_SCOPE = list(range(20))
MONITORED = [4, 7, 9]

ALL_GATE_IDS = {
    "output_diversity_blocking",
    "output_std_blocking",
    "amplitude_collapse_blocking",
    "pearson_dispersion_recording",
    "spectral_peak_ratio_recording",
    "per_file_output_std_recording",
}


_TIDMAD_VALUE_SCALE: dict[str, object] = {
    VALUE_SCALE_PARAMETER: 40.0 / 128.0,
    VALUE_SCALE_UNIT_PARAMETER: "mV",
}
"""What composition injects for TIDMAD (Step 08b C5).

Supplied explicitly because these tests invoke checks DIRECTLY, bypassing
composition. A check that scales samples now refuses to guess a physical
scale rather than falling back to a literal of its own."""


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_health_gates_config_cache()
    yield
    clear_health_gates_config_cache()


def _repo_config():
    return load_health_gates_config(REPO_DEFAULT_YAML)


# ---------------------------------------------------------------------------
# apply_monitored_files
# ---------------------------------------------------------------------------


class TestApplyMonitoredFiles:
    def test_all_six_checks_receive_the_list(self):
        cfg = apply_monitored_files(_repo_config(), MONITORED)
        assert {g.id for g in cfg.health_gates} == ALL_GATE_IDS
        for gate in cfg.health_gates:
            for check in gate.checks:
                assert check.config["peek_file_indices"] == MONITORED, (
                    f"{gate.id}/{check.name} missing shared monitored list"
                )

    def test_normalizes_sorted_deduped(self):
        cfg = apply_monitored_files(_repo_config(), [9, 4, 4, 7])
        for gate in cfg.health_gates:
            for check in gate.checks:
                assert check.config["peek_file_indices"] == [4, 7, 9]

    def test_pure_original_config_unmodified(self):
        original = _repo_config()
        snapshot = original.model_dump()
        apply_monitored_files(original, MONITORED)
        assert original.model_dump() == snapshot

    def test_pure_default_cache_unmodified(self):
        # Load through the DEFAULT path (cached), transform, reload — the
        # cached object must be untouched.
        cached = load_health_gates_config()
        apply_monitored_files(cached, MONITORED)
        again = load_health_gates_config()
        assert again is cached
        for gate in again.health_gates:
            for check in gate.checks:
                if gate.id.endswith("_recording"):
                    assert "peek_file_indices" not in check.config

    def test_empty_files_rejected(self):
        with pytest.raises(ValueError, match="must be non-empty"):
            apply_monitored_files(_repo_config(), [])


# ---------------------------------------------------------------------------
# validate_health_scope
# ---------------------------------------------------------------------------


class TestValidateHealthScope:
    def test_default_yaml_passes_full_scope(self):
        validate_health_scope(_repo_config(), FULL_SCOPE)

    def test_default_yaml_fails_partial_scope_naming_all_six_gates(self):
        with pytest.raises(ValueError) as exc_info:
            validate_health_scope(_repo_config(), SCOPE_4_9)
        msg = str(exc_info.value)
        for gate_id in ALL_GATE_IDS:
            assert gate_id in msg, f"{gate_id} not named in the violation message"
        # Blocking gates: explicit [3,10,17] outside; recording: missing key.
        assert "outside the DataScope" in msg
        assert "defaults to full-dataset access" in msg
        assert "--health_gate_files" in msg

    def test_override_within_scope_passes(self):
        cfg = apply_monitored_files(_repo_config(), MONITORED)
        validate_health_scope(cfg, SCOPE_4_9)

    def test_override_outside_scope_fails(self):
        cfg = apply_monitored_files(_repo_config(), [3, 7, 10])
        with pytest.raises(ValueError, match=r"\[3, 10\] outside the DataScope"):
            validate_health_scope(cfg, SCOPE_4_9)


# ---------------------------------------------------------------------------
# materialize_effective_config
# ---------------------------------------------------------------------------


class TestMaterializeEffectiveConfig:
    def test_written_file_loads_with_override_everywhere(self, tmp_path):
        path, sha = materialize_effective_config(
            REPO_DEFAULT_YAML, MONITORED, str(tmp_path), resolved_scope=SCOPE_4_9
        )
        assert path.endswith(EFFECTIVE_CONFIG_BASENAME)
        loaded = load_health_gates_config(path)
        for gate in loaded.health_gates:
            for check in gate.checks:
                assert check.config["peek_file_indices"] == MONITORED
        assert len(sha) == 64

    def test_files_none_materializes_source_unchanged(self, tmp_path):
        """The ROSTER survives materialization untouched.

        Compared gate-by-gate rather than model-to-model since Step 08b C5:
        the materialized artifact deliberately carries no `health_policy`
        (composition already consumed it and baked the result into each
        gate), so the two models differ in a field whose absence is the
        point.
        """
        path, _sha = materialize_effective_config(REPO_DEFAULT_YAML, None, str(tmp_path))
        loaded = load_health_gates_config(path)
        assert loaded.health_gates == _repo_config().health_gates

    def test_reuse_on_identical_inputs(self, tmp_path):
        path1, sha1 = materialize_effective_config(REPO_DEFAULT_YAML, MONITORED, str(tmp_path))
        path2, sha2 = materialize_effective_config(REPO_DEFAULT_YAML, MONITORED, str(tmp_path))
        assert (path1, sha1) == (path2, sha2)

    def test_changed_operator_inputs_error(self, tmp_path):
        materialize_effective_config(REPO_DEFAULT_YAML, MONITORED, str(tmp_path))
        with pytest.raises(ValueError, match="operator inputs changed"):
            materialize_effective_config(REPO_DEFAULT_YAML, [5, 8], str(tmp_path))

    def test_source_drift_error(self, tmp_path):
        # Copy the repo YAML to a mutable location, materialize, then edit
        # the source — re-materialization must diagnose drift.
        src = tmp_path / "source.yaml"
        src.write_text(open(REPO_DEFAULT_YAML).read())
        ws = tmp_path / "ws"
        materialize_effective_config(str(src), MONITORED, str(ws))
        # Drift a value the framework file actually owns. Since C5 the
        # thresholds live in the task config, and policy is what this file
        # carries — flipping a blocking gate's on_fail is exactly the kind
        # of silent change workspace-immutability exists to catch.
        src.write_text(src.read_text().replace("on_fail: invalidate_round", "on_fail: continue"))
        with pytest.raises(ValueError, match="source YAML content drifted"):
            materialize_effective_config(str(src), MONITORED, str(ws))

    def test_scope_validation_inside_materialize(self, tmp_path):
        with pytest.raises(ValueError, match="violate the DataScope"):
            materialize_effective_config(
                REPO_DEFAULT_YAML, None, str(tmp_path), resolved_scope=SCOPE_4_9
            )
        assert not (tmp_path / EFFECTIVE_CONFIG_BASENAME).exists()


# ---------------------------------------------------------------------------
# Attempted-open sets — all six checks, monitored files only
# ---------------------------------------------------------------------------


class _RecordingCtx:
    """Wraps a HealthCheckContext whose path fns record every requested
    file index. Paths point at nonexistent files, so any actual open
    attempt shows up as an I/O failure inside the check (tolerated) —
    what we assert is the REQUESTED index set."""

    def __init__(self, tmp_path, denoised_paths: dict[int, str] | None = None):
        self.requested: set[int] = set()

        def _denoised(i: int) -> str:
            self.requested.add(i)
            return str(tmp_path / f"denoised_{i:04d}.h5")

        def _target(i: int) -> str:
            self.requested.add(i)
            return str(tmp_path / f"target_{i:04d}.h5")

        self.ctx = HealthCheckContext(
            model_name="m",
            run_name="r",
            round_index=1,
            denoised_paths=denoised_paths or {},
            denoised_filename_fn=_denoised,
            target_path_fn=_target,
        )


ALL_CHECKS = [
    OutputDiversityCheck(),
    OutputStdCheck(),
    AmplitudeCollapseCheck(),
    PearsonDispersionCheck(),
    SpectralPeakRatioCheck(),
    PerFileOutputStdCheck(),
]


class TestAttemptedOpenSets:
    @pytest.mark.parametrize("check", ALL_CHECKS, ids=lambda c: c.name)
    def test_monitored_files_bound_the_attempted_set(self, check, tmp_path):
        rec = _RecordingCtx(tmp_path)
        check.run(rec.ctx, {**_TIDMAD_VALUE_SCALE, "peek_file_indices": MONITORED})
        assert rec.requested, f"{check.name} requested no paths at all"
        assert rec.requested <= set(MONITORED), (
            f"{check.name} requested out-of-monitored files: "
            f"{sorted(rec.requested - set(MONITORED))}"
        )

    @pytest.mark.parametrize(
        "check",
        [PearsonDispersionCheck(), SpectralPeakRatioCheck(), PerFileOutputStdCheck()],
        ids=lambda c: c.name,
    )
    def test_recording_checks_without_config_keep_full_fallback(self, check, tmp_path):
        """Full-scope behavioral identity: no configured list → the
        pre-DS4 range(20) fallback via denoised_filename_fn."""
        rec = _RecordingCtx(tmp_path)
        check.run(rec.ctx, {**_TIDMAD_VALUE_SCALE})
        assert rec.requested == set(range(20))

    def test_recording_check_prefers_denoised_paths_over_fallback(self, tmp_path):
        """Priority order (2): explicit ctx.denoised_paths beats range(20)."""
        check = PerFileOutputStdCheck()
        ctx = HealthCheckContext(
            model_name="m",
            run_name="r",
            round_index=1,
            denoised_paths={5: str(tmp_path / "d5.h5"), 8: str(tmp_path / "d8.h5")},
        )
        result = check.run(ctx, {**_TIDMAD_VALUE_SCALE})
        assert result.metrics["n_files_attempted"] == 2

    # -- Step 02c C1 / §9 row C2 -------------------------------------------
    #
    # Tier ORDER, captured before PR 02c changes the tier-3 VALUE from the
    # hardcoded ``range(20)`` to the profile-derived index space. The
    # existing tests above cover tier-1-over-tier-3 (via
    # ``denoised_filename_fn``) and tier-2-over-tier-3 for ONE module.
    # Nothing pinned tier-1-over-tier-2 for any module, so a migration that
    # accidentally demoted the configured list below ``ctx.denoised_paths``
    # would have gone unnoticed on all three.

    @pytest.mark.parametrize(
        "check",
        [PearsonDispersionCheck(), SpectralPeakRatioCheck(), PerFileOutputStdCheck()],
        ids=lambda c: c.name,
    )
    def test_recording_checks_prefer_configured_list_over_denoised_paths(self, check, tmp_path):
        """Priority order (1) beats (2): the configured monitored list wins
        even when ``ctx.denoised_paths`` is populated with a DIFFERENT set.

        The two candidate populations are deliberately disjoint — ``{4,7,9}``
        configured against ``{5,8}`` present — so the requested set names
        which tier actually won. Under the correct order every requested
        index resolves through ``denoised_filename_fn`` (none of ``4,7,9``
        is in ``denoised_paths``) and the recorded set is exactly the
        configured list.
        """
        populated = {5: str(tmp_path / "d5.h5"), 8: str(tmp_path / "d8.h5")}
        assert not set(populated) & set(MONITORED), "the two tiers must stay disjoint"
        rec = _RecordingCtx(tmp_path, denoised_paths=populated)
        check.run(rec.ctx, {**_TIDMAD_VALUE_SCALE, "peek_file_indices": MONITORED})
        assert rec.requested == set(MONITORED), (
            f"{check.name} resolved {sorted(rec.requested)} — the configured "
            f"peek_file_indices {MONITORED} must outrank ctx.denoised_paths "
            f"{sorted(populated)}"
        )
