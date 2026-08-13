"""PR-02c child CHECKPOINT C — the REAL consumers read the declarations.

Design: ``docs/design/generic_framework_upgrade/step_02_dataset_sample_topology/
pr_02c_systematic_groups.md`` §12.1.

> A test that constructs a declaration and calls a resolver directly does
> NOT satisfy this checkpoint.

So nothing here calls ``_resolve_indices`` or ``_resolve_files``. Every
assertion goes through a real production entry point:

    HealthGate     execute_tools.health_checks.runner.evaluate_gate
                   — what the tuner calls at a round boundary. It loads
                     the SHIPPED configs/health_checks.yaml, dispatches
                     real check skills from the registry, and those skills
                     really open HDF5 files.

    campaign       core.campaign_artifacts.decide_phase1_reuse
                   — the campaign-tooling entry point whose verdict
                     becomes action="train" vs "reuse".

    selection      execute_tools.sample_set_builder.build_sample_set
                   — the anchors branch as the tuner reaches it.

Real files are written and really read; the observable is the set of
paths the checks actually opened, captured at the path-resolution
boundary the checks go through.

Topology is held at TIDMAD throughout and only the DECLARATIONS vary
(§12.1). That is deliberate: a non-TIDMAD topology would drag in the
Step-08/Step-10 residue this PR does not own, and would contaminate the
question being asked here.

No real LLM is involved, and no scientific-quality result is claimed.
"""

from __future__ import annotations

import h5py
import numpy as np
import pytest

from core.campaign_artifacts import decide_phase1_reuse, sha256_file
from execute_tools.dataset_config import TIDMAD_PROFILE, bind_dataset_profile
from execute_tools.health_checks.config import clear_health_gates_config_cache
from execute_tools.health_checks.runner import evaluate_gate
from execute_tools.health_checks.schemas import GateAction, HealthCheckContext
from execute_tools.sample_set_builder import build_sample_set

SHIPPED_CONFIG = "configs/health_checks.yaml"
BLOCKING_GATE = "output_diversity_blocking"
RECORDING_GATE = "per_file_output_std_recording"

DECLARED_PEEK = [6, 13]
DECLARED_ANCHORS = [2, 7, 11, 15, 18]
N_SAMPLES = 4096


@pytest.fixture(autouse=True)
def _isolated_cache():
    clear_health_gates_config_cache()
    yield
    clear_health_gates_config_cache()


def _contrast_profile():
    """TIDMAD topology, both declarations replaced."""
    return TIDMAD_PROFILE.model_copy(
        update={
            "anchor_selection_files": DECLARED_ANCHORS,
            "health_peek_files": DECLARED_PEEK,
        }
    )


def _write_file(path, degenerate: bool) -> None:
    """A real TIDMAD-shaped denoised HDF5.

    Healthy files carry 251 distinct int8 values, comfortably over the
    shipped ``min_unique_int8_values: 25``. Degenerate files carry one.
    """
    payload = (
        np.zeros(N_SAMPLES, dtype=np.int8)
        if degenerate
        else (np.arange(N_SAMPLES, dtype=np.int64) % 251 - 125).astype(np.int8)
    )
    with h5py.File(path, "w") as handle:
        group = handle.create_group("timeseries")
        for channel in ("channel0001", "channel0002"):
            group.create_group(channel).create_dataset("timeseries", data=payload)


class _RealFiles:
    """Twenty real files plus a context that records what was opened."""

    def __init__(self, tmp_path, degenerate: set[int] | None = None):
        degenerate = degenerate or set()
        self.opened: set[int] = set()
        self._paths = {}
        for index in range(TIDMAD_PROFILE.dataset.num_files):
            path = tmp_path / f"denoised_{index:04d}.h5"
            _write_file(path, degenerate=index in degenerate)
            self._paths[index] = str(path)

        def _resolve(index: int) -> str:
            self.opened.add(index)
            return self._paths[index]

        self.ctx = HealthCheckContext(
            model_name="wavenet",
            run_name="step02c_checkpoint_c",
            round_index=1,
            denoised_filename_fn=_resolve,
            target_path_fn=_resolve,
        )


# ---------------------------------------------------------------------------
# 1. A real HealthGate evaluation resolves monitored files from declaration B
# ---------------------------------------------------------------------------


class TestRealHealthGateEvaluation:
    def test_the_blocking_gate_opens_exactly_the_declared_files(self, tmp_path):
        files = _RealFiles(tmp_path)
        with bind_dataset_profile(_contrast_profile()):
            result = evaluate_gate(BLOCKING_GATE, files.ctx, config_path=SHIPPED_CONFIG)

        assert files.opened == set(DECLARED_PEEK), (
            f"the blocking gate actually opened {sorted(files.opened)}; the "
            f"declared health-peek set is {DECLARED_PEEK}. This is the files "
            f"the gate JUDGED, not a resolver's return value"
        )
        assert result.passed is True
        assert result.action is GateAction.CONTINUE

    def test_the_recording_gate_still_evaluates_every_file(self, tmp_path):
        """The §8.1 leak guard at the real evaluation boundary.

        The recording gates ship no ``peek_file_indices``; their
        population derives from the profile's topology. If declaration B
        had leaked into the keyless path this would open two files, not
        twenty — and every one of the recording gate's own tests would
        still pass, because two files is perfectly self-consistent.
        """
        files = _RealFiles(tmp_path)
        with bind_dataset_profile(_contrast_profile()):
            evaluate_gate(RECORDING_GATE, files.ctx, config_path=SHIPPED_CONFIG)

        assert files.opened == set(range(TIDMAD_PROFILE.dataset.num_files))


class TestGateVerdictSemanticsAreUnchanged:
    """Thresholds and verdicts are Step-08's; 02c must not have moved them.

    Both directions are asserted, because a gate that always passed would
    satisfy the healthy case alone.
    """

    def test_a_degenerate_declared_file_still_fails_and_invalidates(self, tmp_path):
        files = _RealFiles(tmp_path, degenerate=set(DECLARED_PEEK))
        with bind_dataset_profile(_contrast_profile()):
            result = evaluate_gate(BLOCKING_GATE, files.ctx, config_path=SHIPPED_CONFIG)

        assert result.passed is False
        assert result.action is GateAction.INVALIDATE_ROUND, (
            "the shipped on_fail action changed — HealthGate routing policy "
            "is Step-08's and must be untouched by 02c"
        )

    def test_a_degenerate_file_OUTSIDE_the_declaration_does_not_flip_the_verdict(self, tmp_path):
        """The declaration decides WHAT IS JUDGED, not merely what is read.

        File 3 is TIDMAD's first declared peek file. Under a task that
        declares [6, 13] it must be irrelevant — if the verdict moved, a
        stale authority is still choosing the judged population.
        """
        files = _RealFiles(tmp_path, degenerate={3})
        with bind_dataset_profile(_contrast_profile()):
            result = evaluate_gate(BLOCKING_GATE, files.ctx, config_path=SHIPPED_CONFIG)

        assert result.passed is True
        assert 3 not in files.opened


# ---------------------------------------------------------------------------
# 2. The campaign validator consumes the same declared semantic
# ---------------------------------------------------------------------------


class TestRealCampaignDecision:
    """Through ``decide_phase1_reuse`` — the entry point whose output is an
    action, so this exercises the branch as POLICY rather than as a string."""

    @staticmethod
    def _record(tmp_path, files_requested: list[int], per_file: dict) -> dict:
        checkpoint = tmp_path / "checkpoint.pth"
        checkpoint.write_bytes(b"checkpoint")
        return {
            "campaign_run_name": "step02c_checkpoint_c",
            "model_type": "wavenet",
            "status": "success",
            "params": {"train_config": {"epochs": 1}},
            "training_files": ["/data/t.h5"],
            "checkpoint_path": str(checkpoint),
            # Required, or `validate_phase1_baseline` reports a checkpoint
            # hash mismatch and BOTH cases below return "train" — the
            # retrain case would then pass without the peek branch having
            # decided anything.
            "checkpoint_sha256": sha256_file(str(checkpoint)),
            "denoising_score": -2.5,
            "file_vector": [1.0] * 20,
            "health_gate_results": [
                {
                    "gate_name": BLOCKING_GATE,
                    "execution_status": "passed",
                    "resolved_action": "continue",
                    "aggregation": {"files_requested": files_requested},
                    "metrics": {"aggregate_statistics": {"count": 2}, "per_file": per_file},
                }
            ],
        }

    def _decide(self, record, outputs):
        return decide_phase1_reuse(
            record,
            campaign_name="step02c_checkpoint_c",
            model_type="wavenet",
            expected_params={"train_config": {"epochs": 1}},
            expected_training_files=["/data/t.h5"],
            configured_gate_ids=[BLOCKING_GATE],
            expected_output_paths=outputs,
        )

    def test_an_incomplete_declared_peek_forces_a_retrain(self, tmp_path):
        output = tmp_path / "out.h5"
        output.write_bytes(b"h5")
        record = self._record(
            tmp_path,
            files_requested=list(DECLARED_PEEK),
            per_file={"6": {"execution_status": "passed"}},  # 13 missing
        )
        with bind_dataset_profile(_contrast_profile()):
            decision = self._decide(record, [str(output)])
        assert decision.action == "train"
        assert any("missing per-file entries" in e for e in decision.validation.errors)

    def test_tidmad_s_triplet_is_no_longer_the_trigger(self, tmp_path):
        """Same incomplete shape, but requesting TIDMAD's files under a task
        that declares something else: not this task's business, so it is
        skipped and the record is reusable."""
        output = tmp_path / "out.h5"
        output.write_bytes(b"h5")
        record = self._record(tmp_path, files_requested=[3, 10, 17], per_file={})
        with bind_dataset_profile(_contrast_profile()):
            decision = self._decide(record, [str(output)])
        assert decision.action == "reuse"


# ---------------------------------------------------------------------------
# 3. The anchors selection path resolves from declaration A
# ---------------------------------------------------------------------------


class TestRealSelectionPath:
    def test_build_sample_set_anchors_follows_the_declaration(self):
        result = build_sample_set(
            is_trial=True,
            trial_strategy="anchors",
            trial_portion=0.05,
            seed=42,
            profile=_contrast_profile(),
        )
        assert sorted(result) == sorted(DECLARED_ANCHORS)

    def test_the_segment_index_space_is_untouched(self):
        """02b's selection semantics must not have drifted: the per-file
        segment count still comes from the profile's geometry and the
        portion, not from anything 02c introduced."""
        result = build_sample_set(
            is_trial=True,
            trial_strategy="anchors",
            trial_portion=0.05,
            seed=42,
            profile=_contrast_profile(),
        )
        expected = max(1, round(0.05 * TIDMAD_PROFILE.dataset.segments_per_file))
        assert {len(v) for v in result.values()} == {expected}


# ---------------------------------------------------------------------------
# 4. No migrated literal survives unnoticed
# ---------------------------------------------------------------------------


class TestNoMigratedLiteralSurvives:
    """Static sweep over the exact sites 02c migrated (§12.2).

    Greppable, because a literal that resurfaces in a later edit would be
    behaviourally invisible under TIDMAD — it would agree with the
    declaration on every shipped path.
    """

    @pytest.mark.parametrize(
        ("path", "forbidden"),
        [
            ("execute_tools/sample_set_builder.py", "ANCHOR_FILES"),
            ("execute_tools/sample_set_builder.py", "[0, 10, 19]"),
            ("core/campaign_artifacts.py", "[3, 10, 17]"),
            ("execute_tools/health_checks/pearson_dispersion.py", "_DEFAULT_FILE_RANGE"),
            ("execute_tools/health_checks/per_file_output_std.py", "_DEFAULT_FILE_RANGE"),
            ("execute_tools/health_checks/spectral_peak_ratio.py", "_DEFAULT_FILE_RANGE"),
            ("configs/health_checks.yaml", "peek_file_indices: [3, 10, 17]"),
            ("configs/health_checks_baseline_observe_mode.yaml", "peek_file_indices: [3, 10, 17]"),
        ],
    )
    def test_the_migrated_site_holds_no_literal(self, path, forbidden):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        source = (repo_root / path).read_text()
        code = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith(("#", "``"))
        )
        assert forbidden not in code, (
            f"{path} still contains {forbidden!r}. Under TIDMAD it would agree "
            f"with the declaration on every shipped path, so no behavioural "
            f"test would notice"
        )
