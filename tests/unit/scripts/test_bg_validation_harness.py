"""The B-G validation harness, tested without a GPU, an LLM, or a holder.

A harness that can only be checked by running it is a harness whose
first real use is also its first test. These are all CPU/synthetic: they
assert the guards that decide whether a real run may start at all, and
the ones that decide whether its result means anything.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import bg_admission_validation as bg  # noqa: E402
from scripts import bg_gpu_holder as holder  # noqa: E402


def code_only(path: Path) -> str:
    """The module's code with every docstring removed.

    Scanning raw source would make prose indistinguishable from
    behaviour: a docstring that says "never monkeypatch this" would fail
    a guard forbidding the word. These guards are about what the code
    does, so they read the code.
    """
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


HOLDER_SRC = REPO_ROOT / "scripts" / "bg_gpu_holder.py"
BG_SRC = REPO_ROOT / "scripts" / "bg_admission_validation.py"
UUID = "GPU-aaaa-0000"
PARAMS = {"model_type": "punet", "phase": "training", "source": "A5"}


class TestImportIsInert:
    """Importing must not touch a GPU, an LLM, or allocate anything.

    Otherwise collecting the test suite would itself be a side effect,
    and CI has no GPU.
    """

    def test_neither_script_imports_torch_at_module_scope(self):
        for src in (HOLDER_SRC, BG_SRC):
            tree = ast.parse(src.read_text())
            top = {
                a.name.split(".")[0]
                for node in tree.body
                if isinstance(node, ast.Import)
                for a in node.names
            } | {
                node.module.split(".")[0]
                for node in tree.body
                if isinstance(node, ast.ImportFrom) and node.module
            }
            assert "torch" not in top, f"{src.name} imports torch at module scope"

    # A `"torch" not in sys.modules` test used to sit here, neutered to
    # `or True` because another test may legitimately have imported torch
    # first. An assertion that cannot fail is not coverage — the
    # module-scope check above is the real and sufficient guard.

    def test_neither_script_is_reachable_from_the_launcher(self):
        """A validation-only path must not be callable by a real run."""
        for name in ("bg_admission_validation", "bg_gpu_holder"):
            hits = subprocess.run(
                ["grep", "-rl", name, str(REPO_ROOT / "scripts" / "run_chain.sh")],
                capture_output=True,
                text=True,
            )
            assert hits.returncode != 0, f"{name} is referenced by run_chain.sh"


class TestHolderBounds:
    """The holder must refuse configurations that could not conclude."""

    @staticmethod
    def _args(**kw):
        base = dict(
            device_uuid=UUID,
            target_mib=5_200,
            min_valid_mib=4_668,
            max_mib=8_000,
            max_lifetime_s=600,
            evidence_dir="/tmp/x",
        )
        base.update(kw)
        return argparse.Namespace(**base)

    def test_the_default_window_is_valid(self):
        assert holder.validate_bounds(self._args()) is None

    def test_a_target_below_the_conclusive_floor_is_refused(self):
        """training 1,476 + holder must exceed 6,144, so a holder under
        4,668 cannot produce a verdict — the holder says so rather than
        running and leaving the caller to notice."""
        problem = holder.validate_bounds(self._args(target_mib=4_000))
        assert problem is not None
        assert "must lie within" in problem

    def test_a_target_above_the_maximum_is_refused(self):
        assert holder.validate_bounds(self._args(target_mib=9_000)) is not None

    def test_an_inverted_window_is_refused(self):
        assert holder.validate_bounds(self._args(min_valid_mib=9_000)) is not None

    @pytest.mark.parametrize("lifetime", [0, -1, 601, 10_000])
    def test_lifetime_is_bounded(self, lifetime):
        assert holder.validate_bounds(self._args(max_lifetime_s=lifetime)) is not None

    def test_the_floor_is_derived_from_the_training_measurement(self):
        """B-G2b must refuse before the TRAINING child starts, so the
        floor comes from the training figure — 1,476 measured on this
        UUID — not from inference's 2,716 and not from A5's 3,076."""
        training = bg.FIXTURE_REQUIREMENTS_MIB["training"]
        assert training + holder.DEFAULT_MIN_VALID_MIB == 6_144
        assert int(bg.VALIDATION_CEILING_GIB * 1024) == 6_144

    def test_the_target_actually_exceeds_the_ceiling(self):
        training = bg.FIXTURE_REQUIREMENTS_MIB["training"]
        assert training + holder.DEFAULT_TARGET_MIB > 6_144

    def test_worst_case_occupancy_stays_far_from_quota(self):
        """If the gate failed entirely, occupancy must still be modest —
        the reason the validation ceiling is 6 GiB rather than 28."""
        worst = max(bg.FIXTURE_REQUIREMENTS_MIB.values()) + holder.DEFAULT_MAX_MIB
        assert worst < 12_000


class TestHolderMeasurement:
    """Occupancy is read from the driver, never inferred."""

    def test_it_reports_the_drivers_figure_for_this_pid_and_uuid(self):
        csv = f"111, 4321, {UUID}\n222, 9999, GPU-other\n"
        with patch.object(
            holder.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, csv, "")
        ):
            assert holder.measured_mib(UUID, 111) == 4321

    def test_a_different_uuid_is_not_counted(self):
        csv = "111, 4321, GPU-other\n"
        with patch.object(
            holder.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, csv, "")
        ):
            assert holder.measured_mib(UUID, 111) is None

    def test_an_unqueryable_driver_is_none_not_zero(self):
        """None means unknown. Zero would read as "holding nothing"."""
        with patch.object(holder.subprocess, "run", side_effect=OSError("no nvidia-smi")):
            assert holder.measured_mib(UUID, 111) is None

    def test_the_uuid_is_resolved_to_an_index_rather_than_assumed(self):
        csv = "0, GPU-other\n1, " + UUID + "\n"
        with patch.object(
            holder.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, csv, "")
        ):
            assert holder.resolve_visible_index(UUID) == 1

    def test_an_absent_uuid_resolves_to_none(self):
        with patch.object(
            holder.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, "0, GPU-other\n", ""),
        ):
            assert holder.resolve_visible_index(UUID) is None

    def test_it_never_defaults_to_device_zero(self):
        src = code_only(HOLDER_SRC)
        assert "'0'" not in src.split("CUDA_VISIBLE_DEVICES")[1][:40]
        assert "resolve_visible_index" in src


class TestFixtureApplicability:
    """A shared model name is not applicability."""

    @staticmethod
    def _fixture(**over):
        f = {
            "validation_only": True,
            "device_uuid": UUID,
            "model_type": "punet",
            "config_sha256": "a" * 64,
            "config": {"model_config": {}, "train_config": {}, "loss_config": {}},
            "phases": {
                "training": {
                    "requirement_mib": 1_476,
                    "provenance": "measured",
                    "measurement_type": "driver_visible_peak",
                },
                "inference": {
                    "requirement_mib": 2_716,
                    "provenance": "measured",
                    "measurement_type": "driver_visible_peak",
                },
            },
        }
        f.update(over)
        return f

    def test_an_exact_match_passes(self):
        assert bg.fixture_mismatch(self._fixture(), device_uuid=UUID, model_type="punet") is None

    def test_a_different_gpu_uuid_is_a_mismatch(self):
        problem = bg.fixture_mismatch(
            self._fixture(), device_uuid="GPU-bbbb-1111", model_type="punet"
        )
        assert problem is not None and "measured on" in problem

    def test_a_different_model_is_a_mismatch(self):
        assert (
            bg.fixture_mismatch(self._fixture(), device_uuid=UUID, model_type="wavenet") is not None
        )

    def test_a_fixture_missing_a_phase_is_a_mismatch(self):
        f = self._fixture(phases={"training": {"requirement_mib": 1_476}})
        problem = bg.fixture_mismatch(f, device_uuid=UUID, model_type="punet")
        assert problem is not None and "BOTH phases" in problem

    def test_a_predicted_measurement_type_is_a_mismatch(self):
        """An estimate must not enter as an authoritative measurement."""
        f = self._fixture()
        f["phases"]["inference"]["measurement_type"] = "predicted_allocated"
        problem = bg.fixture_mismatch(f, device_uuid=UUID, model_type="punet")
        assert problem is not None and "driver-visible" in problem

    def test_the_fixture_carries_a_separate_figure_per_phase(self):
        f = self._fixture()
        assert (
            f["phases"]["training"]["requirement_mib"]
            != f["phases"]["inference"]["requirement_mib"]
        )

    def test_a_fixture_not_marked_validation_only_is_refused(self, tmp_path):
        """The harness must never consume a record claiming production
        authority — that would make a test input look promoted."""
        bad = self._fixture()
        bad.pop("validation_only")
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(bad))
        with pytest.raises(SystemExit, match="validation_only"):
            bg.load_fixture(str(path))

    def test_a_fixture_missing_required_fields_is_refused(self, tmp_path):
        path = tmp_path / "partial.json"
        path.write_text(json.dumps({"validation_only": True, "device_uuid": UUID}))
        with pytest.raises(SystemExit, match="missing required fields"):
            bg.load_fixture(str(path))

    def test_the_real_bg0_fixture_loads_and_matches(self):
        """The artifact B-G0 actually produced, not a rebuilt copy."""
        path = Path("/home/klz/Data/SIDEREIS_DATA/bg0_evidence_20260802/bg0_fixture.json")
        if not path.exists():
            pytest.skip("B-G0 evidence not present on this host")
        f = bg.load_fixture(str(path))
        assert f["phases"]["training"]["requirement_mib"] == 1_476
        assert f["phases"]["inference"]["requirement_mib"] == 2_716
        assert bg.fixture_mismatch(f, device_uuid=f["device_uuid"], model_type="punet") is None


#: B-G0's real three groups, trimmed to the keys the comparison needs.
#: Rebuilt per use where mutated, so no test can corrupt another.
_FIXTURE_CONFIG: dict[str, dict] = {
    "model_config": {"model_type": "punet", "segmentation_size": 40000, "depth": 4},
    "train_config": {"lr": 0.0003, "epochs": 1, "optimizer_type": "adamw"},
    "loss_config": {"loss_type": "focal", "alpha": 0.5},
}


def _phase_params(phase: str) -> dict:
    """The kwargs the executor would receive for `phase`.

    Keyed by the executor's own parameter names — the wrapper renames
    `model_config` -> `m_cfg` before the sandbox ever sees it, which is
    precisely what the first B-G1 missed.
    """
    names = {"model_config": "m_cfg", "train_config": "t_cfg", "loss_config": "l_cfg"}
    groups = bg.PHASE_GROUPS[phase].values()
    return {names[g]: dict(_FIXTURE_CONFIG[g]) for g in groups}


class TestConfigPrecondition:
    """The first B-G1 read model_config/train_config/loss_config, which
    `execute_training` does not take. It got None for all three and
    hashed the same all-None digest every time — a guard that refused
    everything, as worthless as one that accepts everything and harder
    to notice because it looks strict."""

    def test_every_name_it_reads_is_a_real_executor_parameter(self):
        """The join the first B-G1 lacked.

        Pinned to the production signature itself, not to a literal — a
        rename of `m_cfg` that missed `PHASE_GROUPS` fails here rather
        than at the next GPU run.
        """
        import inspect

        from core.sandbox_executor import TidmadSandbox

        for phase, method in (
            ("training", TidmadSandbox.execute_training),
            ("inference", TidmadSandbox.execute_inference),
        ):
            takes = set(inspect.signature(method).parameters)
            assert set(bg.PHASE_GROUPS[phase]) <= takes, (
                f"{phase} reads names {method.__name__} does not accept"
            )

    def test_inference_is_not_asked_for_a_train_config_it_never_receives(self):
        """`execute_inference` has no `t_cfg`, so requiring one would
        refuse every inference phase for a reason that cannot be true."""
        import inspect

        from core.sandbox_executor import TidmadSandbox

        assert "t_cfg" not in set(inspect.signature(TidmadSandbox.execute_inference).parameters)
        assert "t_cfg" not in bg.PHASE_GROUPS["inference"]
        # Behavioural: inference params carrying no t_cfg must realize.
        realized = bg.realize_phase_config("inference", _phase_params("inference"))
        assert set(realized) == {"model_config", "loss_config"}

    def test_training_compares_all_three_groups(self):
        realized = bg.realize_phase_config("training", _phase_params("training"))
        assert set(realized) == {"model_config", "train_config", "loss_config"}

    def test_a_missing_group_raises_instead_of_hashing(self):
        """The first B-G1's exact defect, driven for real: reading a name
        the executor does not pass must abort, not produce a digest."""
        wrong_names = {"model_config": {"a": 1}, "train_config": {}, "loss_config": {}}
        with pytest.raises(bg.HarnessError) as exc:
            bg.realize_phase_config("training", wrong_names)
        assert "model_config" in str(exc.value)

    def test_the_all_none_digest_is_unreachable(self):
        """`43d64649bd9c9f99` was hashed three times by the broken guard.
        No input may produce it now — absence raises first."""
        for params in ({}, {"m_cfg": {"a": 1}}, {"m_cfg": {"a": 1}, "t_cfg": {"b": 2}}):
            with pytest.raises(bg.HarnessError):
                bg.compare_phase_config("training", params, {"model_config": {"a": 1}})

    def test_an_empty_group_is_compared_not_declared_missing(self):
        """`{}` was supplied; `None` was not. Conflating them reports a
        real config difference as a harness bug."""
        params = {"m_cfg": {"a": 1}, "t_cfg": {}, "l_cfg": {}}
        realized = bg.realize_phase_config("training", params)
        assert realized["train_config"] == {}
        with pytest.raises(bg.ConfigMismatch) as exc:
            bg.compare_phase_config("training", params, _FIXTURE_CONFIG)
        assert "train_config" in str(exc.value)

    def test_an_unknown_phase_is_a_harness_error(self):
        with pytest.raises(bg.HarnessError):
            bg.realize_phase_config("scoring", _phase_params("training"))

    def test_a_matching_config_passes_and_records_the_realized_groups(self):
        record = bg.compare_phase_config(
            "training", _phase_params("training"), dict(_FIXTURE_CONFIG)
        )
        assert record["phase"] == "training"
        assert record["config"] == _FIXTURE_CONFIG
        assert record["config_sha256"] == bg.config_hash(_FIXTURE_CONFIG)

    def test_a_differing_group_is_named_in_the_mismatch(self):
        params = _phase_params("training")
        params["t_cfg"] = {**_FIXTURE_CONFIG["train_config"], "lr": 0.9}
        with pytest.raises(bg.ConfigMismatch) as exc:
            bg.compare_phase_config("training", params, _FIXTURE_CONFIG)
        assert exc.value.phase == "training"
        assert exc.value.expected == "train_config"
        assert exc.value.realized["config"]["train_config"]["lr"] == 0.9

    def test_an_inference_mismatch_never_blames_the_train_config(self):
        """The evidence writer's phantom-diff bug: inference receives no
        train config, so it can never be the group that differs."""
        params = _phase_params("inference")
        params["l_cfg"] = {"loss_type": "mse"}
        with pytest.raises(bg.ConfigMismatch) as exc:
            bg.compare_phase_config("inference", params, _FIXTURE_CONFIG)
        assert exc.value.expected == "loss_config"
        assert "train_config" not in exc.value.realized["config"]

    def test_no_fixture_means_nothing_to_compare_against(self):
        """B-G2a supplies no fixture; the precondition must not invent a
        mismatch, because admission is what should refuse there."""
        for empty in (None, {}):
            record = bg.compare_phase_config("training", _phase_params("training"), empty)
            assert record["config"] == _FIXTURE_CONFIG

    def test_the_real_fixture_config_reproduces_its_own_hash(self):
        """End-to-end on the artifact B-G0 produced: the three groups,
        read under the executor's parameter names, must hash to the
        fixture's recorded digest."""
        path = Path("/home/klz/Data/SIDEREIS_DATA/bg0_evidence_20260802/bg0_fixture.json")
        if not path.exists():
            pytest.skip("B-G0 evidence not present on this host")
        f = bg.load_fixture(str(path))
        cfg = f["config"]
        digest = hashlib.sha256(
            json.dumps(
                {
                    "model_config": cfg["model_config"],
                    "train_config": cfg["train_config"],
                    "loss_config": cfg["loss_config"],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        assert digest == f["config_sha256"]

    def test_the_evidence_diff_covers_only_this_phases_groups(self):
        """A fixed three-group loop invents a `train_config` difference on
        every inference mismatch, because `realized` has no such key while
        the fixture does — evidence contradicting the phase-correctness
        the same check exists to prove."""
        realized = bg.realize_phase_config("inference", _phase_params("inference"))
        realized["loss_config"] = {"loss_type": "mse"}
        diff = bg.phase_config_diff("inference", _FIXTURE_CONFIG, realized)
        assert set(diff) == {"loss_config"}
        assert "train_config" not in diff

    def test_the_evidence_diff_reports_a_real_training_difference(self):
        realized = bg.realize_phase_config("training", _phase_params("training"))
        realized["train_config"] = {"lr": 0.9}
        diff = bg.phase_config_diff("training", _FIXTURE_CONFIG, realized)
        assert set(diff) == {"train_config"}
        assert diff["train_config"]["expected"] == _FIXTURE_CONFIG["train_config"]
        assert diff["train_config"]["realized"] == {"lr": 0.9}

    def test_a_mismatch_is_not_a_retryable_training_error(self):
        """`status="error"` was retried three times into max_fail_rounds.
        A mismatch is not a candidate failure, so it must be uncatchable
        by the tuner's `except Exception`."""
        assert issubclass(bg.ConfigMismatch, BaseException)
        assert not issubclass(bg.ConfigMismatch, Exception)
        assert issubclass(bg.HarnessError, BaseException)
        assert not issubclass(bg.HarnessError, Exception)

    def test_a_mismatch_carries_the_realized_config_not_just_a_hash(self):
        m = bg.ConfigMismatch("training", "a" * 64, "b" * 64, {"config": {"model_config": {}}})
        assert m.realized["config"] == {"model_config": {}}
        assert m.phase == "training"


class TestScenarioWiring:
    def test_only_bg0_runs_trial(self):
        """B-G0 must be trial: in formal with no fixture the gate
        correctly refuses, so a formal B-G0 would refuse itself and never
        collect the measurement it exists for.

        Every other scenario must be formal, so a missing or
        inapplicable fixture cannot pass vacuously.
        """
        assert bg.SCENARIO_MODE["bg0"] == "trial"
        assert {bg.SCENARIO_MODE[s] for s in ("bg1", "bg2a", "bg2b")} == {"formal"}

    def test_the_mode_reaches_the_sandbox(self):
        assert callable(bg.make_sandbox_factory(None, mode="trial"))
        src = ast.unparse(
            next(
                n
                for n in ast.walk(ast.parse(BG_SRC.read_text()))
                if isinstance(n, ast.FunctionDef) and n.name == "make_sandbox_factory"
            )
        )
        assert "admission_mode = mode" in src

    def test_the_fixtureless_scenarios_are_bg0_and_bg2a(self):
        assert bg.SCENARIOS == ("bg0", "bg1", "bg2a", "bg2b")
        src = code_only(BG_SRC)
        assert "{'bg0', 'bg2a'}" in src or '{"bg0", "bg2a"}' in src

    def test_the_factory_builds_a_real_sandbox_not_a_stub(self):
        src = code_only(BG_SRC)
        assert "TidmadSandbox" in src
        assert "StubSandbox" not in src

    def test_the_validation_subclass_adds_only_the_config_precondition(self):
        """It may override the two phase entries, and only to assert the
        realized config before a GPU child exists — every path delegates
        to `super()`. Anything else would make the harness validate its
        own variant of the executor rather than production.
        """
        tree = ast.parse(BG_SRC.read_text())
        cls = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef) and n.name == "_ValidationSandbox"
        )
        assert [b.id for b in cls.bases if isinstance(b, ast.Name)] == ["TidmadSandbox"]
        methods = sorted(n.name for n in cls.body if isinstance(n, ast.FunctionDef))
        assert methods == ["_config_precondition", "execute_inference", "execute_training"]
        for name in ("execute_training", "execute_inference"):
            fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
            calls = {
                n.func.attr
                for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            }
            assert name in calls, f"{name} must delegate to super().{name}"

    def test_the_hash_check_precedes_the_production_phase(self):
        """The precondition must run before `super()`, or it would be
        reporting on a phase that already started."""
        src = ast.unparse(
            next(
                n
                for n in ast.walk(ast.parse(BG_SRC.read_text()))
                if isinstance(n, ast.FunctionDef) and n.name == "execute_training"
            )
        )
        assert src.index("_config_precondition") < src.index("super()")

    def test_the_admission_fields_are_not_added_to_production(self):
        """Declaring them on TidmadSandbox itself is B-G3's job; doing it
        from a validation harness would create the validation-only
        production entry point B-G3 exists to avoid."""
        executor = (REPO_ROOT / "core" / "sandbox_executor.py").read_text()
        cls = next(
            n
            for n in ast.walk(ast.parse(executor))
            if isinstance(n, ast.ClassDef) and n.name == "TidmadSandbox"
        )
        declared = {
            n.target.id
            for n in cls.body
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
        }
        assert "admission_mode" not in declared
        assert "measured_requirements" not in declared

    def test_nothing_is_monkeypatched(self):
        """A validation that replaces what it validates proves only that
        the replacement works."""
        src = code_only(BG_SRC)
        for forbidden in ("monkeypatch", "unittest.mock", "MagicMock", "patch("):
            assert forbidden not in src, forbidden

    def test_no_registry_or_promotion(self):
        src = code_only(BG_SRC).lower()
        for forbidden in ("registry", "promote"):
            assert forbidden not in src, forbidden

    def test_the_validation_ceiling_is_applied_through_the_existing_override(self):
        """No production default is edited."""
        src = code_only(BG_SRC)
        assert "SIDERIUS_PAIR_VRAM_CEILING_GIB" in src
        assert "DEFAULT_PAIR_CEILING_GIB" not in src

    def test_the_ceiling_is_labelled_validation_only(self):
        assert bg.VALIDATION_CEILING_GIB == 6.0
        assert "validation-only" in BG_SRC.read_text().lower()


class TestPreflightRefusesToStart:
    @staticmethod
    def _args(scenario="bg1"):
        return argparse.Namespace(scenario=scenario, device_uuid=UUID)

    def test_an_existing_candidate_child_blocks_the_run(self):
        with (
            patch.object(
                bg, "candidate_gpu_children", return_value=["123 train_engine_sandbox.py"]
            ),
            patch.object(bg, "compute_apps", return_value=[]),
        ):
            verdict, ev = bg.preflight(self._args())
        assert verdict == "INCONCLUSIVE"
        assert "already running" in ev["reason"]

    def test_a_busy_gpu_blocks_bg1(self):
        with (
            patch.object(bg, "candidate_gpu_children", return_value=[]),
            patch.object(bg, "compute_apps", return_value=["999, 4000 MiB, GPU-x"]),
        ):
            verdict, _ = bg.preflight(self._args("bg1"))
        assert verdict == "INCONCLUSIVE"

    def test_bg2b_tolerates_the_holder_on_the_card(self):
        """The holder is legitimately present; a candidate child is not."""
        with (
            patch.object(bg, "candidate_gpu_children", return_value=[]),
            patch.object(bg, "compute_apps", return_value=["999, 4000 MiB, GPU-x"]),
        ):
            verdict, _ = bg.preflight(self._args("bg2b"))
        assert verdict == "OK"

    @pytest.mark.allow_real_subprocess
    def test_the_no_child_check_does_not_match_its_own_command_line(self):
        """A shell that merely mentions the script names must not count.

        Observed during the B-G0 dry run: `pgrep -af` matched the
        operator's own inspection command, which contained the pattern as
        an argument. In the no-child proof that would have produced a
        false FAIL — "a phase started", concluded from a grep hitting its
        own argument list.

        Marked `allow_real_subprocess` deliberately. The escape guard
        watches argv *content*, and this test must put the script name in
        a command line to reproduce the false positive at all — which is
        indistinguishable from a real launch to a guard that cannot read
        intent. What actually runs is `bash -c echo`; no training starts,
        and the assertion is that the checker ignores it.
        """
        import subprocess as sp

        proc = sp.Popen(
            ["bash", "-c", "echo train_engine_sandbox.py inference_single.py; sleep 5"],
            stdout=sp.DEVNULL,
        )
        try:
            assert bg.candidate_gpu_children() == []
        finally:
            proc.kill()
            proc.wait()

    def test_the_no_child_check_reads_proc_rather_than_grepping(self):
        src = code_only(BG_SRC)
        assert "/proc" in src
        assert "cmdline" in src
        assert "pgrep" not in src

    def test_the_no_child_check_targets_candidates_not_all_gpu_processes(self):
        src = code_only(BG_SRC)
        assert "train_engine_sandbox.py" in src
        assert "inference_single.py" in src


class TestNoRetryOrTuning:
    def test_the_harness_contains_no_retry_loop(self):
        tree = ast.parse(BG_SRC.read_text())
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef) and fn.name == "main":
                assert not any(isinstance(n, ast.While) for n in ast.walk(fn)), (
                    "main() must not loop — a failed scenario stops and reports"
                )

    def test_a_mismatch_returns_before_any_run(self):
        """The mismatch branch must precede agent construction, or the
        check would be reporting on a run that already happened."""
        src = code_only(BG_SRC)
        assert src.index("fixture mismatch") < src.index("HyperparamTuningAgent(")


class _WitnessSandbox:
    """Only the attributes the real gate reads."""

    def __init__(self, requirements, mode="formal"):
        from core.runtime_control.gpu_accounting import DeviceIdentity

        self.device_identity = DeviceIdentity(uuid="GPU-w-0", physical_index=0)
        self.run_name = "witness"
        self.admission_mode = mode
        self.measured_requirements = requirements


def _snapshot(used_mib):
    from core.runtime_control.gpu_accounting import DeviceIdentity, GpuAccountingSnapshot

    return GpuAccountingSnapshot(
        device=DeviceIdentity(uuid="GPU-w-0", physical_index=0),
        telemetry_available=True,
        device_total_mib=32_000,
        device_used_mib=used_mib,
        own_tree_mib=0,
        other_mib=used_mib,
        other_process_count=1 if used_mib else 0,
        per_pid_total_mib=used_mib,
        unattributed_mib=0,
        accounting_skew_mib=0,
    )


_REALIZED = {"phase": "training", "config": dict(_FIXTURE_CONFIG), "config_sha256": "deadbeef"}


class TestPhaseWitness:
    """The B-G1 rerun admitted and recorded nothing about it. Production
    logs only refusals, so "admitted" rested on the absence of a refusal
    — and a gate that never ran would look identical."""

    @staticmethod
    def _evidence(used_mib, requirements=None, mode="formal", realized=None):
        sandbox = _WitnessSandbox(
            requirements
            if requirements is not None
            else {"training": {"requirement_mib": 1476, "provenance": "measured"}},
            mode=mode,
        )
        with patch("core.runtime_control.gpu_accounting.sample", return_value=_snapshot(used_mib)):
            return bg.phase_evidence(sandbox, "training", realized or _REALIZED, _FIXTURE_CONFIG)

    def test_an_idle_card_is_recorded_as_admitted(self):
        ev = self._evidence(used_mib=0)
        assert ev["gate_evaluated"] is True
        assert ev["admission_result"] == "admitted"
        assert ev["reason_code"] is None

    def test_a_crowded_card_is_recorded_as_refused_with_its_reason(self):
        ev = self._evidence(used_mib=31_500)
        assert ev["admission_result"] == "refused"
        assert ev["reason_code"] == "insufficient_headroom"

    def test_the_witness_records_the_phase_requirement_it_used(self):
        ev = self._evidence(used_mib=0)
        assert ev["requirement_mib"] == 1476
        assert ev["requirement_provenance"] == "measured"

    def test_a_missing_requirement_is_recorded_as_a_policy_problem(self):
        ev = self._evidence(used_mib=0, requirements={})
        assert ev["admission_result"] == "refused"
        assert ev["reason_code"] == "policy_unavailable"
        assert ev["requirement_mib"] is None

    def test_the_success_path_records_expected_and_realized_both(self):
        ev = self._evidence(used_mib=0)
        assert ev["expected_config"] == _FIXTURE_CONFIG
        assert ev["realized_config"] == _FIXTURE_CONFIG
        assert ev["expected_config_sha256"] == bg.config_hash(_FIXTURE_CONFIG)
        assert ev["realized_config_sha256"] == "deadbeef"

    def test_a_matching_diff_is_empty_not_absent(self):
        """Absent and empty must not look alike: one means "compared and
        identical", the other means "never compared"."""
        ev = self._evidence(used_mib=0)
        assert "config_diff" in ev
        assert ev["config_diff"] == {}

    def test_a_differing_diff_names_the_group(self):
        realized = {
            "phase": "training",
            "config": {**_FIXTURE_CONFIG, "train_config": {"lr": 0.9}},
            "config_sha256": "beef",
        }
        ev = self._evidence(used_mib=0, realized=realized)
        assert set(ev["config_diff"]) == {"train_config"}

    def test_the_witness_calls_the_real_gate_not_a_copy(self):
        """If it reimplemented the decision, a production change would
        not move it. Patching the production symbol must change the
        recorded result."""
        import core.sandbox_executor as se

        with patch.object(se, "_admission_refusal", return_value=None) as gate:
            ev = self._evidence(used_mib=31_500)
        assert gate.call_count == 1
        assert ev["admission_result"] == "admitted"

    def test_the_witness_is_honest_about_what_it_witnessed(self):
        ev = self._evidence(used_mib=0)
        assert "not the production call's own return value" in ev["witness_note"]


class TestOneAdmissionAttemptPerScenario:
    """A B-G scenario is one deterministic admission decision.

    The first B-G2a consumed three attempt slots and three planning
    calls to re-derive the identical `policy_unavailable`, because the
    harness left `max_fail_rounds` at production's default of 3. A
    refusal is a statement about the machine; inside a scenario that
    holds the machine fixed, retrying cannot produce a different answer
    and only spends LLM budget.
    """

    def test_the_harness_asks_for_exactly_one_fail_round(self):
        src = code_only(BG_SRC)
        assert "max_fail_rounds=1" in src

    def test_it_also_asks_for_one_round_and_one_attempt(self):
        """All three bounds together are what make the scenario a single
        attempt; any one of them alone does not."""
        src = code_only(BG_SRC)
        assert "max_rounds=1" in src
        assert "attempts_per_formal_round=1" in src

    def test_the_production_default_is_untouched(self):
        """The whole point is that this is a per-run input. If the
        schema default moved, every campaign would inherit a validation
        convenience."""
        from agent.schemas.hyperparam_tuning import HyperparamTuningInput

        assert HyperparamTuningInput.model_fields["max_fail_rounds"].default == 3

    def test_the_field_accepts_one(self):
        """`ge=1`, so 1 is legal and 0 would be rejected — the harness
        cannot ask for "no attempts at all"."""
        from pydantic import ValidationError

        from agent.schemas.hyperparam_tuning import HyperparamTuningInput

        assert HyperparamTuningInput.model_fields["max_fail_rounds"].default == 3
        with pytest.raises(ValidationError):
            HyperparamTuningInput(
                model_type="punet", run_name="x", workspace="/tmp/x", max_fail_rounds=0
            )

    @staticmethod
    def _outcome(max_fail_rounds: int):
        """The real production decision, not a restatement of it."""
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            _compute_termination_state,
        )

        return _compute_termination_state(
            completed_rounds=0,
            max_rounds=1,
            consecutive_fails=1,
            max_fail_rounds=max_fail_rounds,
            gate_aborted=False,
        )

    def test_one_refusal_ends_the_run(self):
        """The behaviour the setting buys, driven through the real
        termination decision rather than asserted from the config."""
        assert self._outcome(1) == ("partial", "aborted_fail_rounds")

    def test_the_production_default_would_not_have_stopped(self):
        """Mutation proof in situ: at max_fail_rounds=3 — the value the
        first B-G2a ran under — one refusal does not trigger the abort,
        which is exactly why it retried twice more and spent three
        planning calls on one deterministic fact."""
        assert self._outcome(3) != ("partial", "aborted_fail_rounds")
