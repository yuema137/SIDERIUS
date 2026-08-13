"""PR-02b Checkpoint C — LIVE integration on the real production path.

Design §5 is explicit about what does NOT satisfy this checkpoint:

    "A test that constructs the profile and calls build_sample_set()
     directly does NOT satisfy this. The question is whether the tuner
     path can still bypass the explicit resolution."

So nothing here calls `build_sample_set` itself. The test drives
`HyperparamTuningAgent.run()` with a REAL `TidmadSandbox`, and asserts on
the JSON file the sandbox actually wrote for the subprocess.

What is real
------------
    tuner run()
      -> resolve_dataset_profile()          REAL (contrast profile bound)
      -> build_sample_set(profile=...)      REAL
      -> _run_skill -> skill wrapper        REAL
      -> sandbox.execute_training/_inference REAL
      -> validate_sample_set                REAL
      -> json.dump -> --sample_set_json     REAL

What is stubbed, and why each is downstream of the property under test
----------------------------------------------------------------------
* the LLM bridge — pseudo planning, no API key (§5: "no real LLM");
* the subprocess launch primitives — no GPU, no training (§5: "no GPU,
  no scientific result"). The launch is stubbed *after* the SampleSet has
  been validated and written, which is precisely the artifact asserted;
* `score_vector` — post-inference scoring, downstream of the boundary.
  Stubbed by SUBCLASSING the real sandbox rather than by patching, so
  `execute_training` and `execute_inference` remain inherited production
  code that no patch can hollow out;
* anchor map / reference scores — scoring inputs, same reasoning.

Ambient resolution inside the builder is made to RAISE for the whole run,
so "no ambient fallback is reachable on that path" is asserted rather than
assumed.
"""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

import core.sandbox_executor as sandbox_module
import execute_tools.sample_set_builder as builder_module
import nodes.ml_hyperparameter_tune_agent as tuner_module
from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    LocalStorageConfig,
    StorageConfig,
)
from core.sandbox_executor import TidmadSandbox
from execute_tools.dataset_config import TIDMAD_PROFILE, bind_dataset_profile
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from tests.unit.agent.tune_ml_hyperparam_agent.test_tuning_agent import (
    FAKE_CONFIG_MANUAL,
    FAKE_PLAN_WITH_TRIAL,
    FAKE_REFLECT_RESPONSE,
    FAKE_RESOURCE_CHECK_OK,
    FAKE_SCORE_RESULT,
    FAKE_SCORE_VECTOR_RESULT,
    _synth_reference,
)

CONTRAST_NUM_FILES = 7


def _contrast_run_input(tmp_path, max_rounds=2):
    """Tuner input for the contrast run.

    ``health_gate_enabled=False`` is REQUIRED here, and not as a
    convenience — it is the remediation the failure itself names. See
    §13.9: `validate_runtime_config` resolves the DataScope against the
    TIDMAD singleton bound as a DEFAULT ARGUMENT, while the HealthGate
    validator computes `scope_is_full` from the AMBIENT profile. Under a
    contrast topology the two disagree and the run is misread as a partial
    DataScope. That is a real genericity gap in the DataScope/HealthGate
    startup path — explicitly NOT 02b's to fix (§2 does not own HealthGate;
    §6.2 lists partial-scope rules as UNCHANGED) — so it is recorded and
    routed rather than worked around silently.
    """
    return HyperparamTuningInput(
        model_type="punet",
        file_index=6,
        max_rounds=max_rounds,
        is_trial=True,
        expert_advice="",
        llm_provider="gemini",
        llm_model_id="test-model",
        health_gate_enabled=False,
        # Bounded by construction. The first pass left these at their
        # defaults (3 attempts x 3 fail-rounds = 9) and each attempt ran a
        # REAL GPU VRAM probe, turning a unit-tier checkpoint into a
        # 14-minute hardware run. One attempt per round is all this
        # checkpoint needs: it asserts a serialized artifact, not a
        # retry policy.
        attempts_per_round=1,
        attempts_per_formal_round=1,
        max_fail_rounds=max_rounds,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test_run"),
        ),
        progress_bar=False,
    )


class _AmbientConsulted(RuntimeError):
    """Raised if the builder ever falls back to ambient resolution."""


def _contrast_profile():
    profile = TIDMAD_PROFILE.model_copy(deep=True)
    profile.dataset.num_files = CONTRAST_NUM_FILES
    return profile


class _RealSandboxWithoutScoring(TidmadSandbox):
    """The production sandbox. Only post-inference scoring is replaced.

    Subclassing rather than patching is deliberate: `execute_training` and
    `execute_inference` — the two methods that own the serialization
    boundary under test — are inherited unchanged, so this cannot pass by
    the boundary having been mocked away.
    """

    def score_vector(self, *args, **kwargs):
        return FAKE_SCORE_VECTOR_RESULT


def _launch_stub(launched, sandbox_holder):
    """Stand in for the GPU child, writing the sentinel training expects.

    `execute_training` treats "returncode 0 but no `_OK_<exp_id>` sentinel"
    as a silent crash, so the stub must write it or inference never runs
    and the eval SampleSet is never serialized — which would leave this
    checkpoint asserting half the boundary.
    """

    def _side_effect(cmd, *args, **kwargs):
        launched.append(cmd)
        if "--exp_id" in cmd and sandbox_holder:
            exp_id = cmd[cmd.index("--exp_id") + 1]
            models = sandbox_holder[0].dirs["models"]
            os.makedirs(models, exist_ok=True)
            with open(os.path.join(models, f"_OK_{exp_id}"), "wb"):
                pass
        result = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return result, None

    return _side_effect


def _selective_run_skill(real_run_skill):
    """Keep training/inference REAL; stub the skills either side of them.

    `training_skill` and `inference_skill` are the only two that reach the
    serialization boundary, so they must be production code. The others are
    stubbed for cost, not convenience: `evaluate_vram_skill` otherwise
    probes the real GPU on every attempt, which turned a bounded checkpoint
    into a 14-minute hardware run on the first pass.
    """
    canned = {
        "check_config_format_skill": FAKE_CONFIG_MANUAL,
        "evaluate_vram_skill": FAKE_RESOURCE_CHECK_OK,
        "denoising_score_skill": FAKE_SCORE_RESULT,
    }

    def _dispatch(skill_folder, sandbox, **params):
        if skill_folder in ("training_skill", "inference_skill"):
            return real_run_skill(skill_folder, sandbox, **params)
        return canned.get(skill_folder, {"status": "error", "message": "unknown skill"})

    return _dispatch


@pytest.fixture
def live_run(tmp_path):
    """Drive the real agent under a contrast topology. Returns artifacts."""
    launched: list = []
    sandboxes: list = []
    contrast = _contrast_profile()

    # PORTABILITY (CLAUDE.md): a real TidmadSandbox resolves dirs["data"] to
    # the MACHINE's configured TIDMAD data directory, and the tuner refuses
    # to start a trial-capable run without `segment_anchors.json` there
    # (ml_hyperparameter_tune_agent.py:3806-3814). Depending on that made
    # this module pass on a developer box with the real dataset and fail on
    # CI with `/path/to/TIDMAD/segment_anchors.json` — a green local result
    # that said nothing about the code under test. The anchor data is
    # redirected into this test's own tmp_path so the run depends on no
    # machine-specific resource. `load_anchor_map` is patched anyway, so
    # only the file's EXISTENCE is load-bearing here.
    anchor_dir = tmp_path / "anchor_data"
    anchor_dir.mkdir()
    (anchor_dir / "segment_anchors.json").write_text(json.dumps({"anchors": {}, "s_max": 1.0}))

    def _factory(**kwargs):
        sandbox = _RealSandboxWithoutScoring(**kwargs)
        sandbox.dirs = {**sandbox.dirs, "data": str(anchor_dir)}
        sandboxes.append(sandbox)
        return sandbox

    real_run_skill = tuner_module._run_skill

    with (
        patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge,
        patch("nodes.ml_hyperparameter_tune_agent.load_anchor_map") as mock_anchor,
        patch(
            "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
            return_value=_synth_reference(),
        ),
        patch("nodes.ml_hyperparameter_tune_agent.get_gates_for_position", return_value=[]),
        # Runtime-control GPU pre-phase measurement. On a host WITH a real
        # device identity (this one has an RTX 5090) it launches a real
        # measurement worker; with the launch primitives stubbed it read a
        # MagicMock `returncode` and raised
        # `TypeError: '<' not supported between MagicMock and int`
        # (gpu_measurement_runner.py:420), aborting the run after round 1 —
        # which is how this checkpoint silently covered trial mode only.
        # PROCEED is the function's own documented early return on a host
        # without a device identity, so this makes the run behave as a
        # CPU-only host. Entirely downstream of selection.
        patch.object(
            tuner_module,
            "_handle_prephase_gpu_measurement",
            return_value=tuner_module.PrephaseOutcome.PROCEED,
        ),
        patch.object(tuner_module, "_run_skill", side_effect=_selective_run_skill(real_run_skill)),
        patch.object(
            sandbox_module,
            "_run_observed_subprocess",
            side_effect=_launch_stub(launched, sandboxes),
        ),
        patch.object(sandbox_module.subprocess, "run"),
        patch.object(sandbox_module.subprocess, "Popen"),
        patch.object(
            builder_module,
            "resolve_dataset_profile",
            side_effect=_AmbientConsulted("build_sample_set fell back to ambient resolution"),
        ) as ambient,
        tempfile.TemporaryDirectory(),
    ):
        mock_brain = MockBridge.return_value
        mock_brain.plan.return_value = FAKE_PLAN_WITH_TRIAL
        mock_brain.reflect.return_value = FAKE_REFLECT_RESPONSE
        mock_anchor.return_value = {"anchors": {}, "s_max": 1.0}

        agent = HyperparamTuningAgent(sandbox_factory=_factory)
        with bind_dataset_profile(contrast):
            agent.run(_contrast_run_input(tmp_path, max_rounds=2))

    return {
        "workspace": tmp_path,
        "launched": launched,
        "ambient": ambient,
        "contrast": contrast,
    }


def _written_sample_sets(workspace) -> dict[str, dict]:
    """Every SampleSet config the REAL sandbox wrote, by filename."""
    found = {}
    for root, _dirs, files in os.walk(workspace):
        for name in files:
            if name.endswith(".json") and "sample_set" in name:
                with open(os.path.join(root, name)) as f:
                    found[name] = json.load(f)
    return found


class TestCheckpointCLiveIntegration:
    def test_import_provenance_is_the_checkout_under_test(self):
        """§5 requirement, adapted honestly.

        No child Python process is launched here — the launch primitives
        are stubbed — so there is no child interpreter whose `sys.path`
        could be audited. What CAN be established is that the modules this
        test exercises are the worktree's, not another clone's: the venv
        carries an editable install pointing at a different checkout, so
        this is a real risk rather than a ceremonial check (§13.0).
        """
        checkout = os.path.dirname(  # .../<checkout>
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        )
        for module in (builder_module, sandbox_module):
            resolved = os.path.realpath(module.__file__ or "")
            assert resolved.startswith(os.path.realpath(checkout)), (
                f"{module.__name__} resolved to {resolved}, outside the checkout "
                f"under test ({checkout}) — the evidence would describe another clone"
            )

    def test_the_real_path_serialized_the_contrast_shape(self, live_run):
        """The load-bearing assertion.

        The file asserted is the one the production sandbox wrote and
        handed to the subprocess via `--sample_set_json`.
        """
        written = _written_sample_sets(live_run["workspace"])
        assert written, (
            "the real tuner run wrote no SampleSet config — the production path "
            "never reached the serialization boundary, so this checkpoint proves "
            "nothing"
        )

        for name, sample_set in written.items():
            assert len(sample_set) == CONTRAST_NUM_FILES, (
                f"{name} carries {len(sample_set)} files; the bound contrast "
                f"topology declares {CONTRAST_NUM_FILES}"
            )
            assert len(sample_set) != TIDMAD_PROFILE.dataset.num_files, (
                f"{name} carries TIDMAD's file population — the production path "
                "selected against the ambient topology"
            )
            assert all(int(k) < CONTRAST_NUM_FILES for k in sample_set), (
                f"{name} contains a file index outside the contrast topology"
            )

    def test_both_train_and_eval_configs_were_written(self, live_run):
        """Both construction sites reached the boundary, not just one.

        `eval` only appears if training SUCCEEDED — inference does not run
        after a failed train step. So this also proves the run got past the
        training phase rather than writing a train config and dying.
        """
        written = _written_sample_sets(live_run["workspace"])
        kinds = {name.split("_sample_set_")[0] for name in written}
        assert {"train", "eval"} <= kinds, (
            f"expected both train and eval SampleSet configs, got {sorted(kinds)}"
        )

    def test_both_rounds_reached_the_boundary(self, live_run):
        """Trial AND formal, not one mode twice.

        §5 requires the trial and formal construction sites both supply the
        profile. Per the §13.0 audit the tuner has ONE call pair serving
        both modes, so the faithful check is that the pair ran in both —
        and the config filenames carry the per-round ``exp_id``, so distinct
        exp_ids are distinct rounds.

        Round 2 is formal by a tuner invariant (the final round is always
        forced formal), which is pinned independently by
        `test_tuning_agent.py::TestDynamicTrialFormal::
        test_final_round_always_formal` — not re-proved here.
        """
        written = _written_sample_sets(live_run["workspace"])
        exp_ids = {name.split("_sample_set_")[1].removesuffix(".json") for name in written}
        assert len(exp_ids) >= 2, (
            f"only {sorted(exp_ids)} reached the serialization boundary; the run "
            "did not exercise both a trial and a formal round, so this checkpoint "
            "covers one mode only"
        )

    def test_no_ambient_fallback_was_reachable(self, live_run):
        """Ambient resolution raised for the whole run and was never hit."""
        live_run["ambient"].assert_not_called()

    def test_the_serialized_set_is_the_one_handed_to_the_subprocess(self, live_run):
        """Same object, one boundary: argv points at the asserted file.

        Guards against the file existing while the subprocess is handed a
        different path — which would make every assertion above describe a
        artifact nothing consumes.
        """
        flagged = []
        for cmd in live_run["launched"]:
            if "--sample_set_json" in cmd:
                flagged.append(cmd[cmd.index("--sample_set_json") + 1])

        assert flagged, "no launch carried --sample_set_json"
        for path in flagged:
            assert os.path.isfile(path)
            with open(path) as f:
                sample_set = json.load(f)
            assert len(sample_set) == CONTRAST_NUM_FILES, (
                f"the config actually handed to the subprocess ({path}) does not "
                "carry the contrast shape"
            )
