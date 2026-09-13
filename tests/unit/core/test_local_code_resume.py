"""Current captured model source is selected only after real resume invariants."""

from __future__ import annotations

import pytest

from core.local_code import LocalCodeError
from core.resume import restore_prior_state
from core.run_invariants import RunInvariantsViolation
from ml_models.models_sandbox import MODEL_REGISTRY
from tests.helpers.local_code_model import MODEL_TYPE, make_package
from tests.unit.core.test_resume import _materialise_iter, _plugin_src, isolated_registries
from tests.unit.core.test_step11_c8_invariants_resume import _invariants, _stamped

pytestmark = pytest.mark.usefixtures("isolated_registries", "synthetic_run_authorities")


@pytest.mark.parametrize("old_copy", [True, False])
def test_actual_resume_uses_current_package_instead_of_missing_or_stale_copy(tmp_path, old_copy):
    package, binding = make_package(tmp_path / "current-task")
    workspace = tmp_path / "workspace"
    stamp = package.identity.digest
    _materialise_iter(
        workspace,
        1,
        MODEL_TYPE,
        write_plugin=old_copy,
        plugin_body="raise AssertionError('stale orphan executed')\n",
        run_output_overrides=_stamped(task_composition_fingerprint=stamp),
    )
    expected = MODEL_REGISTRY.pop(MODEL_TYPE)
    # No active package/model binding: this is the actual preactivation shape.
    state = restore_prior_state(
        str(workspace),
        2,
        [],
        expected_invariants=_invariants(task_composition_fingerprint=stamp),
        dataset_partition_count=4,
        model_plugin_binding=binding,
        code_package=package,
    )
    assert state.restored_plugins == [MODEL_TYPE]
    assert state.committed_iters == [1]
    assert MODEL_REGISTRY[MODEL_TYPE] is expected


def test_resume_invariant_mismatch_refuses_before_declared_registration(tmp_path):
    package, binding = make_package(tmp_path / "task")
    workspace = tmp_path / "workspace"
    _materialise_iter(
        workspace,
        1,
        MODEL_TYPE,
        write_plugin=False,
        run_output_overrides=_stamped(task_composition_fingerprint="a" * 64),
    )
    MODEL_REGISTRY.pop(MODEL_TYPE)
    with pytest.raises(RunInvariantsViolation, match="task_composition_fingerprint"):
        restore_prior_state(
            str(workspace),
            2,
            [],
            expected_invariants=_invariants(task_composition_fingerprint="b" * 64),
            dataset_partition_count=4,
            model_plugin_binding=binding,
            code_package=package,
        )
    assert MODEL_TYPE not in MODEL_REGISTRY


@pytest.mark.parametrize("conflicting", [True, False])
def test_resume_generated_fallback_keeps_current_declaration_authoritative(tmp_path, conflicting):
    package, binding = make_package(tmp_path / "task")
    workspace = tmp_path / "workspace"
    prior_model = "resume_test_arch_b"
    _materialise_iter(
        workspace,
        1,
        prior_model,
        plugin_body=_plugin_src(MODEL_TYPE if conflicting else prior_model),
        run_output_overrides=_stamped(task_composition_fingerprint=package.identity.digest),
    )
    original = MODEL_REGISTRY[MODEL_TYPE]

    def restore():
        return restore_prior_state(
            str(workspace),
            2,
            [],
            expected_invariants=_invariants(task_composition_fingerprint=package.identity.digest),
            dataset_partition_count=4,
            model_plugin_binding=binding,
            code_package=package,
        )

    if conflicting:
        with pytest.raises(LocalCodeError, match="captured member identity"):
            restore()
    else:
        assert restore().restored_plugins == [prior_model]
        assert prior_model in MODEL_REGISTRY
    assert MODEL_REGISTRY[MODEL_TYPE] is original
