# tests/unit/examples/test_pets_health_family.py
"""Step 08c C3 — the Pets task-owned Health family, through the external interface.

Owns:

* the immutability of the committed REAL collapse fixture-of-record
  (sha256 + size pinned — the parent §9 evidence cannot silently drift);
* the full state-C chain on that fixture — shipped policy-only framework
  config + the pack's ``declared/task_health.yaml`` + the pack's plugin →
  BOTH blocking gates FAIL with all four §2.5 evidence values persisted,
  and the framework SAYS what D14 could only observe;
* the healthy counterfactual (both gates PASS — without it an
  always-failing family satisfies the collapse test);
* the §2.12 codec-parity regression: production writer bytes →
  ``pets_data_path`` reader AND → the pack provider projection agree on
  header semantics and ``{image_id: class}`` content;
* fail-closed pair (missing plugin file → ``HealthPluginError``; roster
  naming an unregistered check → ``HealthBindingError``);
* provider error paths (bad header / missing deliverable → ERROR verdict
  through the gate);
* the pack-identifier census: nothing Pets-specific — not the provider
  id, not the gate ids, not the cardinality 37 — appears in generic
  health core.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

from execute_tools.health_checks import _plugin_binding, runner
from execute_tools.health_checks._plugin_binding import (
    HealthBindingError,
    HealthPluginError,
)
from execute_tools.health_checks.config import load_composed_health_config
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from execute_tools.health_checks.schemas import (
    CheckVerdict,
    HealthCheckContext,
    applicability,
)
from execute_tools.pets_data_path import EvaluationReadRequest, PetsTaskDataPath

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK = REPO_ROOT / "examples" / "oxford_iiit_pet"
TASK_HEALTH = PACK / "declared" / "task_health.yaml"
PLUGIN = PACK / "plugins" / "_pets_health_views.py"
FIXTURE = PACK / "expected" / "d14_gate2_collapse_predictions.csv"

# The frozen fixture-of-record pin (child design §2.4, invariant 21).
FIXTURE_SHA256 = "cc8470267fbf5331827c7b641ac2ce8efb834b07441a31836084d4d417ff752c"
FIXTURE_SIZE = 6_812

# The four §2.5 evidence values, hardcoded.
PETS_N = 370
PETS_DISTINCT = 2
PETS_OCCUPANCY = 0.05405405405405406  # 2/37
PETS_DOMINANT_FRACTION = 0.9972972972972973  # 369/370
PETS_DOMINANT_SYMBOL = 5

DISTINCT_GATE = "pets_distinct_symbols_blocking"
DOMINANT_GATE = "pets_dominant_fraction_blocking"

# The deliverable-grammar name the fixture bytes carried in production
# (D14: predictions_{model_type}_{run_name}_{exp_id}.csv).
PRODUCTION_NAME = "predictions_pets_reference_cnn_d14p_pets_gate2_001.csv"


@pytest.fixture(autouse=True)
def _isolated_registries_and_run_scope():
    """Local snapshot/restore — the health-package conftest is out of scope here."""
    registry_snapshot = dict(_REGISTRY)
    provider_snapshot = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry_snapshot)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(provider_snapshot)
        _plugin_binding.reset_run_scope()


def _ctx(deliverable: Path | None) -> HealthCheckContext:
    kwargs = {"model_name": "pets_reference_cnn", "run_name": "r", "round_index": 1}
    if deliverable is not None:
        kwargs["denoised_paths"] = {0: str(deliverable)}
    return HealthCheckContext(**kwargs)


def _compose(monkeypatch, task_health_path: Path = TASK_HEALTH):
    """The real state-C chain: shipped policy-only framework + pack config."""
    composed, task_config, plugins = load_composed_health_config(None, str(task_health_path))
    monkeypatch.setattr(runner, "load_health_gates_config", lambda *a, **k: composed)
    return composed, task_config, plugins


class TestFixtureOfRecord:
    def test_the_committed_fixture_is_byte_identical_to_the_preserved_evidence(self):
        data = FIXTURE.read_bytes()
        assert len(data) == FIXTURE_SIZE
        assert hashlib.sha256(data).hexdigest() == FIXTURE_SHA256


class TestStateCChainOnTheRealCollapse:
    def test_composition_resolves_the_pack_family(self, monkeypatch):
        composed, task_config, plugins = _compose(monkeypatch)

        assert [g.id for g in composed.health_gates] == [DISTINCT_GATE, DOMINANT_GATE]
        for gate in composed.health_gates:
            assert gate.gate_role == "blocking"
            assert gate.on_fail.action.value == "invalidate_round"
            # The injected fact arrived beside the authored threshold.
            assert gate.checks[0].config["symbol_cardinality"] == 37
        assert composed.health_gates[0].checks[0].config["min_distinct_symbols"] == 5
        assert composed.health_gates[1].checks[0].config["max_dominant_fraction"] == 0.95
        assert task_config is not None and task_config.facts.symbol_cardinality == 37
        assert [p.configured_ref for p in plugins] == ["../plugins/_pets_health_views.py"]

    def test_both_blocking_gates_fail_on_the_fixture_with_the_evidence_values(self, monkeypatch):
        _compose(monkeypatch)
        ctx = _ctx(FIXTURE)

        distinct = runner.evaluate_gate(DISTINCT_GATE, ctx)
        (distinct_result,) = distinct.check_results
        assert distinct_result.verdict is CheckVerdict.FAILED
        assert distinct_result.metrics["n_samples"] == PETS_N
        assert distinct_result.metrics["distinct_symbols"] == PETS_DISTINCT
        assert distinct_result.metrics["occupancy"] == PETS_OCCUPANCY
        assert distinct.action.value == "invalidate_round"

        dominant = runner.evaluate_gate(DOMINANT_GATE, ctx)
        (dominant_result,) = dominant.check_results
        assert dominant_result.verdict is CheckVerdict.FAILED
        assert dominant_result.metrics["dominant_fraction"] == PETS_DOMINANT_FRACTION
        assert dominant_result.metrics["dominant_symbol"] == PETS_DOMINANT_SYMBOL
        assert dominant.action.value == "invalidate_round"

    def test_the_healthy_counterfactual_passes_both_gates(self, monkeypatch, tmp_path):
        _compose(monkeypatch)
        healthy = tmp_path / PRODUCTION_NAME
        rows = "\n".join(f"img_{i:04d},{i % 37}" for i in range(PETS_N))
        healthy.write_text(f"image_id,predicted_class_index\n{rows}\n", encoding="utf-8")
        ctx = _ctx(healthy)

        for gate_id in (DISTINCT_GATE, DOMINANT_GATE):
            result = runner.evaluate_gate(gate_id, ctx)
            assert result.passed is True, gate_id
            assert result.check_results[0].verdict is CheckVerdict.PASSED, gate_id

    def test_the_int8_family_is_inapplicable_under_the_pets_declaration(self, monkeypatch):
        """The 8.4-B rung with a REAL task's declared facts."""
        from execute_tools.health_checks.amplitude_collapse import AmplitudeCollapseCheck
        from execute_tools.health_checks.output_diversity import OutputDiversityCheck
        from execute_tools.health_checks.output_std import OutputStdCheck
        from execute_tools.health_checks.pearson_dispersion import PearsonDispersionCheck
        from execute_tools.health_checks.per_file_output_std import PerFileOutputStdCheck
        from execute_tools.health_checks.spectral_peak_ratio import SpectralPeakRatioCheck

        _, task_config, _ = _compose(monkeypatch)
        assert task_config is not None
        facts = task_config.resolved_facts()
        # Context inputs are decided BEFORE fact axes, so satisfy them all
        # (target source included) — the assertion is about the FACT
        # mismatch, not about a missing context input.
        ctx = HealthCheckContext(
            model_name="pets_reference_cnn",
            run_name="r",
            round_index=1,
            denoised_paths={0: str(FIXTURE)},
            target_path_fn=lambda fi: f"/tmp/target_{fi:04d}.h5",
        )
        for check_cls in (
            OutputDiversityCheck,
            OutputStdCheck,
            AmplitudeCollapseCheck,
            PerFileOutputStdCheck,
            SpectralPeakRatioCheck,
            PearsonDispersionCheck,
        ):
            verdict = applicability(check_cls.declaration, facts, ctx)
            assert verdict.applicable is False, check_cls.name
            assert verdict.axis == "encoding_family", check_cls.name


class TestCodecParity:
    """§2.12 — one deliverable format, two readers, zero drift."""

    @staticmethod
    def _load_plugin_module():
        spec = importlib.util.spec_from_file_location("_pets_health_views_under_test", PLUGIN)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(spec.name, None)
        return module

    def test_both_readers_agree_on_the_fixture_bytes(self, tmp_path):
        production_copy = tmp_path / PRODUCTION_NAME
        shutil.copyfile(FIXTURE, production_copy)

        production_payload = PetsTaskDataPath().read_evaluation_payload(
            EvaluationReadRequest(
                deliverable_dir=str(tmp_path),
                exp_id="pets_gate2_001",
                run_name="d14p",
                model_type="pets_reference_cnn",
            )
        )
        module = self._load_plugin_module()
        provider_payload = module.project_predictions(FIXTURE)

        assert provider_payload == production_payload
        assert len(provider_payload) == PETS_N

    def test_both_readers_refuse_the_same_bad_header(self, tmp_path):
        bad = tmp_path / PRODUCTION_NAME
        bad.write_text("image,klass\nAbyssinian_2,5\n", encoding="utf-8")

        with pytest.raises(ValueError, match="header"):
            PetsTaskDataPath().read_evaluation_payload(
                EvaluationReadRequest(
                    deliverable_dir=str(tmp_path),
                    exp_id="pets_gate2_001",
                    run_name="d14p",
                    model_type="pets_reference_cnn",
                )
            )
        module = self._load_plugin_module()
        with pytest.raises(ValueError, match="header"):
            module.project_predictions(bad)


class TestFailClosedPair:
    def _relocated_pack(self, tmp_path: Path, *, with_plugin: bool = True) -> Path:
        declared = tmp_path / "declared"
        declared.mkdir()
        config_path = declared / "task_health.yaml"
        shutil.copyfile(TASK_HEALTH, config_path)
        if with_plugin:
            plugins = tmp_path / "plugins"
            plugins.mkdir()
            shutil.copyfile(PLUGIN, plugins / PLUGIN.name)
        return config_path

    def test_a_missing_plugin_file_fails_closed(self, tmp_path):
        config_path = self._relocated_pack(tmp_path, with_plugin=False)
        with pytest.raises(HealthPluginError, match="_pets_health_views"):
            load_composed_health_config(None, str(config_path))

    def test_a_roster_naming_an_unregistered_check_fails_closed(self, tmp_path):
        config_path = self._relocated_pack(tmp_path)
        text = config_path.read_text(encoding="utf-8").replace(
            "check: categorical_distinct_symbols", "check: pets_nonexistent_check"
        )
        config_path.write_text(text, encoding="utf-8")
        with pytest.raises(HealthBindingError, match="pets_nonexistent_check"):
            load_composed_health_config(None, str(config_path))

    def test_the_relocated_pack_still_composes(self, tmp_path, monkeypatch):
        """The same package at a different absolute path is the same family
        (refs are config-relative — the 08b path-independence contract)."""
        config_path = self._relocated_pack(tmp_path)
        composed, _, _ = load_composed_health_config(None, str(config_path))
        assert [g.id for g in composed.health_gates] == [DISTINCT_GATE, DOMINANT_GATE]


class TestProviderErrorPaths:
    def test_a_bad_header_is_an_ERROR_verdict_through_the_gate(self, monkeypatch, tmp_path):
        _compose(monkeypatch)
        bad = tmp_path / PRODUCTION_NAME
        bad.write_text("not,a,pets,deliverable\n", encoding="utf-8")
        result = runner.evaluate_gate(DISTINCT_GATE, _ctx(bad))
        (check_result,) = result.check_results
        assert check_result.verdict is CheckVerdict.ERROR
        assert "view provider failed" in check_result.reason

    def test_a_missing_deliverable_is_an_ERROR_verdict(self, monkeypatch, tmp_path):
        _compose(monkeypatch)
        result = runner.evaluate_gate(DISTINCT_GATE, _ctx(tmp_path / "absent.csv"))
        (check_result,) = result.check_results
        assert check_result.verdict is CheckVerdict.ERROR


HEALTH_CORE = REPO_ROOT / "execute_tools" / "health_checks"
PETS_IDENTIFIERS = (
    "pets",
    "oxford",
    "categorical_labels",
    DISTINCT_GATE,
    DOMINANT_GATE,
)


class TestPackIdentifierCensus:
    """Nothing Pets-specific leaks into generic health core (C7-08b pattern)."""

    @staticmethod
    def _module_code_text(path: Path) -> str:
        """Identifiers + non-docstring strings, lowercased, joined."""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    docstrings.add(id(body[0].value))
        parts: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                parts.append(node.id)
            elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                parts.append(node.name)
            elif isinstance(node, ast.Attribute):
                parts.append(node.attr)
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                parts.append(node.value)
        return "\n".join(parts).lower()

    def test_the_scan_sees_real_code(self):
        """Anti-vacuity: the collector finds a known identifier."""
        text = self._module_code_text(HEALTH_CORE / "registry.py")
        assert "register_view_provider" in text

    def test_no_pets_identifier_in_generic_health_core(self):
        offenders: list[str] = []
        for module in sorted(HEALTH_CORE.glob("*.py")):
            text = self._module_code_text(module)
            for identifier in PETS_IDENTIFIERS:
                if identifier.lower() in text:
                    offenders.append(f"{module.name}: {identifier}")
        assert offenders == []

    def test_no_cardinality_37_literal_in_generic_health_core(self):
        """The alphabet size is task data, injected — never a core constant."""
        offenders: list[str] = []
        for module in sorted(HEALTH_CORE.glob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == 37:
                    offenders.append(module.name)
        assert offenders == []
