"""Step 12 / PR-12d — F-12d-23: composed Pets/DAVIS now resolve `model_io`.

Design: ``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §Q D-12d-42 (the finding), §A.2 (the
source-audit note this corrects).

**The defect these tests name.** `examples/{oxford_iiit_pet,davis_future_prediction}/
declared/task_config.yaml` used to author `forward_contract` in prose-only
Regime A, reasoning (recorded, now corrected) that `declared/
model_io_contract.json` already carried the structured contract and a second
copy would just duplicate it. That reasoning conflated two different paths:
the JSON fixture is read only by this pack's own declaration tests; the YAML's
`forward_contract.model_io` field is what `run_bound_model_io_contract()`
resolves at RUN TIME, feeding the admission resource-check's
`execute_tools.model_input_dtype.resolve_input_dtype`. Undeclared, that
resolver had no contract to consult and fell back to its `int64` site
preference — correct for TIDMAD's raw-signal models, wrong for these
float-native image/video models. A real `G-12d` Track 2 launch hit exactly
this: ``RuntimeError: Input type (long int) and bias type (float) should be
the same``, 100% reproducing, before any training step.

If either test class below were deleted: a composed Pets or DAVIS real launch
would crash in the admission resource-check before training starts, and
nothing short of that real launch would show it — `resolve_input_dtype` was
never previously called with a REAL composed Pets/DAVIS contract by any test.
"""

from __future__ import annotations

import json
import pathlib

import pytest
import torch

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MANIFEST_DIR = REPO_ROOT / "configs" / "task_composition"

PETS_MANIFEST = MANIFEST_DIR / "pets.yaml"
DAVIS_MANIFEST = MANIFEST_DIR / "davis.yaml"
PETS_FIXTURE = REPO_ROOT / "examples" / "oxford_iiit_pet" / "declared" / "model_io_contract.json"
DAVIS_FIXTURE = (
    REPO_ROOT / "examples" / "davis_future_prediction" / "declared" / "model_io_contract.json"
)
# A real, portable, self-deriving directory — same precedent as
# ``test_step12_pr12d_checkpoint_b.py``'s ``physical_data_root=str(REPO_ROOT)``.
# None of these tests touch data loading, only `run_model_io`/`load_task_config`,
# so the binding only needs a directory that genuinely exists on any checkout.
PETS_DATA_ROOT = str(REPO_ROOT)
DAVIS_DATA_ROOT = str(REPO_ROOT)

CASES = [
    pytest.param(PETS_MANIFEST, PETS_FIXTURE, "pets_reference_cnn", PETS_DATA_ROOT, id="pets"),
    pytest.param(
        DAVIS_MANIFEST, DAVIS_FIXTURE, "davis_reference_predictor", DAVIS_DATA_ROOT, id="davis"
    ),
]


def _bound_model_io(manifest: pathlib.Path, data_root: str):
    """The composed run's `run_model_io`, exactly as the tuner resolves it.

    Uses the SAME two calls ``ml_hyperparameter_tune_agent.py::main`` makes
    (``compose_run_task_bindings`` then ``bind_run_task_composition``) —
    not a shortcut through ``load_task_config`` directly, so this test would
    fail if the wiring between composition and the forward-contract loader
    ever broke, not just the YAML content.
    """
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings
    from workflows.task_config import run_bound_model_io_contract

    composition = compose_run_task_bindings(str(manifest))
    with bind_run_task_composition(composition, physical_data_root=data_root):
        return run_bound_model_io_contract()


class TestComposedRunsNowDeclareModelIO:
    """The regression: a composed run must not resolve `model_io=None`."""

    @pytest.mark.parametrize("manifest,fixture,model_type,data_root", CASES)
    def test_model_io_is_declared_not_none(self, manifest, fixture, model_type, data_root):
        assert _bound_model_io(manifest, data_root) is not None


class TestResourceCheckDtypeResolvesFloat32NotInt64:
    """The exact defect: the probe/resource-check dtype for an image/video model."""

    @pytest.mark.parametrize("manifest,fixture,model_type,data_root", CASES)
    def test_resolved_probe_dtype_is_float32(self, manifest, fixture, model_type, data_root):
        from execute_tools.model_input_dtype import resolve_input_dtype

        contract = _bound_model_io(manifest, data_root)
        dtype = resolve_input_dtype(model_type, contract, site_preference="int64")
        assert dtype == torch.float32, (
            f"{model_type} resolved probe dtype {dtype}, not float32 — this is F-12d-23's "
            "exact defect: an undeclared `model_io` falls back to the int64 site preference, "
            "which crashes a float-native model's forward with 'Input type (long int) and "
            "bias type (float) should be the same' before any training step."
        )


class TestTaskConfigModelIONeverDivergesFromTheFrozenFixture:
    """The hazard the ORIGINAL comment worried about, made a mechanical check.

    Two files declare the same contract now (`task_config.yaml`'s live
    `model_io`, and `declared/model_io_contract.json`'s pinned fixture). An
    editor changing one without the other is exactly the duplicate-authority
    drift the removed "Regime-A prose form deliberately" comment tried to
    avoid by having only one copy — this test enforces the same property
    without giving up the live wiring that copy cost.
    """

    @pytest.mark.parametrize("manifest,fixture,model_type,data_root", CASES)
    def test_yaml_model_io_matches_the_json_fixture(self, manifest, fixture, model_type, data_root):
        from agent.schemas.model_io_contract import ModelIOContract

        live = _bound_model_io(manifest, data_root)
        frozen = ModelIOContract(**json.loads(fixture.read_text(encoding="utf-8")))
        assert live == frozen


class TestDerivedProseIsUnchanged:
    """Proves the fix is silent to the LLM-facing prompt: no new information,
    only a previously-inert declaration becoming the live authority for
    fields that already rendered these exact strings from hand-authored
    prose."""

    def test_pets_derived_shapes_match_the_original_hand_authored_prose(self):
        from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings
        from workflows.task_config import load_task_config

        composition = compose_run_task_bindings(str(PETS_MANIFEST))
        with bind_run_task_composition(composition, physical_data_root=PETS_DATA_ROOT):
            fc = load_task_config()["forward_contract"]
        assert fc["input_shape"] == "[B, 3, 144, 144] float32"
        assert fc["output_shape"] == "[B, 37] float32"
        assert fc["num_classes"] == 37

    def test_davis_derived_shapes_match_the_original_hand_authored_prose(self):
        from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings
        from workflows.task_config import load_task_config

        composition = compose_run_task_bindings(str(DAVIS_MANIFEST))
        with bind_run_task_composition(composition, physical_data_root=DAVIS_DATA_ROOT):
            fc = load_task_config()["forward_contract"]
        assert fc["input_shape"] == "[B, 3, 8, 128, 224] float32"
        assert fc["output_shape"] == "[B, 3, 4, 128, 224] float32"
        assert fc["num_classes"] == 0
