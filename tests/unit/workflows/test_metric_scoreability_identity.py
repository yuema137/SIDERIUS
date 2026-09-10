"""#425: validity plugins must participate in composition and resume identity."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from core.run_invariants import (
    RunInvariants,
    RunInvariantsViolation,
    validate_run_invariants,
    write_run_invariants,
)
from execute_tools.task_registration_scope import run_registration_scope
from workflows.task_composition import compose_run_task_bindings

ROOT = Path(__file__).resolve().parents[3]
GATE = """from execute_tools.evaluation_metric import (
    ScoreabilityContract, ScoreabilityVerdict, ScoreabilityFailure,
)
class Gate(ScoreabilityContract):
    contract_id: str = "external_gate"
    def check(self, deliverables):
        return ScoreabilityVerdict(contract_id=self.contract_id, failures=FAILURES)
"""
REFUSAL = '(ScoreabilityFailure(requirement="integrity", detail="rejected"),)'


@pytest.fixture(autouse=True)
def _isolated_task_registration():
    with run_registration_scope():
        yield


def _write_task(root: Path) -> dict:
    """A real external composition using only the synthetic Quickstart adapter."""
    root.mkdir(parents=True, exist_ok=True)
    manifest = yaml.safe_load((ROOT / "configs/task_composition/quickstart.yaml").read_text())
    # Keep unrelated assets fixed while the task's metric/gate files relocate.
    for section, key in (
        ("task_data_path", "file"),
        ("dataset_profile", "config"),
        ("task_config", "config"),
    ):
        manifest[section][key] = str(
            (ROOT / "configs/task_composition" / manifest[section][key]).resolve()
        )
    manifest.pop("model_plugins")
    # This consumer has its own registration identity; it must not replace a
    # Quickstart registration inherited from another test/run in this process.
    adapter = Path(manifest["task_data_path"]["file"]).read_text()
    (root / "adapter.py").write_text(
        adapter.replace(
            'QUICKSTART_TASK_ID = "quickstart_tabular"',
            'QUICKSTART_TASK_ID = "scoreability_identity_fixture"',
        )
    )
    manifest["task_data_path"]["file"] = "adapter.py"
    manifest["task_data_path"]["id"] = "scoreability_identity_fixture"
    (root / "metric.py").write_text(
        "from execute_tools.evaluation_metric import EvaluationMetric\n"
        "class Metric(EvaluationMetric):\n"
        "    def _compute(self, deliverables, /, **kwargs): return 1., None, ()\n"
    )
    for name in ("primary", "secondary"):
        (root / f"{name}.json").write_text(
            json.dumps(
                {
                    "id": name,
                    "direction": "higher",
                    "aggregation": "single_value",
                    "references": [],
                    "scoreability": {"contract_id": "external_gate"},
                }
            )
        )
    (root / "permit.py").write_text(GATE.replace("FAILURES", "()"))
    (root / "refuse.py").write_text(GATE.replace("FAILURES", REFUSAL))
    manifest["metric"] = _metric("primary", "permit.py")
    return manifest


def _metric(name: str, gate: str) -> dict:
    return {
        "declaration": f"{name}.json",
        "implementation": {"file": "metric.py", "symbol": "Metric"},
        "scoreability_contracts": {"external_gate": {"file": gate, "symbol": "Gate"}},
    }


def _compose(root: Path, manifest: dict):
    path = root / "task.yaml"
    path.write_text(yaml.safe_dump(manifest))
    return compose_run_task_bindings(str(path))


@pytest.mark.parametrize("secondary", [False, True], ids=["primary", "secondary"])
@pytest.mark.parametrize("mutation", ["reference", "content"])
def test_changed_scoreability_refuses_resume(tmp_path, secondary, mutation):
    """Gate changes cannot reuse old results even with unchanged metric arithmetic."""
    root = tmp_path / "task"
    manifest = _write_task(root)
    if secondary:
        manifest["secondary_metrics"] = [_metric("secondary", "permit.py")]
        # Keep the primary independent so a lost secondary carrier is exposed.
        manifest["metric"]["scoreability_contracts"]["external_gate"]["file"] = "refuse.py"
    before = _compose(root, manifest)
    if mutation == "reference":
        section = manifest["secondary_metrics"][0] if secondary else manifest["metric"]
        section["scoreability_contracts"]["external_gate"]["file"] = "refuse.py"
    else:
        (root / "permit.py").write_text(GATE.replace("FAILURES", REFUSAL))
    after = _compose(root, manifest)
    old_metric = before.secondary_metrics[0] if secondary else before.metric
    new_metric = after.secondary_metrics[0] if secondary else after.metric
    assert old_metric.spec.scoreability.check({}).scoreable
    assert not new_metric.spec.scoreability.check({}).scoreable
    assert before.semantic_fingerprint != after.semantic_fingerprint
    assert any(p.absolute_path == str(root / "permit.py") for p in before.provenance.plugins)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    old_lock = RunInvariants(
        resolved_data_scope=[0],
        health_gate_enabled=False,
        health_config_sha256=None,
        task_composition_fingerprint=before.semantic_fingerprint,
    )
    write_run_invariants(str(workspace), old_lock)
    new_lock = old_lock.model_copy(
        update={"task_composition_fingerprint": after.semantic_fingerprint}
    )
    with pytest.raises(RunInvariantsViolation, match="task_composition_fingerprint"):
        validate_run_invariants(str(workspace), new_lock)


def test_swapping_gates_between_metric_roles_changes_identity(tmp_path):
    """Hashing an unordered set of files alone misses primary/secondary swaps."""
    manifest = _write_task(tmp_path)
    manifest["secondary_metrics"] = [_metric("secondary", "refuse.py")]
    before = _compose(tmp_path, manifest)
    manifest["metric"]["scoreability_contracts"]["external_gate"]["file"] = "refuse.py"
    manifest["secondary_metrics"][0]["scoreability_contracts"]["external_gate"]["file"] = (
        "permit.py"
    )
    after = _compose(tmp_path, manifest)
    assert before.metric.spec.scoreability.check({}).scoreable
    assert not after.metric.spec.scoreability.check({}).scoreable
    assert before.semantic_fingerprint != after.semantic_fingerprint


def test_unchanged_gate_identity_is_portable(tmp_path):
    """Repeated composition and relocation must not require a new workspace."""
    root = tmp_path / "original"
    manifest = _write_task(root)
    manifest["secondary_metrics"] = [_metric("secondary", "refuse.py")]
    first = _compose(root, manifest)
    again = _compose(root, manifest)
    relocated = tmp_path / "relocated"
    shutil.copytree(root, relocated)
    other = _compose(relocated, manifest)
    assert first.semantic_fingerprint == again.semantic_fingerprint == other.semantic_fingerprint
    assert [p.canonical_identity() for p in first.provenance.plugins] == [
        p.canonical_identity() for p in other.provenance.plugins
    ]
    assert first.provenance.plugins[-1].absolute_path != other.provenance.plugins[-1].absolute_path


@pytest.mark.parametrize("mutation", ["module", "symbol"])
def test_module_gate_selection_is_semantic(tmp_path, monkeypatch, mutation):
    """A repo-pinned module's selected gate must not inherit the loader's None ref."""
    manifest = _write_task(tmp_path)
    module_name = f"gate_{tmp_path.name}"
    (tmp_path / f"{module_name}.py").write_text(
        GATE.replace("FAILURES", "()")
        + GATE.replace("FAILURES", REFUSAL).replace("class Gate(", "class RefusingGate(")
    )
    (tmp_path / f"{module_name}_other.py").write_text(GATE.replace("FAILURES", REFUSAL))
    monkeypatch.syspath_prepend(str(tmp_path))
    plugin = {"module": module_name, "symbol": "Gate"}
    manifest["metric"]["scoreability_contracts"]["external_gate"] = plugin
    before = _compose(tmp_path, manifest)
    if mutation == "module":
        plugin["module"] += "_other"
    else:
        plugin["symbol"] = "RefusingGate"
    after = _compose(tmp_path, manifest)
    assert before.metric.spec.scoreability.check({}).scoreable
    assert not after.metric.spec.scoreability.check({}).scoreable
    assert before.semantic_fingerprint != after.semantic_fingerprint
    # No fake file digest is invented for a module selection.
    assert before.provenance.plugins == after.provenance.plugins


@pytest.mark.parametrize("plugin_kind", ["file", "module"])
def test_null_opposite_plugin_key_preserves_valid_binding(tmp_path, plugin_kind):
    """Identity projection must accept exactly the nullable alternatives the loader does."""
    manifest = _write_task(tmp_path)
    plugin = manifest["metric"]["scoreability_contracts"]["external_gate"]
    if plugin_kind == "module":
        plugin.clear()
        plugin.update(
            module="execute_tools.evaluation_metric", symbol="PresenceScoreabilityContract"
        )
    before = _compose(tmp_path, manifest)
    plugin["module" if plugin_kind == "file" else "file"] = None
    after = _compose(tmp_path, manifest)
    assert before.semantic_fingerprint == after.semantic_fingerprint
    assert before.metric.spec.scoreability.check({}) == after.metric.spec.scoreability.check({})


def test_no_custom_contract_keeps_original_plugin_identity(tmp_path):
    """Absence and an explicit empty extension must add no fingerprint content."""
    manifest = _write_task(tmp_path)
    manifest["metric"].pop("scoreability_contracts")
    declaration = json.loads((tmp_path / "primary.json").read_text())
    declaration["scoreability"] = {"contract_id": "deliverable_presence"}
    (tmp_path / "primary.json").write_text(json.dumps(declaration))
    before = _compose(tmp_path, manifest)
    manifest["metric"]["scoreability_contracts"] = {}
    after = _compose(tmp_path, manifest)
    assert before.semantic_fingerprint == after.semantic_fingerprint
    assert [(p.configured_ref, p.symbol) for p in before.provenance.plugins] == [
        (manifest["task_data_path"]["file"], "QuickstartTaskDataPath"),
        ("metric.py", "Metric"),
    ]
