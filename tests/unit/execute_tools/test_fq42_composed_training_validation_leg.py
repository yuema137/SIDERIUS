"""F-Q4-2 (v0.1.0, witnessed 2026-08-26) — the composed training child's
validation-declaration leg.

THE INCIDENT. Q4 v2 composed TIDMAD chain: 5/5 training attempts exited 1 on
``run_experiment_streaming``'s crosswise refusal ("refusing two"), zero
training, zero records. Mechanism: ``validation_rows_argv`` gated on scope
PRESENCE (``task_scopes.evaluation is not None``) — true on EVERY composed run
because every shipped implementation declares ``build_eval_scope`` — while a
composed run whose task declares physical geometry (composed TIDMAD) also
still supplies the legacy eval SampleSet (PR-12bc D-BC-13). So the training
child received BOTH declaration authorities, and D14-2 C5b's one-authority-
per-leg contract correctly refused.

THE DESIGN ANSWER (PR-12bc audit, frozen; now implemented by the emitter):
WHICH leg owns the validation-row declaration is the child's own dichotomy —
the PRESENCE of ``--eval_sample_set_json``. Under regime-A the child's
preflight is the ONLY declaration authority and ``--validation_requested_rows``
must stay off the wire; only the explicit leg (a transported eval scope
WITHOUT a regime-A eval SampleSet — every composed contrast run) consumes it.
The task-built evaluation scope still crosses on BOTH legs as scope IDENTITY.

HISTORY, and why the silence assertion below is mandatory: this defect has two
inversions. Pre-12d, rows were emitted by NOTHING and the explicit leg
(composed contrast) refused; 12d's fix emitted them on scope presence and the
regime-A leg (composed TIDMAD) refused. Each fix of one direction created the
other. The third inversion would start from the observation "the acquired eval
scope is not consumed for validation rows on the regime-A leg" being read as a
bug instead of the contract — so that consequence is asserted here BY NAME.

Un-composed byte-identity is NOT re-pinned here — it has standing owners:
``test_step12_pr12bc_b6_scope_transport.py::TestTheTrainingArgv::
test_an_un_composed_run_emits_no_scope_flag``,
``test_step12_pr12d_f12d27_training_scope_transport.py::
TestUncomposedArgvIsUnchanged`` and the D0 ``FORBIDDEN_ON_LEGACY`` guards.
The explicit-leg contrast witness (rows PRESENT when no SampleSet exists) is
likewise already owned by ``TestComposedScopeReachesTheTrainingChildWithout
ASampleSet`` and stays green — this module deliberately does not duplicate it.

Each test states the defect only it catches and how it fails when the
behaviour breaks.
"""

from __future__ import annotations

import pathlib
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import core.sandbox_executor as se
import execute_tools.train_engine_sandbox as tes
from execute_tools.scope_artifact import task_scope_argv, validation_rows_argv
from execute_tools.task_data_path import ScopeBuildRequest, bind_task_data_path
from execute_tools.tidmad_data_path import TidmadScope, TidmadTaskDataPath
from ml_models.models_format_sandbox import LossConfig, TrainConfig
from nodes.ml_hyperparameter_tune_agent.scope_acquisition import AttemptScopes

# Reused, not duplicated: the D14-1 C5 synthetic task is the established way
# to drive the REAL engine body on CPU with no TIDMAD data (pure defs, no
# module state, tests are an importable package).
from tests.unit.execute_tools.test_d14_synthetic_e2e import (
    _MODEL_TYPE,
    SyntheticE2ETaskDataPath,
    _synthetic_contract,
    _TinyClassifier,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
TIDMAD_MANIFEST = str(REPO_ROOT / "configs" / "task_composition" / "tidmad.yaml")

#: The tuner's own selection knobs, mirrored so the acquisition below is the
#: production call shape (`planning.py` -> `acquire_attempt_scopes`).
_SEG_SIZE = 10_000


def _composed_tidmad_training_argv() -> tuple[list[str], AttemptScopes]:
    """The EXACT 5/5-witnessed spawn shape, through the REAL production route.

    Shipped TIDMAD manifest -> `bind_run_task_composition` -> the REAL
    `acquire_attempt_scopes` (not a hand-built ``AttemptScopes``) -> the REAL
    `TidmadSandbox.execute_training` argv builder, intercepted at
    `_run_observed_subprocess` (the symbol BOTH launch branches call — the
    f12d27 capture pattern). The legacy SampleSets are the acquired scopes'
    own sets, which is what production's `build_sample_set` parity gives it
    (12bc's differential oracle: capability-built deep-equals legacy-built).

    No TIDMAD data is required: snapshot scope construction is profile
    metadata, and the fixed emitter never materializes the eval dataset on
    the regime-A leg.
    """
    from nodes.ml_hyperparameter_tune_agent.scope_acquisition import (
        acquire_attempt_scopes,
    )
    from workflows.task_composition import (
        bind_run_task_composition,
        compose_run_task_bindings,
    )

    composition = compose_run_task_bindings(TIDMAD_MANIFEST)
    workspace = tempfile.mkdtemp()
    captured: dict[str, list[str]] = {}

    def _stop(cmd, **_kwargs):
        captured["cmd"] = cmd
        raise SystemExit("argv captured")

    with bind_run_task_composition(composition, physical_data_root=workspace):
        scopes = acquire_attempt_scopes(
            composed=True,
            mode="trial",
            trial_strategy="snapshot",
            trial_portion=0.05,
            eval_strategy="snapshot",
            eval_portion=0.05,
            train_sampling_seed=3,
            eval_sampling_seed=4,
            target_files=None,
            subset=None,
            validation_max_samples=None,
            task_parameters={"seg_size": _SEG_SIZE},
        )
        sandbox = se.TidmadSandbox(run_name="fq42", workspace=workspace, progress_bar=False)
        with patch.object(se, "_run_observed_subprocess", side_effect=_stop):
            try:
                sandbox.execute_training(
                    "fq42_exp",
                    "fq42",
                    "fcnet",
                    {"model_type": "fcnet", "segmentation_size": _SEG_SIZE},
                    {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"},
                    {"loss_type": "ce"},
                    sample_set=scopes.training.sample_set,
                    eval_sample_set=scopes.evaluation.sample_set,
                    task_scopes=scopes,
                )
            except BaseException:
                pass
    assert "cmd" in captured, (
        "the training spawn was never reached — argv construction failed "
        "before launch, which is the pre-fix failure shape (the emitter "
        "materializing the eval dataset on the regime-A leg)"
    )
    return [t for t in captured["cmd"] if isinstance(t, str)], scopes


@pytest.fixture(scope="module")
def composed_tidmad_argv() -> tuple[list[str], AttemptScopes]:
    return _composed_tidmad_training_argv()


class TestComposedTidmadTrainingArgvCarriesOneValidationAuthority:
    """THE F-Q4-2 witness. Fails (pre-fix) by `--validation_requested_rows`
    appearing next to `--eval_sample_set_json` — the exact argv the child
    refused 5/5 — or by the spawn never being reached at all (the emitter's
    parent-side eval materialization over a data-less root)."""

    def test_the_regime_a_declaration_is_present(self, composed_tidmad_argv):
        argv, _ = composed_tidmad_argv
        assert "--eval_sample_set_json" in argv

    def test_the_explicit_declaration_is_absent(self, composed_tidmad_argv):
        argv, _ = composed_tidmad_argv
        assert "--validation_requested_rows" not in argv

    def test_exactly_one_validation_declaration_authority_on_the_wire(self, composed_tidmad_argv):
        """The invariant whose violation IS the crosswise refusal: the child
        dispatches its declaration authority on flag presence, so the parent
        must put exactly one declaration on the wire."""
        argv, _ = composed_tidmad_argv
        assert ("--eval_sample_set_json" in argv) != ("--validation_requested_rows" in argv)

    def test_the_scope_identity_still_crosses_on_the_regime_a_leg(self, composed_tidmad_argv):
        """The fix removed the DECLARATION from the regime-A leg, not the
        scope IDENTITY: 12bc's four-flag transport (task_scope + eval-scope
        ref/digest pairs) is unchanged, and the child's R3 pass still receives
        the task-built scope. Fails if the repair is widened into suppressing
        the eval-scope artifact itself — a different (12bc-frozen) contract."""
        argv, _ = composed_tidmad_argv
        for flag in (
            "--task_scope_ref",
            "--task_scope_digest",
            "--task_eval_scope_ref",
            "--task_eval_scope_digest",
        ):
            assert flag in argv, f"{flag} must still cross on the regime-A leg"


class TestTheRegimeALegSilence:
    """MANDATORY silence assertion (reviewer-required).

    On the regime-A leg, ``task_scopes.evaluation`` IS built by the task and
    is deliberately NOT consumed for validation rows — the preflight owns the
    declaration; the scope crosses as identity only. WHY assert an absence by
    name: an unconsumed task-owned value that quietly governs nothing is where
    the THIRD inversion of this defect would start — a future reader "fixing"
    the silence by re-emitting the count, which re-creates the 5/5 refusal.
    This test turns that silence from an accident into a stated contract.
    """

    def test_the_acquired_eval_scope_is_not_consumed_for_validation_rows(
        self, composed_tidmad_argv
    ):
        argv, scopes = composed_tidmad_argv
        # The scope was REALLY acquired (this is not vacuous absence) ...
        assert scopes.evaluation is not None
        assert isinstance(scopes.evaluation, TidmadScope)
        # ... and the declaration is REALLY absent from the emitted argv.
        assert "--validation_requested_rows" not in argv

    def test_the_emitter_returns_nothing_on_the_regime_a_leg_without_touching_data(self):
        """Emitter-level form of the same silence, plus its cost consequence:
        the regime-A return happens BEFORE `validation_dataset`, so the parent
        no longer materializes eval data for a count the child refuses.
        Fails if the leg gate is removed (rows re-emitted) or reordered after
        the materialization (this data-less TidmadScope would raise)."""
        scopes = AttemptScopes(
            training=TidmadScope(sample_set={0: [1]}, seg_size=_SEG_SIZE),
            evaluation=TidmadScope(sample_set={3: [0]}, seg_size=_SEG_SIZE),
        )
        with bind_task_data_path(TidmadTaskDataPath()):
            fragment = validation_rows_argv(
                scopes, "/nonexistent/data/root", regime_a_eval_declared=True
            )
        assert fragment == []


class TestTheCrosswiseRefusalIsIntact:
    """MANDATORY negative: the D14-2 C5b contract itself, live.

    This is the test that goes RED if anyone "fixes" F-Q4-2 by weakening,
    reordering or special-casing the ENGINE refusal instead of the emitter.
    It is also the refusal's first reachability witness — before this, the
    "refusing two" text was verified only by source inspection (12bc §Q.B6).
    The other direction (explicit scope WITHOUT rows refused) is already
    owned live by ``test_d14_synthetic_e2e.py::
    test_explicit_eval_scope_without_declared_rows_fails_loudly``.
    """

    def test_both_authorities_at_the_child_still_refuse(self, tmp_path, monkeypatch):
        monkeypatch.setitem(tes.MODEL_REGISTRY, _MODEL_TYPE, _TinyClassifier)
        sandbox_dirs = {"models": str(tmp_path / "models"), "results": str(tmp_path / "results")}
        for d in sandbox_dirs.values():
            pathlib.Path(d).mkdir()
        with pytest.raises(ValueError, match="refusing two"):
            tes.run_experiment_streaming(
                SimpleNamespace(model_type=_MODEL_TYPE, segmentation_size=4),
                TrainConfig(lr=1e-3, epochs=1, batch_size=2, optimizer_type="adam", device="cpu"),
                LossConfig(loss_type="ce"),
                sample_set={0: [1]},
                data_dir=str(tmp_path),
                sandbox_dirs=sandbox_dirs,
                exp_id="fq42_refusal",
                eval_sample_set={0: [0]},
                validation_requested_rows=3,
            )


class TestTheChildAcceptsTheFixedMixedState:
    """The child half of the witness: parse+validation ACCEPTS what the fixed
    parent now sends — regime-A declaration + transported eval scope + NO
    explicit row count — and runs R3 with the preflight as the declaration
    authority and the TRANSPORTED scope as the identity.

    Coordinates that matter (exactly the fixed composed argv, decoded):
    ``eval_sample_set`` non-None, ``task_eval_scope`` non-None,
    ``validation_requested_rows`` None. Driven through the REAL engine body
    under the synthetic binding; ``_preflight_validation_scope`` (TIDMAD's
    HDF5 counter, the regime-A declaration authority) is spied so the test
    both avoids real data AND proves that authority is the one consulted.
    Fails if the mixed state starts being refused (a "both flags or neither"
    over-correction at the child) or if the declaration stops coming from the
    preflight.
    """

    def test_mixed_state_trains_with_the_preflight_as_declaration_authority(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setitem(tes.MODEL_REGISTRY, _MODEL_TYPE, _TinyClassifier)
        sandbox_dirs = {"models": str(tmp_path / "models"), "results": str(tmp_path / "results")}
        for d in sandbox_dirs.values():
            pathlib.Path(d).mkdir()

        eval_ids = ["va", "vb", "vc"]
        regime_a_declaration = {0: [0, 1]}
        preflight_calls: list[dict] = []

        def _spy_preflight(data_dir, eval_sample_set, seg_size, profile):
            preflight_calls.append(eval_sample_set)
            # The value is THIS TEST's, not one read back from the pass; the
            # engine's requested==materialized check then holds against the
            # synthetic eval dataset's real length.
            return len(eval_ids)

        monkeypatch.setattr(tes, "_preflight_validation_scope", _spy_preflight)
        with bind_task_data_path(SyntheticE2ETaskDataPath()):
            results = tes.run_experiment_streaming(
                SimpleNamespace(model_type=_MODEL_TYPE, segmentation_size=4),
                TrainConfig(lr=1e-3, epochs=1, batch_size=2, optimizer_type="adam", device="cpu"),
                LossConfig(loss_type="ce"),
                sample_set={},
                data_dir=str(tmp_path),
                sandbox_dirs=sandbox_dirs,
                exp_id="fq42_mixed",
                train_base_seed=7,
                model_io=_synthetic_contract(),
                task_scope=["a", "b", "c", "d"],
                eval_sample_set=regime_a_declaration,
                task_eval_scope=list(eval_ids),
                validation_requested_rows=None,
            )
        assert results is not None
        th = results["training_history"]
        # Declaration = the preflight's count (consulted exactly once, with
        # the regime-A declaration), identity = the transported scope.
        assert preflight_calls == [regime_a_declaration]
        assert th["validation_requested_samples"] == len(eval_ids)
        assert th["validation_samples"] == len(eval_ids)
        assert len(th["validation_objective"]) == 1
        assert th["comparability"] == "established"


class TestExplicitLegPairing:
    """MANDATORY pairing test, at the emitter layer with the REAL emitters.

    The explicit leg's two transports — the eval-scope ref/digest pair
    (``task_scope_argv``) and the declared row count
    (``validation_rows_argv``) — must never be able to outrun each other:
    the count is emitted ONLY when the artifact it declares is transported
    too, and on the explicit leg they arrive together. The explicit leg IS
    production-reachable (every composed contrast run: `planning.py` builds
    no legacy SampleSets when the profile declares no physical geometry —
    witnessed by ``TestComposedScopeReachesTheTrainingChildWithoutASample
    Set``); only the (training=None, evaluation!=None) corner is
    emitter-level-only today, since ``acquire_attempt_scopes`` builds both
    legs or neither for every shipped task. Fails when either emitter's
    gate drifts from the other's — e.g. rows re-keyed on scope presence
    alone (F-Q4-2 itself), or emitted for an eval scope whose artifact the
    training-scope early return suppressed (a silently dangling
    declaration the engine would ignore).
    """

    _TRAIN = TidmadScope(sample_set={0: [1]}, seg_size=_SEG_SIZE)
    _EVAL = TidmadScope(sample_set={3: [0]}, seg_size=_SEG_SIZE)

    class _SizedStub:
        def __len__(self) -> int:
            return 7

    @pytest.mark.parametrize("regime_a", [False, True])
    @pytest.mark.parametrize(
        "training,evaluation",
        [(None, None), (_TRAIN, None), (None, _EVAL), (_TRAIN, _EVAL)],
    )
    def test_rows_are_emitted_iff_the_explicit_leg_is_active(
        self, tmp_path, training, evaluation, regime_a
    ):
        scopes = AttemptScopes(training=training, evaluation=evaluation)
        explicit_leg_active = training is not None and evaluation is not None and not regime_a
        with (
            bind_task_data_path(TidmadTaskDataPath()),
            patch.object(TidmadTaskDataPath, "validation_dataset", return_value=self._SizedStub()),
        ):
            scope_fragment = (
                task_scope_argv(str(tmp_path), "fq42_pair", scopes)
                if (training is not None or evaluation is not None)
                else []
            )
            rows_fragment = validation_rows_argv(
                scopes, str(tmp_path), regime_a_eval_declared=regime_a
            )
        rows_emitted = "--validation_requested_rows" in rows_fragment
        ref_emitted = "--task_eval_scope_ref" in scope_fragment
        assert rows_emitted == explicit_leg_active
        if rows_emitted:
            # Together, never alone: the count's artifact is on the same argv.
            assert ref_emitted
            assert rows_fragment == ["--validation_requested_rows", "7"]
        if not ref_emitted:
            # A declaration must never outrun the scope it declares.
            assert not rows_emitted
