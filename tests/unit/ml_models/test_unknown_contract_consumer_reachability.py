"""V21 PR C1 — every production consumer reaches AND translates the failure.

``test_unknown_output_contract_fails_closed.py`` proves the helper raises.
That is not evidence that any production path notices, which is PR A's
central lesson: a rule existing in source is not evidence that every
consumer honours it. PR A shipped three consumers still assuming the
classifier contract while every deterministic checkpoint was green.

So this module drives each of the five real consumers and asserts two
things per consumer:

  reachability   the consumer actually calls ``get_output_type``, so the
                 invariant failure arrives there at all
  translation    it converts to that layer's typed refusal, and does not
                 let a raw ``UnknownOutputContractError`` escape

The five were enumerated in the PR C design doc §0.2 / §0.5a. The fifth
(``agent/prompts.py``) was missed by the first census because that census
was built from the execution path; prompt rendering is not on it.

One consumer is not exercised here: ``execute_tools/inference_single.py``.
It is a subprocess ``__main__`` script whose lookup sits inside the
inference body, and it is unreachable by construction — its
``--denoising_model`` is the live model passed by
``sandbox_executor.execute_inference`` after ``_validate_configs`` already
resolved that same model's contract. Its guard is defence in depth and is
covered by source inspection, recorded in the design doc rather than
claimed as a test here.
"""

from __future__ import annotations

import pytest

from ml_models.plugin_loader import UnknownOutputContractError

pytestmark = pytest.mark.usefixtures("synthetic_task_config", "synthetic_physical_data_root")

_UNREGISTERED = "c1_consumer_probe_unregistered_model"


# ---------------------------------------------------------------------------
# Consumer 1 — the generated-plugin branch of TidmadSandbox._validate_configs
# ---------------------------------------------------------------------------


def test_sandbox_plugin_branch_reports_a_registration_defect(monkeypatch, tmp_path):
    """A model in PLUGIN_CONFIG_REGISTRY but not PLUGIN_OUTPUT_TYPE_REGISTRY.

    This is the *partial registration* case: the two registries have
    diverged. It is reachable only through the generated-plugin branch,
    which is the only branch the agent's own models take.

    The refusal must be distinguishable from an ordinary config rejection.
    V20 spent two PRs (#184, then #185) misdiagnosing a
    ``CONFIG_REJECTED`` that was really a registry-reconstruction failure;
    folding this into the generic "Configuration Rejected" message would
    reproduce that misdiagnosis exactly.

    Fails if: the guard is removed (message becomes the generic one), or
    the lookup is moved out of the branch.
    """
    import ml_models.models_format_sandbox as mfs
    from core.sandbox_executor import TidmadSandbox
    from ml_models.models_format_sandbox import PUNetConfig

    # Register a config class but deliberately NOT an output type.
    monkeypatch.setitem(mfs.PLUGIN_CONFIG_REGISTRY, _UNREGISTERED, PUNetConfig)

    sandbox = TidmadSandbox(workspace=str(tmp_path), file_index=0)

    with pytest.raises(ValueError) as exc:
        sandbox._validate_configs(
            _UNREGISTERED,
            {},
            {"epochs": 1, "batch_size": 2, "lr": 1e-3, "optimizer": "adam"},
            {"loss_type": "focal"},
            exp_id="c1_probe",
            run_name="c1_probe_run",
        )

    message = str(exc.value)
    assert "Plugin Output Contract Unavailable" in message
    assert "registration defect" in message
    # Must NOT be misreported as a config the agent could fix.
    assert "Plugin Experiment Configuration Rejected" not in message


# ---------------------------------------------------------------------------
# Consumer 2 — ExperimentConfig's architecture/loss validator
# ---------------------------------------------------------------------------


def test_experiment_config_surfaces_a_validation_error(monkeypatch):
    """``ExperimentConfig``'s validator converts to a Pydantic error.

    Driving this needs care. ``model_type`` is a plain ``str``, but the
    ``network_config`` union only admits the built-in config classes, so an
    arbitrary unregistered name cannot be used to reach the validator.

    Instead the registry is made to *lose* a model that is otherwise fully
    valid: ``punet`` is deleted from ``BUILTIN_OUTPUT_TYPES`` for the
    duration of the test. That is precisely the production scenario — a
    model whose config is intact while its output contract is not
    established — and it reaches the real validator on the real class.

    Fails if: the validator lets ``UnknownOutputContractError`` escape as a
    raw ``LookupError`` (Pydantic would not wrap it), or swallows it and
    re-derives a default contract.
    """
    import pydantic

    import ml_models.models_sandbox as ms
    from ml_models.models_format_sandbox import ExperimentConfig, PUNetConfig

    patched = dict(ms.BUILTIN_OUTPUT_TYPES)
    del patched["punet"]
    monkeypatch.setattr(ms, "BUILTIN_OUTPUT_TYPES", patched)

    with pytest.raises(pydantic.ValidationError) as exc:
        ExperimentConfig(
            exp_id="c1_probe",
            run_name="c1_probe_run",
            model_type="punet",
            network_config=PUNetConfig(),
            train_config={"epochs": 1, "batch_size": 2, "lr": 1e-3, "optimizer": "adam"},
            loss_config={"loss_type": "focal"},
        )

    message = str(exc.value)
    assert "REGISTRATION FAILED" in message
    assert "punet" in message


# ---------------------------------------------------------------------------
# Consumer 4 — the VRAM probe's target-tensor builder
# ---------------------------------------------------------------------------


def test_vram_probe_refuses_rather_than_probing_the_wrong_shape():
    """The probe must refuse, not fall through to the classifier shape.

    This is the highest-consequence consumer. The else-branch builds a
    ``[B, 256, T]`` target, so a fall-through would probe an unregistered
    regressor against the classifier shape and produce a VRAM forecast
    describing a different model. PR A's A3c fixed exactly this class of
    error after Gate 2R caught it.

    Fails if: the guard is removed and ``output_type`` stays ``None``,
    which silently selects the 256-bin target.
    """
    from agent.skills.evaluate_vram_skill.wrapper import _build_probe_tensors

    with pytest.raises(ValueError) as exc:
        _build_probe_tensors(
            batch_size=1,
            seg_size=64,
            loss_type="smooth_l1",
            loss_name=None,
            model_type=_UNREGISTERED,
        )

    assert "probe target" in str(exc.value)
    assert _UNREGISTERED in str(exc.value)


# ---------------------------------------------------------------------------
# Consumer 5 — planner prompt rendering (the one the first census missed)
# ---------------------------------------------------------------------------


def test_planner_prompt_refuses_an_unresolvable_forced_model():
    """Prompt rendering must refuse, not guess the legal loss families.

    ``force_model`` selects which losses the planner is *told* are legal.
    Guessing would hand the agent a prompt contradicting the live
    compatibility rule, making every plan it produces invalid — a failure
    that would surface far downstream as unexplained plan rejections.

    Note this consumer deliberately does NOT follow the defensive
    ``except Exception -> degrade`` pattern used a few lines earlier for
    the custom-loss probe. Degrading there costs the agent an option;
    degrading here corrupts the contract.

    Fails if: the guard is removed, or someone widens it into the
    custom-loss probe's swallow-and-continue idiom.
    """
    from agent.prompts import get_planner_user_prompt

    with pytest.raises(ValueError) as exc:
        get_planner_user_prompt(
            memory_history=[],
            expert_advice="",
            force_model=_UNREGISTERED,
        )

    message = str(exc.value)
    assert "planner prompt" in message
    assert _UNREGISTERED in message


def test_planner_prompt_still_renders_for_auto_and_for_builtins():
    """The guard must not disturb the two normal paths.

    ``force_model="auto"`` never looks up a contract at all, and a built-in
    resolves. Both must render exactly as before.
    """
    from agent.prompts import get_planner_user_prompt

    for force_model in ("auto", "punet", "fcnet"):
        rendered = get_planner_user_prompt(
            memory_history=[],
            expert_advice="",
            force_model=force_model,
        )
        assert isinstance(rendered, str) and rendered
