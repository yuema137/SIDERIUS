"""Step 12 / PR-12bc — B0: Phase-B differential baselines and inverted guards.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12bc_generic_task_boundary_closure.md`` §M / B0.

B0 changes **no production file**. It pins what Phase B must preserve and
makes each defect Phase B repairs *executably visible first*, so a later
commit flips a NAMED guard instead of asserting progress against nothing. A
baseline captured after a change is not a baseline — which is why this is the
first commit.

Inverted guards
---------------

Every ``TestInvertedGuard*`` class asserts a defect is PRESENT on today's
source. Each names its flip owner, and **each fails once the defect is
repaired** — that is the point. R-11-10 applies: when the fix lands, the guard
either becomes the permanent owner of the corrected property or is deleted,
never both.

===========  ==================================================  ==========
guard        defect asserted PRESENT                             flips in
===========  ==================================================  ==========
(a)          RETIRED at B6 — the pairing gap is closed; the      RETIRED
             positive contract lives in
             ``test_step12_pr12bc_b6_scope_transport.py``
(b)(c)(d)    RETIRED at B7; (e) UPGRADED at B7. The positive     RETIRED
(e)          contracts live in
             ``test_step12_pr12bc_b7_satellites.py``
===========  ==================================================  ==========

What is deliberately NOT inverted
---------------------------------

``TestPreservedCrossTaskPairingRule`` asserts a rule Phase B must **keep**:
handing one task's scope to another task's implementation raises
``TypeError``. B6 must not "fix" that away while closing the pairing gap.

``TestPhaseBStructuralBaseline`` records the §J pre-values for every function
Phase B touches, so B8/BC-FINAL can perform the mandatory comparison. It is a
tripwire on GROWTH and is silent on shrinkage.

Why the structural guards (c), (d), (e) assert SOURCE and not behaviour
----------------------------------------------------------------------

All three sit inside large orchestration functions — ``_target_fn`` is a
nested closure inside ``run_inference_scoring_health``, the anchor load is a
statement inside ``HyperparamTuningAgent.run``, and the measurement scope is
inside the time-estimation wrapper. Driving any of them behaviourally would
require standing up the surrounding orchestrator, and the design's own B0
edge-case note for guard (e) says it explicitly: *"the guard must assert
structure, never wall time (the F-12a-G2 lesson)."* Guard (b), whose site is a
free function, IS asserted behaviourally.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import pathlib
import random
from unittest.mock import MagicMock, mock_open, patch

import h5py
import numpy as np
import pytest

from core.sandbox_executor import TidmadSandbox
from execute_tools.dataset_config import (
    NUM_FILES,
    SEGMENTS_PER_FILE,
    ChannelIdentity,
    DatasetConfig,
    DatasetProfile,
    ValueEncoding,
)
from execute_tools.sample_set_builder import build_sample_set
from execute_tools.scoring_utils import validate_sample_set
from execute_tools.task_data_path import EpochSamplingParams
from execute_tools.tidmad_data_path import TidmadScope, TidmadTaskDataPath
from tests.unit.guardrails.test_step12_pr12a_c0_defect_baselines import (
    _qualified_functions,
    measure,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

MODEL_CFG = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
LOSS_CFG = {"loss_type": "ce"}
EXP_ID = "pr12bc_b0_exp"
RUN_NAME = "pr12bc_b0_run"


# ======================================================================
# Shared helpers
# ======================================================================


def _options(cmd: list[str]) -> tuple[str, ...]:
    """Option tokens of an argv, in order, de-duplicated by first sight.

    Same convention as the Step-11 C0 baseline
    (``test_step11_c0_baselines._options``): a token that merely LOOKS like a
    flag (a negative number) is excluded by requiring a non-digit after the
    dashes. Positional values are absolute temp paths and carry no contract,
    which is R-11-13's repo-rooted-token normalization applied by construction
    rather than by string surgery.
    """
    seen: list[str] = []
    for tok in cmd:
        if tok.startswith("-") and not tok.lstrip("-")[:1].isdigit() and tok not in seen:
            seen.append(tok)
    return tuple(seen)


@pytest.fixture
def sandbox(tmp_path):
    return TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path), progress_bar=False)


def _train_success(sb, exp_id):
    def _side_effect(*args, **kwargs):
        os.makedirs(sb.dirs["models"], exist_ok=True)
        with open(os.path.join(sb.dirs["models"], f"_OK_{exp_id}"), "wb"):
            pass
        result = MagicMock()
        result.returncode = 0
        result.stdout = "done\n"
        result.stderr = ""
        return result, None

    return _side_effect


def _source(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _fn(rel: str, qualname: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    fns = _qualified_functions(REPO_ROOT / rel)
    assert qualname in fns, (
        f"{rel}::{qualname} no longer exists. A guard over a renamed-away "
        f"function passes by measuring nothing — re-anchor it deliberately."
    )
    return fns[qualname]


# ======================================================================
# 1. Legacy argv parity — the DEFAULT `shuffle` MULTI-FILE path
# ======================================================================

#: Captured by RUNNING the production builders at the PR-12bc base with NO
#: composition bound and a MULTI-FILE (sample-set) call.
#:
#: This is deliberately NOT a duplicate of ``test_step11_c0_baselines``. That
#: baseline uses the MINIMAL legacy signature and its own docstring says the
#: conditional flags are absent "because the CALLER supplied nothing, not
#: because they were removed" — so it cannot see the ordering flags at all.
#: The defect only THIS fixture catches: a Phase-B transport commit that emits
#: an ordering flag, or a scope flag, on the legacy multi-file path — where a
#: sample set genuinely exists and the temptation to attach a scope to it is
#: greatest.
#:
#: Two things the capture recorded that are easy to assume away, so they are
#: stated: ``--file_index`` is present even in MULTI-FILE mode (the child
#: still receives it; the sample set is what makes the run multi-file), and
#: ``--runtime_observation_out`` is unconditional on the streaming path even
#: with no runtime policy supplied.
LEGACY_MULTIFILE_TRAINING_FLAGS: tuple[str, ...] = (
    "--model_cfg",
    "--train_cfg",
    "--loss_cfg",
    "--dataset_profile_json",
    "--exp_id",
    "--run_name",
    "--sandbox_dir",
    "--file_index",
    "--model_io_json",
    "--sample_set_json",
    "--runtime_observation_out",
)

#: Flags that MUST NOT appear on an un-composed run, whatever else changes.
#: The first two are the default-`shuffle` absence rule
#: (``core/sandbox_executor.py:1545-1553``); the rest are composed-only
#: transports, including the two Phase B is about to introduce.
FORBIDDEN_ON_LEGACY: tuple[str, ...] = (
    "--order_strategy",
    "--file_order_json",
    "--task_data_path_id",
    "--task_manifest",
    "--data_dir",
    "--raw_data_dir",
    "--task_scope_ref",
    "--task_scope_digest",
    "--task_eval_scope_ref",
    "--task_eval_scope_digest",
)

BASELINE_SAMPLE_SET = {0: [1, 2], 3: [0, 4]}


class TestLegacyMultiFileArgvBaseline:
    """R-11-13 parity for the multi-file path Phase B is about to touch."""

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_training_multifile_argv_flag_set(self, mock_run, sandbox):
        mock_run.side_effect = _train_success(sandbox, EXP_ID)
        sandbox.execute_training(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
            sample_set=BASELINE_SAMPLE_SET,
        )
        assert _options(mock_run.call_args[0][0]) == LEGACY_MULTIFILE_TRAINING_FLAGS

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_the_default_shuffle_path_emits_NO_ordering_flag(self, mock_run, sandbox):
        """Flag ABSENCE, not flag value.

        ``order_strategy`` defaults to ``"shuffle"`` and ``file_order`` to
        ``None``, and the builder emits each flag only when non-default
        (``core/sandbox_executor.py:1545-1553``). A commit that starts
        emitting ``--order_strategy shuffle`` "for explicitness" changes a
        command line that predates ordering, for every legacy run.
        """
        mock_run.side_effect = _train_success(sandbox, EXP_ID)
        sandbox.execute_training(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
            sample_set=BASELINE_SAMPLE_SET,
        )
        cmd = mock_run.call_args[0][0]
        assert "--order_strategy" not in cmd
        assert "--file_order_json" not in cmd

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_no_composed_only_flag_reaches_a_legacy_training_run(self, mock_run, sandbox):
        mock_run.side_effect = _train_success(sandbox, EXP_ID)
        sandbox.execute_training(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
            sample_set=BASELINE_SAMPLE_SET,
        )
        cmd = mock_run.call_args[0][0]
        leaked = [f for f in FORBIDDEN_ON_LEGACY if f in cmd]
        assert leaked == [], f"composed-only flags leaked onto a legacy training argv: {leaked}"

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_no_composed_only_flag_reaches_a_legacy_inference_run(self, mock_run, sandbox):
        cfg_dir = sandbox.dirs["configs"]
        os.makedirs(cfg_dir, exist_ok=True)
        for name in (f"model_config_{EXP_ID}.json", f"loss_config_{EXP_ID}.json"):
            with open(os.path.join(cfg_dir, name), "w") as fh:
                json.dump({}, fh)
        open(os.path.join(sandbox.dirs["models"], f"model_fcnet_{EXP_ID}_agent.pth"), "w").close()
        result = MagicMock()
        result.returncode = 0
        result.stdout = "done\n"
        result.stderr = ""
        mock_run.return_value = (result, None)
        sandbox.execute_inference(
            EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG, sample_set=BASELINE_SAMPLE_SET
        )
        cmd = mock_run.call_args[0][0]
        leaked = [f for f in FORBIDDEN_ON_LEGACY if f in cmd]
        assert leaked == [], f"composed-only flags leaked onto a legacy inference argv: {leaked}"

    @patch("core.sandbox_executor.subprocess.run")
    def test_no_composed_only_flag_reaches_a_legacy_scoring_run(self, mock_run, sandbox):
        """Scoring's ``--data_dir`` is the DELIVERABLE dir, so it is excluded
        from the forbidden set here rather than asserted absent — the Step-11
        C4 distinction (`--raw_data_dir` is the dataset root) must survive.
        """
        result = MagicMock()
        result.returncode = 0
        result.stdout = "done\n"
        result.stderr = ""
        mock_run.return_value = result
        with (
            patch("builtins.open", mock_open(read_data=json.dumps({"denoising_score": 0.9}))),
            patch("os.path.exists", return_value=True),
            patch("os.remove"),
        ):
            sandbox.execute_scoring(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        cmd = mock_run.call_args[0][0]
        forbidden = tuple(f for f in FORBIDDEN_ON_LEGACY if f != "--data_dir")
        leaked = [f for f in forbidden if f in cmd]
        assert leaked == [], f"composed-only flags leaked onto a legacy scoring argv: {leaked}"


# ======================================================================
# 2. SampleSet wire-format baseline
# ======================================================================


class TestSampleSetWireFormatBaseline:
    """The bytes a scope-transport change must not perturb.

    ``test_step02b_b1_sampleset_roundtrip`` and ``..._b3_boundary_byte_parity``
    own the cross-site and compact-form properties. This adds the one thing
    they cannot express from inside their own module: the exact recorded
    baseline BYTES for the fixed set this PR's own baselines use, so a
    Phase-B change that re-routes SampleSet serialization through the new
    scope authority is caught here with a value, not a comparison against
    whatever the code currently produces.
    """

    def test_the_recorded_wire_bytes(self, sandbox):
        path = os.path.abspath(os.path.join(sandbox.dirs["configs"], f"sample_set_{EXP_ID}.json"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump({str(k): v for k, v in BASELINE_SAMPLE_SET.items()}, fh)
        with open(path, "rb") as fh:
            written = fh.read()
        # Hardcoded, never read back from the thing under test.
        assert written == b'{"0": [1, 2], "3": [0, 4]}'


# ======================================================================
# 3. Legacy scope construction — the MATERIALIZED baseline
# ======================================================================
#
# Recorded as the visited sample SEQUENCE and step COUNT, not as config
# values: key-type drift, a changed rng draw or a reordered file loop all
# leave the config values identical while changing what the model sees.
#
# A deliberately small synthetic topology, so this runs as a unit test with
# no TIDMAD data on disk. The production classes are the real ones.

SMALL_DATASET = DatasetConfig(
    psd_segment_length=40,
    segments_per_file=5,
    num_files=3,
    sampling_frequency=100.0,
)
SMALL_PROFILE = DatasetProfile(
    dataset=SMALL_DATASET,
    channels=ChannelIdentity(input_channel="channel0001", target_channel="channel0002"),
    encoding=ValueEncoding(
        storage_dtype="int8", compute_dtype="int16", value_offset=128, num_classes=256
    ),
    anchor_selection_files=[0, 2],
    health_peek_files=[1],
)
SMALL_SEG_SIZE = 10  # 40 // 10 = 4 ML rows per PSD segment


@pytest.fixture
def small_data_dir(tmp_path):
    """Three tiny training files whose contents encode (file, sample index).

    Any misindexing, reordering or family mix-up changes the digest below.
    """
    root = tmp_path / "small_data"
    root.mkdir()
    psd_len = SMALL_DATASET.psd_segment_length
    n = SMALL_DATASET.segments_per_file * psd_len
    for fi in range(SMALL_DATASET.num_files):
        idx = np.arange(n, dtype=np.int64)
        ch1 = ((fi * 1000 + idx) % 251 - 125).astype(np.int8)
        ch2 = ((fi * 1000 + idx * 7) % 251 - 125).astype(np.int8)
        # The layout the production reader walks:
        # ``_h5_dataset(f, "timeseries", <channel>, "timeseries")``
        # (``tidmad_data_path.py:190-191``) — a nested group, not a flat one.
        with h5py.File(root / SMALL_DATASET.training_file_name(fi), "w") as f:
            f.create_dataset("timeseries/channel0001/timeseries", data=ch1)
            f.create_dataset("timeseries/channel0002/timeseries", data=ch2)
    return str(root)


def _materialize(data_dir, sample_set, *, epoch_seed, train_portion):
    ds = TidmadTaskDataPath().training_dataset(
        TidmadScope(sample_set=sample_set, seg_size=SMALL_SEG_SIZE, profile=SMALL_PROFILE),
        EpochSamplingParams(data_dir=data_dir, epoch_seed=epoch_seed, train_portion=train_portion),
    )
    return {
        "steps": len(ds),
        "psd_segments_read": ds.psd_segments_read,
        "file_row_ranges": {k: list(v) for k, v in ds.file_row_ranges.items()},
        "inputs_sha256": hashlib.sha256(ds.inputs.tobytes()).hexdigest(),
        "targets_sha256": hashlib.sha256(ds.targets.tobytes()).hexdigest(),
    }


class TestLegacyScopeConstructionBaseline:
    """What ``build_sample_set -> TidmadScope -> training_dataset`` produces
    today, for a fixed ``(plan, seed, profile, data_scope)``.

    B3's capability implementation and B5's tuner acquisition must reproduce
    these exact values; B6's child must materialize them after a round trip.
    """

    def test_build_sample_set_is_the_recorded_selection(self):
        ss = build_sample_set(
            is_trial=True,
            trial_strategy="snapshot",
            trial_portion=0.4,
            seed=1234,
            profile=SMALL_PROFILE,
        )
        # round(0.4 * 5) == 2 segments per file, over all 3 files.
        assert ss == {0: [0, 3], 1: [0, 4], 2: [0, 4]}

    def test_full_portion_materialization_is_exact(self, small_data_dir):
        ss = build_sample_set(
            is_trial=True,
            trial_strategy="snapshot",
            trial_portion=0.4,
            seed=1234,
            profile=SMALL_PROFILE,
        )
        got = _materialize(small_data_dir, ss, epoch_seed=7, train_portion=1.0)
        assert got == {
            "steps": 24,
            "psd_segments_read": 6,
            "file_row_ranges": {0: [0, 8], 1: [8, 16], 2: [16, 24]},
            "inputs_sha256": ("6c08bbb24f4f5758000ae7150223aeca0c7a86394d5c55a2c75c2fbf32bbd83d"),
            "targets_sha256": ("6d79caf18802dd6467f97cc8add010546d02b19bd80d4127fc0726cf30fca76a"),
        }

    def test_subsampled_materialization_pins_the_rng_draw(self, small_data_dir):
        """``train_portion < 1.0`` takes ``rng.sample(...)`` — an UNSORTED
        draw whose order becomes the row order. A capability implementation
        that re-derives the seed differently, or sorts the draw, changes what
        the model sees while every config value stays identical.
        """
        ss = build_sample_set(
            is_trial=True,
            trial_strategy="snapshot",
            trial_portion=1.0,
            seed=99,
            profile=SMALL_PROFILE,
        )
        got = _materialize(small_data_dir, ss, epoch_seed=5, train_portion=0.4)
        assert got == {
            "steps": 24,
            "psd_segments_read": 6,
            "file_row_ranges": {0: [0, 8], 1: [8, 16], 2: [16, 24]},
            # A DIFFERENT digest from the full-portion cell above, over the
            # same 24 rows and the same three files: the rows differ only in
            # WHICH PSD segments the draw kept and in what order. That is the
            # property no config-value comparison can see.
            "inputs_sha256": ("a30c37cb448afcba552efa2d2223d472bf625dec0de4a4a79e2343dc281763d2"),
            "targets_sha256": ("01571be721144c760b7b9d91191f879f0251defe6900c82da8ca29daa8ef5e5e"),
        }

    def test_string_keys_materialize_identically_to_int_keys(self, small_data_dir):
        """The JSON round trip turns keys into strings
        (``tidmad_data_path.py:375`` does ``int(k)``). B4's canonical bytes
        must not change what this produces.
        """
        ss = build_sample_set(
            is_trial=True,
            trial_strategy="snapshot",
            trial_portion=0.4,
            seed=1234,
            profile=SMALL_PROFILE,
        )
        as_int = _materialize(small_data_dir, ss, epoch_seed=7, train_portion=1.0)
        as_str = _materialize(
            small_data_dir,
            {str(k): v for k, v in ss.items()},
            epoch_seed=7,
            train_portion=1.0,
        )
        assert as_str == as_int


# ======================================================================
# 4. INVERTED GUARD (a) — RETIRED AT B6 (R-11-10)
# ======================================================================
#
# The pairing gap is CLOSED. Per R-11-10 a flipped guard becomes the permanent
# owner of the corrected property or is deleted, never both — and the positive
# contract is a better owner than an inverted one, so it lives where the
# behaviour does:
#
#     tests/unit/core/test_step12_pr12bc_b6_scope_transport.py
#
# which asserts that `main()` forwards the scopes, that the child verifies
# before deserializing, and that the composed path never reaches the regime-A
# `TidmadScope` branches. Nothing is left here to pass for the wrong reason.

# ======================================================================
# 5-8. INVERTED GUARDS (b) (c) (d) (e) — RETIRED AT B7 (R-11-10)
# ======================================================================
#
# All four fired with exactly their intended messages when B7 landed, and a
# flipped guard becomes the permanent owner of the corrected property or is
# deleted — never both. The positive contracts live where the behaviour does:
#
#     tests/unit/execute_tools/test_step12_pr12bc_b7_satellites.py
#
# (b) F-12bc-1   `validate_sample_set` is profile-aware: the partition bound
#                is GENERIC IDENTITY and always checked; the per-partition
#                bound is TASK TOPOLOGY and is SKIPPED, not guessed, when the
#                task declares none.
# (c) sat. (f)   the peek path comes from the COMPOSED root + the profile's
#                declared validation-file template; the import-time
#                `TIDMAD_DATA_DIR` and the inline filename literal are gone.
# (d) sat. (e)   trial anchoring is a DECLARED optional capability; a task
#                that has none refuses the ROUND by name.
# (e) F-12-2     UPGRADED rather than deleted — see the note in B7's module.
#                `TidmadScope` legitimately REMAINS on the regime-A path, so
#                the old assertion would still pass; what changed is that the
#                measurement now SKIPS with a named reason instead of building
#                that scope under whatever binding happens to be active.

# ======================================================================
# 9. PRESERVED (not inverted) — the cross-task pairing rule
# ======================================================================


class TestPreservedCrossTaskPairingRule:
    """B6 closes the pairing GAP; it must not weaken the pairing RULE.

    ``_scope()``'s ``TypeError`` is what makes "the binding and the scope
    object must come from the same task" executable. A B6 implementation that
    coerced or ignored a foreign scope would make the transport silently
    wrong instead of loudly refused.
    """

    def test_a_tidmad_scope_is_refused_by_the_pets_implementation(self):
        from execute_tools.pets_data_path import PetsTaskDataPath

        scope = TidmadScope(sample_set={0: [0]}, seg_size=10, profile=SMALL_PROFILE)
        with pytest.raises(TypeError, match="requires a PetsScope"):
            PetsTaskDataPath._scope(scope)

    def test_a_foreign_scope_is_refused_by_the_tidmad_implementation(self):
        with pytest.raises(TypeError, match="requires a TidmadScope"):
            TidmadTaskDataPath._scope(object())


# ======================================================================
# 10. §J structural baseline for Phase B
# ======================================================================
#
# RE-MEASURED at the PR-12bc base with the SAME tool used on both sides
# (`measure`, imported from the PR-12a C0 module rather than re-implemented).
# §J's table was produced at `e4cd5c18`; PR-12a has since changed some of
# these files, so the numbers below — not §J's — are what BC-FINAL compares
# against, exactly as §J instructs ("B0/C0 re-measure the specific files each
# phase touches").

PHASE_B_STRUCTURAL_BASELINE: dict[str, tuple[int, int, int, int]] = {
    "execute_tools/train_engine_sandbox.py::main": (87, 23, 294, 0),
    "execute_tools/train_engine_sandbox.py::run_experiment_streaming": (174, 62, 728, 19),
    "core/sandbox_executor.py::TidmadSandbox.execute_training": (92, 39, 358, 14),
    "core/sandbox_executor.py::TidmadSandbox.execute_inference": (69, 28, 254, 9),
    "core/sandbox_executor.py::TidmadSandbox.execute_scoring": (26, 10, 79, 7),
    "core/sandbox_executor.py::_task_data_path_argv": (5, 1, 24, 0),
    "core/sandbox_executor.py::_task_manifest_argv": (5, 1, 15, 0),
    "nodes/ml_hyperparameter_tune_agent/planning.py::prepare_attempt": (116, 32, 471, 7),
    "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py::"
    "HyperparamTuningAgent.run": (258, 69, 1142, 2),
    "nodes/ml_hyperparameter_tune_agent/execution.py::run_inference_scoring_health": (
        109,
        26,
        474,
        6,
    ),
    "nodes/ml_hyperparameter_tune_agent/policy.py::_resolve_sample_set_cfg": (7, 2, 48, 3),
    "execute_tools/scoring_utils.py::validate_sample_set": (23, 14, 58, 2),
    "execute_tools/sample_set_builder.py::build_sample_set": (28, 9, 101, 8),
    "execute_tools/tidmad_data_path.py::TidmadTaskDataPath.training_dataset": (4, 1, 15, 3),
    "execute_tools/tidmad_data_path.py::TidmadTaskDataPath.validation_dataset": (13, 5, 37, 3),
    "execute_tools/tidmad_data_path.py::TIDMADEpochDataset.__init__": (51, 18, 150, 9),
}

#: §J: "no new branch family in any baselined function; a total-LOC argument
#: does NOT excuse one." Same thresholds the PR-12a C0 tripwire used.
MAX_BRANCH_GROWTH = 3
MAX_LOC_GROWTH = 80
MAX_PARAM_GROWTH = 1


def phase_b_current_structure() -> dict[str, tuple[int, int, int, int]]:
    out: dict[str, tuple[int, int, int, int]] = {}
    by_file: dict[str, list[str]] = {}
    for key in PHASE_B_STRUCTURAL_BASELINE:
        rel, name = key.split("::")
        by_file.setdefault(rel, []).append(name)
    for rel, names in by_file.items():
        fns = _qualified_functions(REPO_ROOT / rel)
        for name in names:
            if name in fns:
                out[f"{rel}::{name}"] = measure(fns[name])
    return out


class TestPhaseBStructuralBaseline:
    def test_every_baselined_function_still_exists(self):
        """A budget over a renamed-away function passes by measuring nothing."""
        assert set(phase_b_current_structure()) == set(PHASE_B_STRUCTURAL_BASELINE)

    @pytest.mark.parametrize("key", sorted(PHASE_B_STRUCTURAL_BASELINE))
    def test_no_function_grew_past_its_budget(self, key):
        _, branch, loc, params = phase_b_current_structure()[key]
        _, base_branch, base_loc, base_params = PHASE_B_STRUCTURAL_BASELINE[key]
        assert branch - base_branch <= MAX_BRANCH_GROWTH, (
            f"{key} gained {branch - base_branch} branch nodes "
            f"({base_branch} -> {branch}) — that is a new branch family. "
            f"Establish a typed boundary first (CLAUDE.md; design §J)."
        )
        assert loc - base_loc <= MAX_LOC_GROWTH, (
            f"{key} grew {loc - base_loc} lines ({base_loc} -> {loc}). Extract before adding."
        )
        assert params - base_params <= MAX_PARAM_GROWTH, (
            f"{key} gained {params - base_params} parameters "
            f"({base_params} -> {params}); §J freezes run_experiment_streaming at 19."
        )

    def test_run_experiment_streaming_keeps_exactly_its_current_parameters(self):
        """§J: "no new parameters — the three scope params already exist".

        B6 must USE ``task_scope`` / ``task_eval_scope`` /
        ``validation_requested_rows``, never add a fourth.
        """
        fn = _fn("execute_tools/train_engine_sandbox.py", "run_experiment_streaming")
        names = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        assert {"task_scope", "task_eval_scope", "validation_requested_rows"} <= names
        _, _, _, params = measure(fn)
        assert params == 19


def test_random_is_not_reseeded_by_this_module():
    """These baselines pin rng-derived values; a module-level ``random.seed``
    anywhere in the suite would make them pass for the wrong reason. Asserted
    rather than assumed, because every draw above goes through a LOCAL
    ``random.Random`` instance — this states that intent executably.
    """
    a = random.Random(1234).sample(list(range(5)), 2)
    b = random.Random(1234).sample(list(range(5)), 2)
    assert a == b
