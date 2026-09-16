"""Step 12 / PR-12a — C2: the typed composition projection and every consumer.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12a_composed_path_closure.md`` §5 C2 (D-12a-1).

The tuner learns "this run is composed, and by what" from its **INPUT**. Both
consumers of that fact move in this one commit — the W4 reference-science
discriminator and the per-model run-invariants lock's identity kwargs — so no
temporary dual authority ever exists (the frozen ordering rule).

WHAT THE PROJECTION IS NOT
--------------------------
It is not a second semantic authority. The composed run's real authorities are
unchanged run-scoped bindings, and the record/output composition-fingerprint
STAMPS still read ``active_composition_fingerprint()`` at exactly two call
sites — Step 11's F-11-C10-a fix, which Gate 2 caught the hard way when the
two stamps had different sources. `TestTheStampsStillReadTheRunScopedAuthority`
keeps that pin visible from this PR's side too.

This module also RETIRES C0's inverted guard
``TestInvertedGuardBTunerOmitsCompositionIdentity`` (R-11-10: replace, never
twin) and closes the half C1 explicitly deferred — the per-model effective
Health document's binding markers, and therefore its body sha.
"""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest
import yaml

from agent.schemas.custom_loss_contract import custom_loss_snapshot_from_forward_contract
from core.capability_registry import CapabilityMetadata
from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT
from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration
from tests.helpers.step12_pr12a_prompt_capture import PREFLIGHT_FIXTURE
from workflows.model_exploration import build_task_composition_ref
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "step10_p1"
QUICKSTART = REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"
MASKED_REGRESSION = REPO_ROOT / "configs" / "task_composition" / "synthetic_masked_regression.yaml"
TUNER_PACKAGE = REPO_ROOT / "src/nodes" / "ml_hyperparameter_tune_agent"


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    registry = dict(_REGISTRY)
    providers = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers)
        _plugin_binding.reset_run_scope()


def _preflight() -> list[dict]:
    return json.loads(PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"]


def _locks(workspace: str) -> list[dict]:
    paths = sorted(Path(workspace).rglob("run_invariants_lock.json"))
    assert paths, "the run must write a lock, or the assertion below is vacuous"
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


# ======================================================================
# The projection itself
# ======================================================================


class TestTheProjection:
    def test_it_carries_the_compositions_own_resolved_values(self):
        """Every field is a value the composition already resolved. Compared
        against the composition object, because 'nothing is re-derived here'
        is exactly the property — not against a hardcoded literal, which would
        pin a fixture rather than the mapping."""
        composition = compose_run_task_bindings(str(QUICKSTART))
        ref = build_task_composition_ref(composition)

        assert ref is not None
        assert ref.semantic_fingerprint == composition.semantic_fingerprint
        assert ref.task_health_binding == composition.task_health_binding
        assert ref.task_data_path_id == "quickstart_tabular"
        assert ref.segmentation_applicability == "not_applicable"

    def test_an_un_composed_run_projects_nothing(self):
        assert build_task_composition_ref(None) is None

    def test_two_different_tasks_project_different_identities(self):
        """Anti-vacuity: a builder that returned a constant would satisfy the
        row above for every task."""
        quickstart = build_task_composition_ref(compose_run_task_bindings(str(QUICKSTART)))
        _plugin_binding.reset_run_scope()
        masked_regression = build_task_composition_ref(
            compose_run_task_bindings(str(MASKED_REGRESSION))
        )
        assert quickstart is not None and masked_regression is not None
        assert quickstart.semantic_fingerprint != masked_regression.semantic_fingerprint
        assert quickstart.task_data_path_id != masked_regression.task_data_path_id


# ======================================================================
# Consumer 1 — the W4 reference-science discriminator
# ======================================================================


class TestW4ReadsTheInputNotTheAmbientEnvironment:
    """The re-key. The W4 census in ``test_step10_p56_c5_wiring_closures.py``
    follows the guard's key and keeps its forbidden-token list unchanged; this
    module owns the RUNTIME consequence.
    """

    def test_the_tuner_package_has_no_ambient_composition_read_left(self):
        """The acceptance criterion, as a census: zero
        ``active_task_data_path`` USES anywhere in the tuner package.

        AST-based, not a text scan. The tuner keeps a comment explaining what
        the guard used to read and why it moved — that history is worth
        keeping, and a substring census would call it a violation. What must
        be zero is references the interpreter can execute: calls, imports and
        bare name loads.
        """
        offenders: list[str] = []
        for path in TUNER_PACKAGE.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == "active_task_data_path":
                    offenders.append(f"{path.name}: name load")
                elif isinstance(node, ast.Attribute) and node.attr == "active_task_data_path":
                    offenders.append(f"{path.name}: attribute access")
                elif isinstance(node, ast.ImportFrom) and any(
                    alias.name == "active_task_data_path" for alias in node.names
                ):
                    offenders.append(f"{path.name}: import")
        assert offenders == []

    def test_the_guard_follows_the_FIELD_even_with_the_contextvars_unbound(self, capsys):
        """THE MUTATION THE DESIGN ASKS FOR, as a permanent test.

        Populate the projection while binding NOTHING. If the guard still read
        the ambient accessor it would see an un-composed process and load
        TIDMAD's reference tables; reading the field, it must announce the
        named absence. This is what proves the read actually moved rather than
        the two merely agreeing in production.
        """
        _plugin_binding.reset_run_scope()

        from execute_tools.task_data_path import active_task_data_path
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            _load_trial_anchor_map,
        )

        assert active_task_data_path() is None, "the ContextVars must be UNBOUND for this test"
        assert _load_trial_anchor_map(composed=True, data_root="unused") is None
        printed = capsys.readouterr().out
        assert "trial anchoring SKIPPED — this composed run" in printed


# ======================================================================
# Consumer 2 — the per-model run-invariants lock
# ======================================================================


class TestThePerModelLockRecordsTheComposition:
    """Replaces C0's inverted guard (b-tuner) and closes F-P56-3.

    HOW IT FAILS WHEN THE BEHAVIOUR BREAKS: drop either kwarg from the tuner's
    ``build_run_invariants`` call and a composed workspace goes back to a lock
    that cannot say which task produced it, and to a per-model Health document
    stamped ``legacy_default`` while carrying the task's roster.
    """

    def test_a_composed_run_stamps_the_fingerprint(self, tmp_path, monkeypatch):
        composition = compose_run_task_bindings(str(QUICKSTART))
        ref = build_task_composition_ref(composition)
        assert ref is not None

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            _out, _bridge, _sandbox, workspace = run_bounded_pseudo_iteration(
                tmp_path,
                monkeypatch,
                preflight_results=_preflight(),
                input_overrides={"health_gate_enabled": False, "task_composition_ref": ref},
            )

        for lock in _locks(workspace):
            assert lock["task_composition_fingerprint"] == composition.semantic_fingerprint

    def test_the_per_model_health_document_matches_the_chains(self, tmp_path, monkeypatch):
        """**The half C1 deferred (F-12a-C1-3), now closed.**

        C1 made the tuner's re-materialization a ROSTER no-op by handing it the
        chain's effective config. It could not make the BODY SHA equal, because
        08b restamps ``body_markers()`` from the binding it is called with and
        the tuner passed none — so the per-model document said
        ``legacy_default`` while carrying the task's gates. With the binding
        arriving on the projection, both documents are the same document.

        The framework-owned masked-regression composition supplies a real
        task-owned Health roster while keeping this framework contract test
        independent of any scientific task.
        """
        from core.run_invariants import RunHealthMaterialization, build_run_invariants

        composition = compose_run_task_bindings(str(MASKED_REGRESSION))
        ref = build_task_composition_ref(composition)
        assert ref is not None
        loss_snapshot = custom_loss_snapshot_from_forward_contract(composition.forward_contract)
        assert loss_snapshot is not None
        generated_root = tmp_path / "generated_library"
        generated_loss_dir = generated_root / "losses"
        generated_loss_dir.mkdir(parents=True)
        loss_plugin = generated_loss_dir / "masked_mse_loss.py"
        shutil.copyfile(
            REPO_ROOT / "examples/synthetic_masked_regression/plugins/masked_mse_loss.py",
            loss_plugin,
        )
        monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(generated_root))
        capability_index = tmp_path / "capability_index.json"
        capability_index.write_text(
            json.dumps(
                [
                    CapabilityMetadata(
                        name="synthetic_masked_mse",
                        capability_type="loss",
                        file_path=str(loss_plugin),
                        created_at="2026-09-13T00:00:00Z",
                        contract_snapshot=loss_snapshot,
                    ).model_dump(mode="json")
                ]
            ),
            encoding="utf-8",
        )

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            chain_workspace = tmp_path / "chain"
            chain_workspace.mkdir()
            chain_invariants, chain_config = build_run_invariants(
                resolved_data_scope=list(range(3)),
                health_gate_enabled=True,
                health_gate_files=None,
                health_checks_config=None,
                workspace=str(chain_workspace),
                health_materialization=RunHealthMaterialization(
                    task_health_binding=composition.task_health_binding,
                ),
                task_composition_fingerprint=composition.semantic_fingerprint,
            )
            _out, _bridge, _sandbox, workspace = run_bounded_pseudo_iteration(
                tmp_path / "run",
                monkeypatch,
                preflight_results=_preflight(),
                capability_index_path=str(capability_index),
                input_overrides={
                    "health_gate_enabled": True,
                    "task_composition_ref": ref,
                    # What the workflow now hands the tuner (C1's D-12a-2).
                    "health_checks_config": chain_config,
                },
            )

        for lock in _locks(workspace):
            assert lock["health_config_sha256"] == chain_invariants.health_config_sha256
            assert lock["task_composition_fingerprint"] == composition.semantic_fingerprint

        documents = sorted(Path(workspace).rglob("health_checks_effective.yaml"))
        assert documents, "a gates-on run must materialize a per-model effective config"
        for document in documents:
            body = yaml.safe_load(document.read_text(encoding="utf-8"))
            assert body["task_health_binding"] == "explicit"


class TestTheStampsStillReadTheRunScopedAuthority:
    """Step 11's F-11-C10-a pin, re-asserted from this PR's side.

    The projection must not become the source of the record/output composition
    stamps. Gate 2 caught those two disagreeing once already; the fix was ONE
    authority, and a convenient new field on the input is exactly the shape
    that would quietly undo it.
    """

    def test_all_stamps_still_call_the_run_scoped_accessor(self):
        source = (TUNER_PACKAGE / "records.py").read_text(encoding="utf-8")
        calls = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "active_composition_fingerprint"
        ]
        # Record, output, and trained-model artifact identities share the
        # same run-scoped authority.
        assert len(calls) == 3

    def test_the_record_module_does_not_read_the_projection(self):
        source = (TUNER_PACKAGE / "records.py").read_text(encoding="utf-8")
        assert "task_composition_ref" not in source
