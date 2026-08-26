"""Step 12 / PR-12d — CHECKPOINT B: the final three-task pre-Gate matrix.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §M `D8a`, §A.2 (the per-family
disposition table).

Checkpoint A proved the generic seams on CONTRAST-SHAPED fixtures, explicitly
before the shipped Pets/DAVIS declarations existed. **Checkpoint B proves the
opposite half**: TIDMAD, Pets and DAVIS's SHIPPED compositions — the exact
files an operator points ``--task_composition`` at, the exact files `G-12d`
launches against — all compose green, and §A.2's disposition table holds cell
by cell against them.

**The frozen negative falsifier**: *"the matrix must run against the shipped
manifests, not fixtures — a test that would pass with the fixtures
substituted is not Checkpoint B."* Every assertion below is therefore tied to
a property ONLY the shipped state has: `configs/task_composition/pets.yaml`
resolving `pets_reference_cnn` through its OWN `model_plugins:` section, the
exact §22.9a directions, and the DAVIS pseudo-run reaching `run_workflow` —
none of which the Step-10 fixture compositions declare, so substituting them
would make this module fail rather than pass.
"""

from __future__ import annotations

import json
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MANIFEST_DIR = REPO_ROOT / "configs" / "task_composition"

#: The SHIPPED manifests — never the `tests/fixtures/step10_p1/` ones. This
#: is the falsifier's own boundary: everything below composes from HERE.
TIDMAD = MANIFEST_DIR / "tidmad.yaml"
PETS = MANIFEST_DIR / "pets.yaml"
DAVIS = MANIFEST_DIR / "davis.yaml"

TIDMAD_FINGERPRINT = "3fd178b532360c88d741d74748c34f915738b5202a84174b93f7e7816a2bfb56"


@pytest.fixture(autouse=True)
def _restore_health_plugin_globals():
    """Health registration is PROCESS-GLOBAL; this module must not dictate it.

    Composing the shipped DAVIS manifest loads that pack's Health plugins,
    which register `davis.sample_views` and nine checks and set the run scope.
    Left behind, they leak into whatever runs next in the same session and
    produce ORDER-DEPENDENT failures elsewhere — reproduced by inspecting
    `externally_registered_view_providers()` after this module: it returned
    `['davis.sample_views']` with `_RUN_SCOPE` still set.

    That process-globality is deliberate — the Step-08b run-scope guard exists
    precisely because registration cannot be scoped — so the obligation is on
    a test that triggers it to restore what it found. This is the SAME
    snapshot/restore fixture `test_step10_p56_c6_three_task_closure.py`
    already uses for the same reason, not a new mechanism, and it is
    test-isolation hygiene rather than a production reset: nothing here
    weakens the guard or reaches into production lifecycle.
    """
    from execute_tools.health_checks import _plugin_binding
    from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY

    registry = dict(_REGISTRY)
    providers = dict(_PROVIDER_REGISTRY)
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers)
        _plugin_binding.reset_run_scope()


def _compose(manifest: pathlib.Path):
    from workflows.task_composition import compose_run_task_bindings

    return compose_run_task_bindings(str(manifest))


# ======================================================================
# All three SHIPPED compositions compose green
# ======================================================================


class TestAllThreeShippedCompositionsCompose:
    @pytest.mark.parametrize("manifest", [TIDMAD, PETS, DAVIS])
    def test_it_composes_with_no_exception(self, manifest):
        _compose(manifest)

    def test_tidmad_is_UNCHANGED_by_every_pack_declaration_that_followed(self):
        """The anchor every other claim in this checkpoint depends on."""
        assert _compose(TIDMAD).semantic_fingerprint == TIDMAD_FINGERPRINT


# ======================================================================
# §A.2's disposition table, cell by cell, against the SHIPPED state
# ======================================================================


class TestTheDispositionTableHoldsCellByCell:
    """§A.2's table names four legal states per cell:
    ``DECLARED`` / ``INTENTIONALLY ABSENT`` / ``NOT APPLICABLE`` /
    ``LEGACY-ONLY``. This class is that table, executed.
    """

    def test_task_data_path_is_declared_with_the_seam_A_config(self):
        for manifest, expected_id in [
            (PETS, "oxford_iiit_pet"),
            (DAVIS, "davis_future_prediction"),
        ]:
            assert _compose(manifest).task_data_path.task_data_path_id == expected_id

    def test_dataset_profile_is_declared_and_Q_12_4_shaped(self):
        from execute_tools.dataset_config import declares_tidmad_topology

        for manifest in (PETS, DAVIS):
            profile = _compose(manifest).dataset_profile
            assert profile is not None
            assert not declares_tidmad_topology(profile), (
                "a contrast profile must not carry TIDMAD physical geometry"
            )

    def test_metric_is_declared_matching_SS22_9a_exactly(self):
        """The frozen primaries: Pets `accuracy`/HIGHER, DAVIS `mse`/LOWER."""
        pets_metric = _compose(PETS).metric.spec
        assert (pets_metric.id, pets_metric.direction) == ("accuracy", "higher")
        davis_metric = _compose(DAVIS).metric.spec
        assert (davis_metric.id, davis_metric.direction) == ("mse", "lower")

    def test_secondary_metrics_are_DECLARED_PLUS_EXECUTABLE_not_absent(self):
        """The ruling §A.2 states explicitly: never "deliberately absent".

        Executable is asserted by checking each bound implementation's
        `IMPLEMENTS` claim agrees with what it is bound to — the same check
        `_compose_metric` enforces at composition time (F-12d-3).
        """
        pets = _compose(PETS)
        pets_secondaries = {(s.spec.id, s.spec.direction) for s in pets.secondary_metrics or ()}
        assert pets_secondaries == {("macro_f1", "higher"), ("log_loss", "lower")}
        for secondary in pets.secondary_metrics or ():
            assert secondary.spec.id in type(secondary).IMPLEMENTS

        davis = _compose(DAVIS)
        davis_secondaries = {(s.spec.id, s.spec.direction) for s in davis.secondary_metrics or ()}
        assert davis_secondaries == {("psnr", "higher"), ("mae", "lower")}
        for secondary in davis.secondary_metrics or ():
            assert secondary.spec.id in type(secondary).IMPLEMENTS

        # TIDMAD's own row: INTENTIONALLY ABSENT, unaffected by any of this.
        assert not (_compose(TIDMAD).secondary_metrics or ())

    def test_task_config_is_declared_from_SS22_9a(self):
        for manifest in (PETS, DAVIS):
            assert _compose(manifest).task_description is not None

    def test_task_health_is_declared_pack_local(self):
        for manifest in (PETS, DAVIS):
            assert _compose(manifest).task_health_binding is not None

    def test_the_three_blocks_families_are_INTENTIONALLY_ABSENT_first_class_empty(self):
        """Absence and explicit `none: true` are the SAME state (verified via
        the composer itself, not assumed): both packs render nothing."""
        for manifest in (PETS, DAVIS):
            composition = _compose(manifest)
            assert composition.interpretation_blocks is None
            assert composition.proposal_blocks is None
            assert composition.implementor_blocks is None

    def test_deliverable_is_NOT_APPLICABLE_never_the_silent_TIDMAD_default(self):
        """F-A4-1, at the disposition-table level.

        Neither pack DECLARES a `deliverable:` section — there is no such
        key in either manifest — and seam E's refusal is what makes its
        absence honest rather than a silent TIDMAD-template fallback.
        """
        import yaml

        for manifest in (PETS, DAVIS):
            raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
            assert "deliverable" not in raw

    def test_model_plugins_resolve_for_BOTH_packs(self):
        """Not a §A.2 table row (seam P landed after the table was written),
        but load-bearing for `G-12d`: neither track can launch without it.

        F-12d-2 closed for DAVIS at D6 and for Pets at D8a (D-12d-37) — this
        is the regression witness for both, in one place.
        """
        from ml_models.plugin_binding import active_run_model_plugin_roots
        from workflows.task_composition import bind_run_task_composition

        for manifest, expected_type in [
            (PETS, "pets_reference_cnn"),
            (DAVIS, "davis_reference_predictor"),
        ]:
            composition = _compose(manifest)
            with bind_run_task_composition(composition, physical_data_root=str(REPO_ROOT)):
                roots = active_run_model_plugin_roots()
            assert roots, f"{manifest.name} declares no reachable model_plugins root"
            assert composition.model_plugins is not None
            resolved_types = {p.model_type for p in composition.model_plugins.plugins}
            assert expected_type in resolved_types


# ======================================================================
# Integration: a composed run reaches the tuner (Pets already proven; DAVIS closes the gap)
# ======================================================================


class TestADavisRunReachesTheTunerWithItsOwnMetricAndDirection:
    """DAVIS' half of the pseudo-integration evidence D5 already wrote for
    Pets (`test_step12_pr12d_d5_pets_declarations.py::
    test_a_composed_pets_run_reaches_the_tuner_with_ITS_OWN_metric_and_direction`).

    Same defect class: the shipped manifest composes in isolation but
    something on the loop's own path could still substitute an assumed
    metric or direction (the C-P56-1 family) — only a drive through
    `run_workflow` can see that, because the substitution would happen
    BETWEEN composition and the tuner's input. DAVIS' `lower`-is-better
    primary makes this the direction falsifier the Pets case cannot be:
    Pets' `higher` primary would pass even if direction propagation were
    silently hardcoded to `higher` everywhere.

    **Not claimed**: no training, inference or scoring runs here, and this
    is not contrast-track L4 evidence — that is `G-12d`'s.
    """

    def test_the_composed_run_hands_the_tuner_mse_lower(self, tmp_path):
        from unittest.mock import patch

        from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
        from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT
        from tests.unit.workflows.test_model_exploration import (
            _make_implementor_output,
            _make_interpretation_output,
            _make_proposal_output,
            _make_tune_output,
            _make_validator_output,
        )
        from workflows.model_exploration import run_workflow
        from workflows.run_config import WorkflowLaunchConfig
        from workflows.task_composition import bind_run_task_composition

        composition = _compose(DAVIS)
        assert (composition.metric.spec.id, composition.metric.spec.direction) == (
            "mse",
            "lower",
        )

        # A seed stamped with THIS composition — mirrors D5's Pets case
        # exactly (an unstamped or TIDMAD-stamped one is correctly refused,
        # R-11-9 / P2a, which would test the refusal rather than the
        # orchestration).
        agent_dir = tmp_path / "data" / "davis_reference_predictor" / "v1" / "agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "run_output_v1_agent.json").write_text(
            HyperparamTuningOutput(
                run_name="v1",
                model_type="davis_reference_predictor",
                file_index=0,
                status="completed",
                task_composition_fingerprint=composition.semantic_fingerprint,
                completed_rounds=1,
                total_attempts=1,
                best_exp_id="davis_reference_predictor_v1_001",
                best_denoising_score=0.02,
                best_formal_denoising_score=0.02,
                best_config={"model_config": {}, "train_config": {}, "loss_config": {}},
                all_records=[
                    {
                        "exp_id": "davis_reference_predictor_v1_001",
                        "status": "success",
                        "model_type": "davis_reference_predictor",
                        "timestamp": "2026-01-01 00:00:00",
                        "file_index": 0,
                        "params": {"model_config": {}, "train_config": {}, "loss_config": {}},
                        "results": {"denoising_score": 0.02},
                        "denoising_score": 0.02,
                    }
                ],
                started_at="2026-01-01 00:00:00",
                finished_at="2026-01-01 01:00:00",
                metric_spec=composition.metric.spec,
            ).model_dump_json(indent=2)
        )

        seen: dict = {}
        with (
            patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
            patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
            patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
            patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
            patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
        ):

            def _interp(inp):
                seen["interp"] = inp
                return _make_interpretation_output()

            def _tune(inp):
                seen["tune"] = inp
                out = _make_tune_output(model_type=inp.model_type, score=0.02)
                out.metric_spec = composition.metric.spec
                return out

            MockInterp.return_value.run.side_effect = _interp
            MockPropose.return_value.run.return_value = _make_proposal_output("davis_cand_1")
            MockImpl.return_value.run.return_value = _make_implementor_output()
            MockValid.return_value.run.return_value = _make_validator_output(passed=True)
            MockTune.return_value.run.side_effect = _tune

            with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
                results = run_workflow(
                    launch=WorkflowLaunchConfig(
                        data_dir=str(tmp_path / "data"),
                        model_types=["davis_reference_predictor"],
                        source_run_name="v1",
                        max_iterations=1,
                    ),
                    workspace=str(tmp_path / "ws"),
                    run_name="d8a_davis",
                    task_composition=composition,
                )

        assert len(results) == 1
        assert seen["tune"].task_composition_ref is not None
        # The interpreter is handed the run's OWN spec — and it is LOWER, not
        # a hardcoded HIGHER. This is what a Pets-only witness cannot prove.
        assert (seen["interp"].metric_spec.id, seen["interp"].metric_spec.direction) == (
            "mse",
            "lower",
        )
        lock = json.loads(
            (tmp_path / "ws" / "run_invariants_lock.json").read_text(encoding="utf-8")
        )
        assert lock["task_composition_fingerprint"] == composition.semantic_fingerprint


# ======================================================================
# B0 closure + zero unclassified claims
# ======================================================================


class TestB0IsClosedAndTheLedgerIsComplete:
    def test_both_packs_ship_a_composition_manifest(self):
        assert PETS.is_file()
        assert DAVIS.is_file()

    def test_zero_runner_claims_are_still_UNRESOLVED(self):
        """D8a's own acceptance: 'zero claims unclassified.'

        `RUNNER_CLAIMS` carried exactly one UNRESOLVED entry at D0
        (`davis.last_frame_copy_baseline_comparison`), explicitly deferred
        to D8a. This fails if that decision — or any future one — is left
        unmade.
        """
        from tests.unit.guardrails.test_step12_pr12d_d0_baselines import RUNNER_CLAIMS

        unresolved = [
            claim
            for claim, entry in RUNNER_CLAIMS.items()
            if "UNRESOLVED" in entry["intended_owner"]
        ]
        assert unresolved == [], unresolved

    def test_every_claim_has_a_named_disposition(self):
        from tests.unit.guardrails.test_step12_pr12d_d0_baselines import RUNNER_CLAIMS

        assert len(RUNNER_CLAIMS) >= 15, "the ledger must not have silently shrunk"
        for claim, entry in RUNNER_CLAIMS.items():
            assert entry["intended_owner"].strip(), claim


# ======================================================================
# The falsifier itself, made executable
# ======================================================================


class TestTheFixturesWouldFailThisModule:
    """*"a test that would pass with the fixtures substituted is not
    Checkpoint B."* Proven, not just claimed: the fixture compositions
    declare NO `model_plugins:` section, so the model-resolution assertion
    above would fail against them.
    """

    def test_the_fixture_compositions_declare_no_model_plugins(self):
        import yaml

        fixtures = REPO_ROOT / "tests" / "fixtures" / "step10_p1"
        for pack in ("pets", "davis"):
            raw = yaml.safe_load((fixtures / pack / "composition.yaml").read_text(encoding="utf-8"))
            assert "model_plugins" not in raw, (
                f"the {pack} FIXTURE now declares model_plugins — if so, "
                "TestAllThreeShippedCompositionsCompose's falsifier property "
                "needs a different anchor, since this one no longer discriminates"
            )
