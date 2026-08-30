# tests/unit/examples/test_davis_health_family.py
"""Step 08c C4 — the DAVIS task-owned Health family, through the external interface.

Owns:

* the full state-C chain (shipped policy-only framework config + the
  pack's ``declared/task_health.yaml`` + the pack's plugin) with the
  FROZEN floor ``min_dispersion = 0.04``;
* the FULL-decoded-view semantics (§3.5): sorted clip keys → per-clip
  C-order ``ravel()`` → one concatenated stream, native float32
  preserved, no cap;
* the hand-computed synthetic evidence pair — near-constant FAILED,
  varied (√5) PASSED — plus the §2.9 near-collapse perturbation control;
* the §2.12 codec-parity regression: production writer bytes →
  ``davis_data_path`` reader AND → the pack provider projection agree on
  clip-key set, shapes, dtype and values;
* the skip-guarded machine-local real-npz evidence, reproducing the
  frozen §2.9 dispersion 0.2156402715035823 EXACTLY over 5,160,960
  samples (skips with a declared reason when the preserved artifact is
  absent — never claimed as run when skipped);
* provider error paths (missing / corrupt npz, unequal clip shapes →
  ERROR; NaN frames → FAILED; empty npz → ERROR at the check);
* the fail-closed plugin/binding pair and the DAVIS identifier census.
"""

from __future__ import annotations

import ast
import hashlib
import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from execute_tools.davis_data_path import (
    DavisClip,
    DavisTaskDataPath,
    clip_key,
)
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
from execute_tools.task_data_path import DeliverableWriteRequest, EvaluationReadRequest

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK = REPO_ROOT / "examples" / "davis_future_prediction"
TASK_HEALTH = PACK / "declared" / "task_health.yaml"
PLUGIN = PACK / "plugins" / "_davis_health_views.py"

DISPERSION_GATE = "davis_dispersion_blocking"
FROZEN_FLOOR = 0.04

# The preserved real artifact (child design §2.9) — machine-local, NOT in
# the repo (17.9 MB). The test over it is skip-guarded.
REAL_NPZ = Path(
    "/home/klz/Data/SIDEREIS_DATA/d14_davis_gate2_20260818c/"
    "predictions_davis_reference_predictor_d14d_davis_gate2_001.npz"
)
REAL_NPZ_SHA256 = "ee52a7109798a1c4c608e7824e623604e2986dab8d499b75a4794d443e0fa010"
REAL_N_SAMPLES = 5_160_960
FROZEN_DISPERSION = 0.2156402715035823

WRITE_IDENTITY = {
    "exp_id": "davis_health_001",
    "run_name": "t",
    "model_type": "davis_reference_predictor",
}
DELIVERABLE_NAME = "predictions_davis_reference_predictor_t_davis_health_001.npz"


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


def _ctx(
    deliverable: Path | None,
    *,
    identity: dict[str, str] = WRITE_IDENTITY,
) -> HealthCheckContext:
    kwargs = {"model_name": "davis_reference_predictor", "run_name": "t", "round_index": 1}
    if deliverable is not None:
        kwargs["denoised_paths"] = {0: str(deliverable)}
        kwargs["evaluation_payload_fn"] = lambda: DavisTaskDataPath().read_evaluation_payload(
            EvaluationReadRequest(deliverable_dir=str(deliverable.parent), **identity)
        )
    return HealthCheckContext(**kwargs)


def _compose(monkeypatch, task_health_path: Path = TASK_HEALTH):
    composed, task_config, plugins = load_composed_health_config(None, str(task_health_path))
    monkeypatch.setattr(runner, "load_health_gates_config", lambda *a, **k: composed)
    return composed, task_config, plugins


def _write_deliverable(tmp_path: Path, clips: dict[str, np.ndarray]) -> Path:
    """Through the PRODUCTION writer — the §2.12 'production writer bytes'."""
    outputs = [
        (DavisClip(sequence_name=key.split(":")[0], start_frame=int(key.split(":")[1])), arr)
        for key, arr in clips.items()
    ]
    DavisTaskDataPath().write_deliverable(
        outputs, DeliverableWriteRequest(output_dir=str(tmp_path), **WRITE_IDENTITY)
    )
    return tmp_path / DELIVERABLE_NAME


class TestStateCChain:
    def test_composition_resolves_the_pack_family(self, monkeypatch):
        composed, task_config, plugins = _compose(monkeypatch)

        assert [g.id for g in composed.health_gates] == [DISPERSION_GATE]
        (gate,) = composed.health_gates
        assert gate.gate_role == "blocking"
        assert gate.on_fail.action.value == "invalidate_round"
        assert gate.checks[0].name == "sample_dispersion_floor"
        assert gate.checks[0].config["min_dispersion"] == FROZEN_FLOOR
        # No cardinality axis declared by the check, none injected.
        assert "symbol_cardinality" not in gate.checks[0].config
        assert task_config is not None
        assert task_config.facts.encoding_family == "continuous_float"
        assert [p.configured_ref for p in plugins] == ["../plugins/_davis_health_views.py"]

    def test_the_int8_family_is_inapplicable_under_the_davis_declaration(self, monkeypatch):
        from execute_tools.health_checks.amplitude_collapse import AmplitudeCollapseCheck
        from execute_tools.health_checks.output_diversity import OutputDiversityCheck
        from execute_tools.health_checks.output_std import OutputStdCheck
        from execute_tools.health_checks.pearson_dispersion import PearsonDispersionCheck
        from execute_tools.health_checks.per_file_output_std import PerFileOutputStdCheck
        from execute_tools.health_checks.spectral_peak_ratio import SpectralPeakRatioCheck

        _, task_config, _ = _compose(monkeypatch)
        assert task_config is not None
        facts = task_config.resolved_facts()
        ctx = HealthCheckContext(
            model_name="davis_reference_predictor",
            run_name="t",
            round_index=1,
            denoised_paths={0: "/tmp/whatever.npz"},
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


class TestSyntheticEvidencePair:
    def test_a_constant_deliverable_fails_the_frozen_floor(self, monkeypatch, tmp_path):
        _compose(monkeypatch)
        constant = _write_deliverable(
            tmp_path, {"a:0": np.full((2, 2), 0.5), "b:0": np.full((2, 2), 0.5)}
        )
        result = runner.evaluate_gate(DISPERSION_GATE, _ctx(constant))
        (check_result,) = result.check_results
        assert check_result.verdict is CheckVerdict.FAILED
        assert check_result.metrics["dispersion"] == 0.0
        assert check_result.metrics["n_samples"] == 8
        assert result.action.value == "invalidate_round"

    def test_the_near_collapse_perturbation_control_fails(self, monkeypatch, tmp_path):
        """§2.9's acceptance control: constant plus a tiny perturbation
        (dispersion ≈ 10⁻³) fails the 0.04 floor by orders of magnitude."""
        _compose(monkeypatch)
        samples = np.full((2, 4), 0.5)
        samples[0, 0] = 0.508
        near = _write_deliverable(tmp_path, {"a:0": samples})
        result = runner.evaluate_gate(DISPERSION_GATE, _ctx(near))
        (check_result,) = result.check_results
        assert check_result.verdict is CheckVerdict.FAILED
        # mean 0.501; deviations 7×(-0.001), 1×0.007 → var 5.6e-5/8 = 7e-6.
        assert check_result.metrics["dispersion"] == pytest.approx(math.sqrt(7e-6), rel=1e-3)

    def test_a_varied_deliverable_passes_with_the_hand_computed_dispersion(
        self, monkeypatch, tmp_path
    ):
        _compose(monkeypatch)
        varied = _write_deliverable(
            tmp_path,
            {"a:0": np.array([[0.0, 2.0]]), "b:0": np.array([[4.0, 6.0]])},
        )
        result = runner.evaluate_gate(DISPERSION_GATE, _ctx(varied))
        (check_result,) = result.check_results
        assert check_result.verdict is CheckVerdict.PASSED
        # [0,2,4,6]: mean 3, squared deviations 9/1/1/9 → var 5 → std √5.
        assert check_result.metrics["dispersion"] == pytest.approx(math.sqrt(5.0))
        assert result.passed is True


class TestFullDecodedViewSemantics:
    @staticmethod
    def _provider():
        from execute_tools.health_checks.registry import get_view_provider

        return get_view_provider("davis.sample_views")

    def test_sorted_clip_keys_then_c_order_ravel(self, monkeypatch, tmp_path):
        _compose(monkeypatch)
        # Written out of order; "b:0" carries the LOW values. Sorted keys
        # put "a:0" first, and ravel is row-major.
        deliverable = _write_deliverable(
            tmp_path,
            {
                "b:0": np.array([[10.0, 11.0], [12.0, 13.0]]),
                "a:0": np.array([[0.0, 1.0], [2.0, 3.0]]),
            },
        )
        view = self._provider().materialize("continuous_samples", _ctx(deliverable))
        assert view.payload.samples.tolist() == [0, 1, 2, 3, 10, 11, 12, 13]

    def test_the_native_float32_dtype_is_preserved(self, monkeypatch, tmp_path):
        _compose(monkeypatch)
        deliverable = _write_deliverable(tmp_path, {"a:0": np.array([[0.25, 0.75]])})
        view = self._provider().materialize("continuous_samples", _ctx(deliverable))
        assert view.payload.samples.dtype == np.float32

    def test_the_view_is_the_full_stream_no_cap(self, monkeypatch, tmp_path):
        _compose(monkeypatch)
        clips = {f"c{i}:0": np.random.default_rng(i).random((3, 5)) for i in range(4)}
        deliverable = _write_deliverable(tmp_path, clips)
        view = self._provider().materialize("continuous_samples", _ctx(deliverable))
        assert view.payload.samples.size == 4 * 3 * 5


class TestCodecParity:
    """§2.12 — one deliverable format, two readers, zero drift."""

    def test_both_readers_agree_on_production_written_bytes(self, monkeypatch, tmp_path):
        _compose(monkeypatch)
        rng = np.random.default_rng(7)
        original = {
            "bear:0": rng.random((3, 4, 2, 2)),
            "bear:8": rng.random((3, 4, 2, 2)),
            "camel:0": rng.random((3, 4, 2, 2)),
        }
        deliverable = _write_deliverable(tmp_path, original)

        production = DavisTaskDataPath().read_evaluation_payload(
            EvaluationReadRequest(deliverable_dir=str(tmp_path), **WRITE_IDENTITY)
        )
        assert isinstance(production, dict)
        assert set(production) == set(original)
        for key, arr in production.items():
            assert arr.shape == (3, 4, 2, 2)
            assert arr.dtype == np.float32
            np.testing.assert_array_equal(arr, original[key].astype(np.float32))

        from execute_tools.health_checks.registry import get_view_provider

        view = get_view_provider("davis.sample_views").materialize(
            "continuous_samples", _ctx(deliverable)
        )
        expected = np.concatenate([production[key].ravel() for key in sorted(production)])
        np.testing.assert_array_equal(view.payload.samples, expected)
        assert view.payload.samples.dtype == expected.dtype == np.float32

    def test_clip_key_grammar_matches_the_production_authority(self):
        assert clip_key(DavisClip(sequence_name="bear", start_frame=8)) == "bear:8"


@pytest.mark.skipif(
    not REAL_NPZ.is_file(),
    reason=(
        "machine-local preserved DAVIS Gate-2 artifact not present "
        f"({REAL_NPZ}); the real-npz evidence runs only where the D14 "
        "corpus is preserved"
    ),
)
class TestRealPreservedArtifact:
    """The §2.9 measurement, reproduced from the preserved bytes."""

    def test_the_artifact_is_the_preserved_one(self):
        assert hashlib.sha256(REAL_NPZ.read_bytes()).hexdigest() == REAL_NPZ_SHA256

    def test_the_full_view_reproduces_the_frozen_dispersion_exactly(self, monkeypatch):
        _compose(monkeypatch)
        from execute_tools.health_checks.registry import get_view_provider

        view = get_view_provider("davis.sample_views").materialize(
            "continuous_samples",
            _ctx(
                REAL_NPZ,
                identity={
                    "exp_id": "davis_gate2_001",
                    "run_name": "d14d",
                    "model_type": "davis_reference_predictor",
                },
            ),
        )
        samples = view.payload.samples
        assert samples.size == REAL_N_SAMPLES
        assert samples.dtype == np.float32
        # The check-owned estimator (§3.5a), bit-equal to the frozen value.
        assert float(np.std(samples, dtype=np.float64, ddof=0)) == FROZEN_DISPERSION

    def test_the_gate_passes_the_preserved_artifact_at_the_frozen_floor(self, monkeypatch):
        _compose(monkeypatch)
        result = runner.evaluate_gate(
            DISPERSION_GATE,
            _ctx(
                REAL_NPZ,
                identity={
                    "exp_id": "davis_gate2_001",
                    "run_name": "d14d",
                    "model_type": "davis_reference_predictor",
                },
            ),
        )
        (check_result,) = result.check_results
        assert check_result.verdict is CheckVerdict.PASSED
        assert check_result.metrics["dispersion"] == FROZEN_DISPERSION
        assert check_result.metrics["n_samples"] == REAL_N_SAMPLES
        assert check_result.metrics["min_dispersion"] == FROZEN_FLOOR


class TestProviderErrorPaths:
    def test_a_missing_npz_is_an_ERROR_verdict(self, monkeypatch, tmp_path):
        _compose(monkeypatch)
        result = runner.evaluate_gate(DISPERSION_GATE, _ctx(tmp_path / "absent.npz"))
        (check_result,) = result.check_results
        assert check_result.verdict is CheckVerdict.ERROR
        assert check_result.metrics["n_samples"] == 0

    def test_a_corrupt_npz_is_an_ERROR_verdict(self, monkeypatch, tmp_path):
        _compose(monkeypatch)
        corrupt = tmp_path / DELIVERABLE_NAME
        corrupt.write_bytes(b"this is not an npz archive")
        result = runner.evaluate_gate(DISPERSION_GATE, _ctx(corrupt))
        (check_result,) = result.check_results
        assert check_result.verdict is CheckVerdict.ERROR

    def test_unequal_clip_shapes_are_an_ERROR_verdict(self, monkeypatch, tmp_path):
        _compose(monkeypatch)
        mixed = _write_deliverable(
            tmp_path,
            {"a:0": np.zeros((2, 2)), "b:0": np.zeros((3, 3))},
        )
        result = runner.evaluate_gate(DISPERSION_GATE, _ctx(mixed))
        (check_result,) = result.check_results
        assert check_result.verdict is CheckVerdict.ERROR
        assert "unequal" in check_result.reason

    def test_an_empty_npz_is_an_ERROR_at_the_check(self, monkeypatch, tmp_path):
        """Zero clips decode to an EMPTY stream: the provider read the
        artifact honestly, and the CHECK rules emptiness (§3.2a)."""
        _compose(monkeypatch)
        empty = tmp_path / DELIVERABLE_NAME
        np.savez_compressed(empty)
        result = runner.evaluate_gate(DISPERSION_GATE, _ctx(empty))
        (check_result,) = result.check_results
        assert check_result.verdict is CheckVerdict.ERROR
        assert check_result.metrics["n_samples"] == 0

    def test_nan_frames_are_FAILED(self, monkeypatch, tmp_path):
        _compose(monkeypatch)
        samples = np.full((2, 2), 0.5)
        samples[0, 0] = np.nan
        bad = _write_deliverable(tmp_path, {"a:0": samples})
        result = runner.evaluate_gate(DISPERSION_GATE, _ctx(bad))
        (check_result,) = result.check_results
        assert check_result.verdict is CheckVerdict.FAILED
        assert check_result.metrics["non_finite_samples"] == 1


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
        with pytest.raises(HealthPluginError, match="_davis_health_views"):
            load_composed_health_config(None, str(config_path))

    def test_a_roster_naming_an_unregistered_check_fails_closed(self, tmp_path):
        config_path = self._relocated_pack(tmp_path)
        text = config_path.read_text(encoding="utf-8").replace(
            "check: sample_dispersion_floor", "check: davis_nonexistent_check"
        )
        config_path.write_text(text, encoding="utf-8")
        with pytest.raises(HealthBindingError, match="davis_nonexistent_check"):
            load_composed_health_config(None, str(config_path))


HEALTH_CORE = REPO_ROOT / "execute_tools" / "health_checks"
DAVIS_IDENTIFIERS = ("davis", DISPERSION_GATE, "sample_views")


class TestPackIdentifierCensus:
    """Nothing DAVIS-specific leaks into generic health core."""

    @staticmethod
    def _module_code_text(path: Path) -> str:
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

    def test_no_davis_identifier_in_generic_health_core(self):
        offenders: list[str] = []
        for module in sorted(HEALTH_CORE.glob("*.py")):
            text = self._module_code_text(module)
            for identifier in DAVIS_IDENTIFIERS:
                if identifier.lower() in text:
                    offenders.append(f"{module.name}: {identifier}")
        assert offenders == []
