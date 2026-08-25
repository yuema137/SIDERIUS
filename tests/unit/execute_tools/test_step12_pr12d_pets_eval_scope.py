"""Step 12 / PR-12d — F-12d-17, the Pets half.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §Q (D-12d-33, D-12d-35).

This pack ships THREE DISJOINT role manifests — train 370, validation 74,
final 370 — and the ``scope`` column inside each is CONSTANT, so the role IS
the file. Before this closed, ``PetsTaskDataPath.build_training_scope`` and
``build_eval_scope`` both selected from the single ``manifest_path``, so a
composed run trained and evaluated on the identical images.

The DAVIS half closed first, inside the D6 workstream
(``execute_tools/davis_data_path.py``); this mirrors it exactly for Pets,
found and closed by the integration owner while auditing D0's runner-claim
ledger for gaps left open by the D6-only fix.

Nothing green caught it. Every deterministic scope test constructs a scope
directly or asserts a round-trip, and ``scripts/run_pets_gate2.py`` loads all
three manifests itself and passes ``task_scope`` / ``task_eval_scope``
explicitly — so the composed path is the ONLY caller that has to CHOOSE.
"""

from __future__ import annotations

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PACK = REPO_ROOT / "examples" / "oxford_iiit_pet"
MANIFESTS = PACK / "data" / "manifests"
SHIPPED = REPO_ROOT / "configs" / "task_composition" / "pets.yaml"


class TestTheEvalScopeIsNotTheTrainingScope:
    @staticmethod
    def _keys(scope) -> set[str]:
        return {row.image_id for row in scope.rows}

    @staticmethod
    def _request():
        from execute_tools.task_data_path import ScopeBuildRequest

        return ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)

    def test_the_shipped_composition_evaluates_on_DISJOINT_images(self):
        """The property, end to end through the shipped manifest."""
        from execute_tools.task_data_path import resolve_task_scope_capability
        from workflows.task_composition import compose_run_task_bindings

        composition = compose_run_task_bindings(str(SHIPPED))
        capability = resolve_task_scope_capability(composition.task_data_path)
        train = self._keys(capability.build_training_scope(self._request()))
        evaluation = self._keys(capability.build_eval_scope(self._request()))

        assert len(train) == 370
        assert len(evaluation) == 74
        assert train & evaluation == set(), (
            "a composed Pets run must not evaluate on images it trained on"
        )

    def test_the_shipped_manifest_DECLARES_the_eval_manifest(self):
        """Reachability: the separation must come from the DECLARATION."""
        raw = yaml.safe_load(SHIPPED.read_text(encoding="utf-8"))
        config = raw["task_data_path"]["config"]
        assert config["manifest_path"]["ref"].endswith("gate2_train.csv")
        assert config["eval_manifest_path"]["ref"].endswith("gate2_validation.csv")

    def test_the_frozen_FINAL_eval_scope_is_still_untouched_by_the_composed_config(self):
        """The other half of the same property: the FROZEN final-eval set is
        deliberately not the composed evaluation manifest, so no composed run
        can contaminate it. ``gate2_validation.csv`` is what a composed run
        evaluates on; ``gate2_final.csv`` stays reserved.
        """
        raw = yaml.safe_load(SHIPPED.read_text(encoding="utf-8"))
        config = raw["task_data_path"]["config"]
        assert "final" not in config["eval_manifest_path"]["ref"]

    def test_omitting_the_eval_manifest_FALLS_BACK_rather_than_crashing(self):
        """The fallback is what keeps the fix additive — and it is a hazard.

        Every pre-existing caller (the D14 runner, the module-level
        registration, every current test) constructs with one path and must
        be byte-unchanged.
        """
        from execute_tools.pets_data_path import PetsTaskDataPath

        single = PetsTaskDataPath(manifest_path=str(MANIFESTS / "gate2_train.csv"))
        assert self._keys(single.build_eval_scope(self._request())) == self._keys(
            single.build_training_scope(self._request())
        )

    def test_the_three_role_manifests_really_are_disjoint(self):
        """The premise, not assumed."""
        from execute_tools.pets_data_path import load_pets_manifest

        train = {r.image_id for r in load_pets_manifest(str(MANIFESTS / "gate2_train.csv"))}
        validation = {
            r.image_id for r in load_pets_manifest(str(MANIFESTS / "gate2_validation.csv"))
        }
        assert len(train) == 370
        assert len(validation) == 74
        assert train & validation == set()
