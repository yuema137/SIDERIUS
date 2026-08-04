"""The gate harness delegates; it does not become a second implementation.

V20 PR C2.

`bg_admission_validation.py` states the risk in its own words: *"a
validation that replaces the thing it is validating proves only that the
replacement works."* A harness that grew its own sampler, its own
classifier, or a hand-built requirement would produce green gate artifacts
about code nobody runs.

So these tests are structural as well as behavioural: they assert that the
harness calls the SAME production functions the tuner calls, and that it
defines none of their logic itself.
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path
from typing import Any

import pytest

import scripts.c2_prephase_validation as harness

REPO_ROOT = Path(__file__).resolve().parents[3]
HARNESS = REPO_ROOT / "scripts" / "c2_prephase_validation.py"
TUNER = REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "ml_hyperparameter_tune_agent.py"

#: The production boundary. The tuner calls these; so must the harness.
BOUNDARY_CALLS = {
    "run_prephase_measurement",
    "decide_prephase_admission",
    "attach_measured_requirements",
}


def _calls(path: Path) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


class TestItDrivesTheProductionBoundary:
    def test_it_calls_every_boundary_function_the_tuner_calls(self):
        """Bypassing any one of them would test a path production does not
        take -- and the gate would certify it."""
        assert BOUNDARY_CALLS <= _calls(HARNESS)

    def test_the_tuner_calls_the_same_three(self):
        """Pins the claim above to the tuner rather than to this file's
        idea of what production does. If the tuner's boundary changes, this
        fails and the harness must follow."""
        assert BOUNDARY_CALLS <= _calls(TUNER)

    def test_it_uses_the_production_identity_builder(self):
        """A hand-built planned identity would hash a different key set,
        and every measurement would be refused for an identity mismatch
        that was the harness's fault."""
        assert "build_planned_identity" in _calls(HARNESS)


class TestItImplementsNoneOfWhatItValidates:
    @pytest.mark.parametrize(
        "forbidden",
        [
            "measure_window",
            "classify_measurement",
            "evaluate_gpu_admission",
            "MeasuredGpuRequirement",
            "MeasuredRequirementTable",
            "run_measured_phases",
        ],
        ids=[
            "window-reduction",
            "classifier",
            "pr-b-gate",
            "requirement",
            "delivery-table",
            "phase-runner",
        ],
    )
    def test_it_never_constructs_the_thing_under_test(self, forbidden):
        """Each of these would let the harness manufacture a result instead
        of observing one. `decide_prephase_admission` reaches all of them
        internally, which is the point: they must be reached THROUGH the
        production boundary, not beside it."""
        assert forbidden not in _calls(HARNESS)

    def test_the_production_sampler_is_used_only_for_the_formal_arms(self):
        """The formal arms have no production runner to sample them -- the
        prephase runner owns its own poll loop, and `execute_training`
        blocks. So the harness drives the PRODUCTION `GpuTreeSampler`
        directly there, and nowhere else.

        This is reuse, not reimplementation: the ownership rule, the
        gap-is-not-a-zero rule and the window reduction all remain
        production's. The guardrail is narrowed, not dropped -- a second
        sampler of the harness's own would still fail below.
        """
        tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
        holders = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
            and any(
                isinstance(c, ast.Call)
                and isinstance(c.func, ast.Name)
                and c.func.id == "GpuTreeSampler"
                for c in ast.walk(node)
            )
        }
        assert holders <= {"BackgroundTreeSampler", "__init__"}, (
            f"the production sampler is constructed outside the formal-arm wrapper: {holders}"
        )

    def test_it_defines_no_sampler_of_its_own(self):
        """The reduction, the ownership split and the coverage rules must
        stay production's."""
        source = HARNESS.read_text(encoding="utf-8")
        for token in ("def measure_window", "def sample(", "def is_descendant_of"):
            assert token not in source, f"the harness reimplements {token!r}"

    def test_it_defines_no_functions_named_after_the_production_units(self):
        tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
        defined = {fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)}
        assert not defined & {
            "run_prephase_measurement",
            "decide_prephase_admission",
            "classify_measurement",
            "measure_window",
        }

    def test_it_makes_no_llm_call(self):
        source = HARNESS.read_text(encoding="utf-8")
        for token in ("LLMBridge", "llm_bridge", "openai", "anthropic", "genai"):
            assert token not in source


class TestTheCaseMatrixIsHonest:
    def test_the_perturbation_cases_need_a_formal_comparison_arm(self):
        """They compare the probe against a bounded PRODUCTION formal
        execution. Running a plain measurement under a perturbation label
        would report a perturbation case that measured no perturbation."""
        assert harness.FORMAL_COMPARISON_CASES == {"c12a", "c12b"}
        assert harness.BLOCKED_CASES == {}, "both are now runnable"

    def test_the_formal_parameters_are_required_and_never_defaulted(self, capsys):
        """A shorter formal run peaks lower, so a default here would decide
        the answer the case exists to measure."""
        with pytest.raises(SystemExit):
            harness.parse_args([*_argv_for("c12a")])
        err = capsys.readouterr().err
        for flag in ("--formal_eval_portion", "--formal_train_portion", "--formal_seed"):
            assert flag in err
        assert "would decide the answer" in err

    def test_a_complete_formal_argument_set_parses(self):
        args = harness.parse_args(
            [
                *_argv_for("c12a"),
                "--formal_eval_portion",
                "0.01",
                "--formal_train_portion",
                "0.01",
                "--formal_seed",
                "20260803",
            ]
        )
        assert args.case == "c12a"
        assert args.formal_seed == 20260803

    #: The Lite-A packet's own Case 12 command, in the form it is documented.
    _BOUND_SELECTION = (
        "--formal_train_files",
        "8",
        "--formal_train_psd_per_file",
        "3",
        "--formal_eval_files",
        "8",
        "--formal_eval_psd_per_file",
        "2",
    )
    _BOUND_FORM = (*_BOUND_SELECTION, "--formal_seed", "137")

    def test_the_explicit_integer_bound_is_a_complete_selection(self):
        """REGRESSION. The check demanded the PORTIONS unconditionally, so
        the explicit-integer bound added beside them was unusable: the
        committed Lite-A packet's own c12 command would have been rejected
        by argparse before any GPU work, and the failure would have surfaced
        only at Gate time.

        A selection may be stated either way. Both are complete.
        """
        args = harness.parse_args([*_argv_for("c12a"), *self._BOUND_FORM])
        assert args.formal_train_portion is None
        assert (args.formal_train_files, args.formal_train_psd_per_file) == (8, 3)
        assert (args.formal_eval_files, args.formal_eval_psd_per_file) == (8, 2)

    def test_the_training_ceiling_outlasts_the_max_step_backstop(self):
        """The derivation, at the level that resolves it.

        `test_c2_documentation_sync` checks the DOCUMENTED triple; this
        checks that the harness's own arithmetic agrees, so a change to
        `_MODEL_SEGMENTS_PER_PSD` cannot leave the two consistent with each
        other and wrong about the data.

        If the ceiling were lower, the arm would end in data exhaustion --
        INCONCLUSIVE for a reason unrelated to the peak -- and the backstop
        that exists to bound the run would never bound it.
        """
        args = harness.parse_args([*_argv_for("c12a"), *self._BOUND_FORM])
        bound = harness.describe_workload_bound(args)
        assert bound["training_steps_per_epoch"] == 6000
        assert bound["training_steps_per_epoch"] >= args.formal_max_steps
        assert args.formal_train_psd_per_file == math.ceil(
            args.formal_max_steps / (args.formal_train_files * harness._MODEL_SEGMENTS_PER_PSD)
        ), "the ceiling is no longer the smallest integer the backstop requires"

    def test_half_a_bound_is_not_a_selection(self, capsys):
        """A file count without a per-file segment count does not determine
        a workload, and must not silently fall back to a portion."""
        with pytest.raises(SystemExit):
            harness.parse_args(
                [
                    *_argv_for("c12a"),
                    "--formal_train_files",
                    "8",
                    "--formal_eval_portion",
                    "0.01",
                    "--formal_seed",
                    "137",
                ]
            )
        assert "TRAINING selection" in capsys.readouterr().err

    def test_the_seed_is_required_under_either_form(self, capsys):
        """A complete bound still does not fix the SUBSAMPLE it selects."""
        with pytest.raises(SystemExit):
            harness.parse_args([*_argv_for("c12a"), *self._BOUND_SELECTION])
        assert "--formal_seed" in capsys.readouterr().err

    def test_the_live_stability_defaults_are_the_operator_decision(self):
        """The margin travels between machines because it counts real work;
        the backstops do not and are set per Gate."""
        args = harness.parse_args([*_argv_for("c12a"), *self._BOUND_FORM])
        assert args.formal_stable_steps == 500
        assert args.formal_min_samples == 3
        assert args.formal_max_steps == 5000
        assert args.formal_max_phase_seconds is None, (
            "a wall-clock cap must be chosen per machine, never inherited as a default"
        )

    def test_the_other_cases_do_not_require_them(self):
        assert harness.parse_args(_ARGV).formal_seed is None

    def test_the_test_evidence_cases_name_real_tests(self):
        """Cases 13-16 cite exact-head tests instead of GPU runs. A citation
        pointing at a test that does not exist would be worse than a missing
        case."""
        for case, node_id in harness.TEST_EVIDENCE_CASES.items():
            path = REPO_ROOT / node_id.split("::")[0]
            assert path.exists(), f"{case} cites a missing file: {path}"
            body = path.read_text(encoding="utf-8")
            for part in node_id.split("::")[1:]:
                assert part in body, f"{case} cites a missing test: {part}"

    def test_every_real_case_has_a_description(self):
        assert all(v.strip() for v in harness.REAL_CASES.values())

    def test_synthetic_cases_are_declared(self):
        """Injection is legitimate for crash and unavailable-telemetry, and
        it must be labelled: an injected failure is not evidence about a
        candidate."""
        assert harness.SYNTHETIC_CASES <= set(harness.REAL_CASES)


class TestTheOperatorSurfaceCarriesNoHiddenDefaults:
    @pytest.mark.parametrize(
        "flag",
        [
            "--device_uuid",
            "--data_dir",
            "--ceiling_gib",
            "--model_type",
            "--deadline_seconds",
            "--sampling_interval_seconds",
        ],
    )
    def test_gate_relevant_values_are_required(self, flag, capsys):
        """A code default would let a gate run against something other than
        what was approved, and the manifest would still look correct."""
        with pytest.raises(SystemExit):
            harness.parse_args(["--case", "c1"])
        assert flag in capsys.readouterr().err

    def test_a_full_argument_set_parses(self):
        args = harness.parse_args(_ARGV)
        assert args.case == "c1"
        assert args.dry_run is False

    def test_dry_run_is_opt_in(self):
        assert harness.parse_args([*_ARGV, "--dry_run"]).dry_run is True


_ARGV = [
    "--case",
    "c1",
    "--device_uuid",
    "GPU-test",
    "--model_type",
    "punet",
    "--model_config",
    "{}",
    "--train_config",
    "{}",
    "--loss_config",
    "{}",
    "--data_dir",
    "/tmp",
    "--workspace",
    "/tmp/ws",
    "--artifact_dir",
    "/tmp/art",
    "--ceiling_gib",
    "24",
    "--deadline_seconds",
    "600",
    "--sampling_interval_seconds",
    "0.25",
    "--training_steps",
    "4",
    "--inference_batches",
    "3",
    "--gate_attempt",
    "9",
]


class TestDryRunIsNotEvidence:
    def test_it_says_so_in_the_manifest(self, tmp_path):
        argv = _replace_paths(_ARGV, tmp_path)
        assert harness.main([*argv, "--dry_run"]) == 0
        manifest = json.loads(_only_manifest(tmp_path).read_text())
        assert manifest["gate_evidence"] is False
        assert manifest["dry_run"]["gate_evidence"] is False

    def test_it_launches_no_worker(self, tmp_path, monkeypatch):
        import core.runtime_control.gpu_measurement_runner as runner

        def forbidden(*_a, **_k):
            raise AssertionError("--dry_run launched the measurement worker")

        monkeypatch.setattr(runner, "run_prephase_measurement", forbidden)
        assert harness.main([*_replace_paths(_ARGV, tmp_path), "--dry_run"]) == 0

    def test_it_records_the_exact_sha_and_tree_state(self, tmp_path):
        harness.main([*_replace_paths(_ARGV, tmp_path), "--dry_run"])
        manifest = json.loads(_only_manifest(tmp_path).read_text())
        assert len(manifest["git"]["sha"]) == 40
        assert isinstance(manifest["git"]["dirty"], bool)

    def test_it_hashes_its_own_manifest(self, tmp_path):
        harness.main([*_replace_paths(_ARGV, tmp_path), "--dry_run"])
        digest = _only_manifest(tmp_path).with_suffix(".sha256").read_text()
        assert len(digest) == 64


class TestTheLiveRegistryIsNeverTouched:
    def test_the_calibration_dir_is_redirected_into_the_workspace(self, tmp_path, monkeypatch):
        """One env var governs BOTH the legacy v1 table and the v2 registry
        root, a coupling that already caught a C1 validation run out."""
        monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", "/should/be/replaced")
        harness.main([*_replace_paths(_ARGV, tmp_path), "--dry_run"])
        import os

        assert os.environ["SIDERIUS_CALIBRATION_DIR"].startswith(str(tmp_path))

    def test_the_manifest_proves_the_live_tree_is_unchanged(self, tmp_path):
        """The fingerprint must survive a machine with NO live registry.

        This test reached straight for `["sha256"]`, which
        `live_registry_fingerprint` records only when the root exists. It
        passed on a dev box with `~/.siderius` present and raised `KeyError`
        on a CI runner without it -- an environment assumption, not a
        production defect: recording `present: False` and omitting the
        digest is the honest answer, and the H100 Lite-B manifests show
        exactly that shape (`/root/.siderius`, `present: False`).

        So the assertion now covers both worlds, and the absent branch still
        carries a real claim: a missing tree must never fabricate a hash.
        """
        harness.main([*_replace_paths(_ARGV, tmp_path), "--dry_run"])
        manifest = json.loads(_only_manifest(tmp_path).read_text())
        before = manifest["live_registry_before"]
        after = manifest["live_registry_after"]
        assert manifest["live_registry_unchanged"] is True
        assert before == after, "the live calibration tree changed during the run"
        if before.get("present"):
            # Present: "unchanged" must be backed by a real digest, not by
            # two absent trees trivially agreeing.
            assert before["sha256"] == after["sha256"]
            assert len(before["sha256"]) == 64
        else:
            assert "sha256" not in before, "an absent tree must not carry a digest"


def _only_manifest(tmp_path) -> Path:
    """The single manifest this invocation wrote. Names now carry attempt,
    SHA, case and sub-attempt, so they are no longer predictable by hand --
    which is the point."""
    found = sorted((tmp_path / "art").glob("*.json"))
    assert len(found) == 1, f"expected one manifest, found {found}"
    return found[0]


def _replace_paths(argv: list[str], tmp_path) -> list[str]:
    out = list(argv)
    out[out.index("--workspace") + 1] = str(tmp_path / "ws")
    out[out.index("--artifact_dir") + 1] = str(tmp_path / "art")
    return out


def _argv_for(case: str) -> list[str]:
    out = list(_ARGV)
    out[out.index("--case") + 1] = case
    return out


class TestTheFormalControlPathIsProductionAndHarnessOnly:
    """Case 12a needs a formal execution with NO preceding probe. There is
    deliberately no production flag for that, so the control arm lives here
    -- and must stay here."""

    def test_it_runs_BOTH_formal_phases(self):
        """12b compares the probe's INFERENCE peak against a formal
        inference peak. Running only training would answer half the
        question and look complete."""
        source = HARNESS.read_text(encoding="utf-8")
        assert "sandbox.execute_training(" in source
        assert "sandbox.execute_inference(" in source

    def test_the_slice_is_not_reduced_twice(self):
        """`train_portion=1.0` inside execute_training: the operator's slice
        is applied when the sample set is built, and a second per-epoch
        reduction would make the formal run smaller than approved and
        quietly favour the probe."""
        source = HARNESS.read_text(encoding="utf-8")
        assert "train_portion=1.0," in source

    def test_it_calls_the_production_formal_boundary(self):
        """`TidmadSandbox.execute_training` is exactly what
        `agent.skills.training_skill.wrapper.run_skill` calls. Anything else
        would compare the probe against a path production never takes."""
        source = HARNESS.read_text(encoding="utf-8")
        assert "sandbox.execute_training(" in source
        wrapper = (REPO_ROOT / "agent" / "skills" / "training_skill" / "wrapper.py").read_text()
        assert "execute_training(" in wrapper

    def test_it_builds_the_sample_set_with_the_production_builder(self):
        assert "build_sample_set" in _calls(HARNESS)

    def test_the_control_path_is_unreachable_from_production(self):
        """The no-probe arm must never become something production can
        take. Nothing outside the harness may reference it."""
        offenders = [
            path
            for path in (REPO_ROOT / "core").rglob("*.py")
            if "run_formal_comparison" in path.read_text(encoding="utf-8")
        ] + [
            path
            for path in (REPO_ROOT / "nodes").rglob("*.py")
            if "run_formal_comparison" in path.read_text(encoding="utf-8")
        ]
        assert offenders == []

    def test_no_correction_factor_is_ever_applied(self):
        """The repetitions establish the observed envelope; subtracting a
        probe overhead would erase the very quantity being measured."""
        source = HARNESS.read_text(encoding="utf-8")
        assert '"correction_factor_applied": False' in source
        for token in ("overhead_subtract", "correction_factor =", "* CORRECTION"):
            assert token not in source

    def test_the_three_pairs_alternate_order(self):
        """A warmed driver or a cached dataset page would otherwise
        masquerade as a perturbation."""
        source = HARNESS.read_text(encoding="utf-8")
        assert '("with_probe", "without_probe")' in source
        assert '("without_probe", "with_probe")' in source

    def test_the_environment_shift_and_the_verdict_are_recorded_separately(self):
        """D-C2-21. The single `contaminated` key is gone.

        It conflated "the surroundings moved" with "the pair cannot be
        compared", and that conflation refused all three of Lite-A attempt
        20's pairs while every arm measured an identical 1476 MiB. Two
        facts, two keys, and the artifact carries both.
        """
        source = HARNESS.read_text(encoding="utf-8")
        assert '"contaminated"' not in source, (
            "the conflated key is back; a shift may be observed while the pair "
            "remains perfectly comparable"
        )
        assert '"environment_shift_observed"' in source
        assert '"pair_comparable"' in source
        assert "visible_gpu_processes" in _calls(HARNESS)

    def test_the_adapter_builds_an_arm_from_a_REAL_formal_record(self):
        """THE test that was missing, and the defect it now catches.

        `summarize_formal_arm` read `formal["realized_identity"]` and
        `stability["candidate_id"]`. Neither key exists on a formal-arm
        record. Every LIVE pair was therefore refused for "no identity"
        while the replay passed, because the replay hand-fed the identity --
        two constructions of one mapping, drifting exactly as the function's
        own docstring warns.

        The fixture is a real attempt-21 arm, kept whole.
        """
        fixture = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "c2_lite_a21_formal_arm_record.json").read_text(
                encoding="utf-8"
            )
        )
        summaries = [
            harness.summarize_formal_arm(arm, fixture["arms"][arm]) for arm in fixture["order"]
        ]
        for s in summaries:
            assert s.identity is not None, (
                f"{s.arm}: the adapter found no realized identity in a real record"
            )
            assert "punet" in s.identity, s.identity
            assert s.candidate_peak_mib == 1476
            assert s.admission_result == "admitted"
            assert s.sampling_complete is True
            assert s.attribution_complete is True
        assert summaries[0].identity == summaries[1].identity, (
            "both arms ran the same candidate and must agree on identity"
        )

    def test_a_real_pair_is_comparable_end_to_end(self):
        """The live path, from artifact to verdict, with nothing hand-fed."""
        from core.runtime_control.environment_stability import assess_pair_comparability

        fixture = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "c2_lite_a21_formal_arm_record.json").read_text(
                encoding="utf-8"
            )
        )
        a, b = (harness.summarize_formal_arm(x, fixture["arms"][x]) for x in fixture["order"])
        r = assess_pair_comparability(a, b, case="c12a")
        assert r.pair_comparable is True, list(r.blocking_reasons)

    def test_the_identity_is_realized_not_rebuilt_from_arguments(self):
        """MUTATION TARGET: sourcing identity from `args`.

        Both arms receive identical arguments by construction, so a check
        against them could never fail -- it would be decoration. The
        identity must come from what each training subprocess actually
        built.
        """
        source = HARNESS.read_text(encoding="utf-8")
        fn = source[
            source.index("def summarize_formal_arm") : source.index("def run_formal_comparison")
        ]
        assert "calibration_context" in fn
        assert "args." not in fn, "the adapter reaches for arguments instead of realized data"

    def test_each_arm_is_summarized_before_the_pair_is_judged(self):
        """MUTATION TARGET: pooling both arms' samples again.

        One min/max across both arms cannot tell a wobble inside an arm from
        a shift between them.
        """
        called = _calls(HARNESS)
        assert "summarize_formal_arm" in called
        assert "assess_pair_comparability" in called

    def test_the_series_is_stored_machine_readably(self):
        """`environment_samples` held Pydantic objects that the manifest
        writer's `default=str` turned into repr strings — recorded, but no
        replay could re-derive the assessment from them."""
        source = HARNESS.read_text(encoding="utf-8")
        assert '"environment_samples"' not in source
        assert '"raw_samples": watcher.raw_samples' in source


class TestTheFormalArmRunsBothPhasesForReal:
    """Behavioural, not source-scanning. A call that exists and silently
    returns nothing passes a grep; these capture what was actually invoked
    and with which arguments."""

    @pytest.fixture
    def captured(self, monkeypatch, tmp_path):
        calls: dict[str, Any] = {"sample_sets": [], "training": None, "inference": None}

        class _Sandbox:
            def __init__(self, **kw):
                calls["sandbox_kwargs"] = kw

            def execute_training(self, **kw):
                calls["training"] = kw
                return {"status": "success"}

            def execute_inference(self, **kw):
                calls["inference"] = kw
                return {"status": "success"}

        def _build_sample_set(**kw):
            calls["sample_sets"].append(kw)
            return {"files": [0], "portion": kw.get("trial_portion")}

        import core.sandbox_executor as executor
        import execute_tools.sample_set_builder as builder

        monkeypatch.setattr(executor, "TidmadSandbox", _Sandbox)
        monkeypatch.setattr(builder, "build_sample_set", _build_sample_set)

        args = harness.parse_args(
            [
                *_replace_paths(_argv_for("c12a"), tmp_path),
                "--formal_train_portion",
                "0.01",
                "--formal_eval_portion",
                "0.02",
                "--formal_seed",
                "137",
            ]
        )
        result = harness.run_formal_execution(args, label="probe-test")
        return calls, result

    def test_both_production_phases_are_invoked(self, captured):
        calls, _ = captured
        assert calls["training"] is not None, "execute_training was never called"
        assert calls["inference"] is not None, "execute_inference was never called"

    def test_the_slice_is_applied_once_not_twice(self, captured):
        """The operator's 1% is applied when the sample set is built. A
        per-epoch `train_portion` below 1.0 would shrink the formal run a
        second time and quietly favour the probe."""
        calls, _ = captured
        assert calls["training"]["train_portion"] == 1.0

    def test_train_and_eval_slices_are_distinct_inputs(self, captured):
        """Deliberately 0.01 vs 0.02 here: equal values would pass even if
        one flag fed both sample sets."""
        calls, _ = captured
        portions = [s["trial_portion"] for s in calls["sample_sets"]]
        assert portions == [0.01, 0.02]

    def test_the_seed_reaches_both_sample_sets_and_training(self, captured):
        calls, _ = captured
        assert all(s["seed"] == 137 for s in calls["sample_sets"])
        assert calls["training"]["train_base_seed"] == 137

    def test_the_result_carries_both_phase_results(self, captured):
        _, result = captured
        assert result["training_status"]
        assert result["inference_status"]
        # Not merely present: each window must carry what only the
        # production sampler produces. A hand-built dict with the right
        # keys would pass a presence check and measure nothing.
        for key in ("training_memory", "inference_memory"):
            window = result[key]
            for field in (
                "driver_tree_peak_mib",
                "driver_source",
                "samples_taken",
                "sampling_complete",
                "max_gap_seconds",
                "own_pids",
            ):
                assert field in window, f"{key} lacks sampler output: {field}"
            assert window["driver_source"].startswith("gpu_accounting.sample")
        assert len(result["raw_samples"]) >= 1, (
            "the timestamped series must survive so a peak-versus-time curve "
            "can be reconstructed -- attempt 5 could not"
        )
        assert all("at" in s for s in result["raw_samples"])

    def test_an_arm_missing_inference_is_not_complete(self):
        """The completeness gate this exists for: a formal arm that ran only
        training must not be markable as done."""
        assert harness.formal_phases_complete({"training_status": {"status": "success"}}) is False

    def test_an_arm_missing_training_is_not_complete(self):
        assert harness.formal_phases_complete({"inference_status": {"status": "success"}}) is False


class TestTheManifestRecordsTheApprovedInputs:
    def test_the_portions_and_seed_are_recorded_exactly(self, tmp_path):
        argv = [
            *_replace_paths(_argv_for("c12a"), tmp_path),
            "--formal_train_portion",
            "0.01",
            "--formal_eval_portion",
            "0.01",
            "--formal_seed",
            "137",
            "--dry_run",
        ]
        assert harness.main(argv) == 0
        manifest = json.loads(_only_manifest(tmp_path).read_text())
        resolved = manifest["resolved_arguments"]
        assert resolved["formal_train_portion"] == 0.01
        assert resolved["formal_eval_portion"] == 0.01
        assert resolved["formal_seed"] == 137


class TestArtifactsAreImmutable:
    """Gate attempt 4's first c3 induction was invalid -- the PATH still
    reached `/usr/bin/nvidia-smi`, so nothing was injected -- and the
    corrected rerun OVERWROTE it. That artifact is unrecoverable. The record
    of a mistake is often the most useful part of a Gate."""

    def test_a_second_run_of_the_same_case_never_replaces_the_first(self, tmp_path):
        argv = [*_replace_paths(_ARGV, tmp_path), "--dry_run"]
        harness.main(argv)
        harness.main(argv)
        found = sorted((tmp_path / "art").glob("*.json"))
        assert len(found) == 2, "the second run must create a NEW artifact"
        assert {p.name for p in found} == {
            found[0].name,
            found[1].name,
        }, "and the two must be distinguishable"

    def test_the_identity_carries_attempt_sha_and_case(self, tmp_path):
        harness.main([*_replace_paths(_ARGV, tmp_path), "--dry_run"])
        name = _only_manifest(tmp_path).name
        assert name.startswith("c2_lite_a9_"), "gate attempt"
        assert "_c1__sub1" in name, "case and sub-attempt"

    def test_each_artifact_records_its_own_path(self, tmp_path):
        harness.main([*_replace_paths(_ARGV, tmp_path), "--dry_run"])
        manifest = json.loads(_only_manifest(tmp_path).read_text())
        assert manifest["artifact_path"].endswith("__sub1.json")

    def test_the_gate_attempt_is_required(self, capsys):
        argv = [a for a in _ARGV if a not in ("--gate_attempt", "9")]
        with pytest.raises(SystemExit):
            harness.parse_args(argv)
        assert "--gate_attempt" in capsys.readouterr().err


class TestSyntheticInjectionProvenance:
    def test_a_shim_is_recorded_and_hashed(self, tmp_path):
        """A synthetic result is only interpretable alongside what was
        injected -- and an injection can silently fail to happen at all,
        producing an ordinary measurement under a fault label."""
        shim = tmp_path / "nvidia-smi"
        shim.write_text("#!/bin/sh\nexit 1\n")
        shim.chmod(0o755)
        argv = _replace_paths(_argv_for("c3"), tmp_path)
        harness.main([*argv, "--injection_shim", str(shim), "--dry_run"])
        prov = harness.injection_provenance(
            harness.parse_args([*argv, "--injection_shim", str(shim)])
        )
        assert prov["shim_path"] == str(shim)
        assert len(prov["shim_sha256"]) == 64
        assert prov["shim_executable"] is True
        assert "exit 1" in prov["shim_content"]

    def test_a_non_synthetic_case_records_none(self):
        assert harness.injection_provenance(harness.parse_args(_ARGV)) is None


class TestTheCase12BudgetCheckpoint:
    def _pair(self, formal_a, formal_b, probe):
        arm = lambda f, p: {  # noqa: E731
            "formal": {
                "wall_seconds": f,
                "training_wall_seconds": f * 0.7,
                "inference_wall_seconds": f * 0.3,
            },
            "prephase": {"wall_seconds": p} if p is not None else None,
        }
        return {"arms": {"with_probe": arm(formal_a, probe), "without_probe": arm(formal_b, None)}}

    def _args(self, prior=0.0, budget=5400.0):
        return harness.parse_args(
            [
                *_argv_for("c12a"),
                "--formal_train_portion",
                "0.01",
                "--formal_eval_portion",
                "0.01",
                "--formal_seed",
                "137",
                "--prior_cases_wall_seconds",
                str(prior),
                "--max_total_wall_seconds",
                str(budget),
            ]
        )

    def test_t_formal_is_the_slower_arm_not_the_mean(self):
        """An optimistic projection would authorise a run that overruns,
        which is what the checkpoint exists to prevent."""
        p = harness.project_case12_wall(self._args(), self._pair(100.0, 200.0, 10.0))
        assert p["t_formal_seconds"] == 200.0
        assert p["projected_case12_wall_seconds"] == 6 * 200.0 + 3 * 10.0

    def test_it_continues_inside_the_budget(self):
        p = harness.project_case12_wall(self._args(prior=180.0), self._pair(60.0, 60.0, 5.0))
        assert p["continue"] is True

    def test_it_stops_past_the_budget(self):
        p = harness.project_case12_wall(
            self._args(prior=180.0, budget=600.0), self._pair(300.0, 300.0, 20.0)
        )
        assert p["continue"] is False
        assert "nothing is shrunk" in p["decision"]

    def test_the_prior_case_time_is_included(self):
        cheap = harness.project_case12_wall(self._args(prior=0.0), self._pair(10.0, 10.0, 1.0))
        costly = harness.project_case12_wall(self._args(prior=5000.0), self._pair(10.0, 10.0, 1.0))
        assert (
            cheap["projected_total_lite_a_wall_seconds"]
            < (costly["projected_total_lite_a_wall_seconds"])
        )

    def test_the_calculation_inputs_are_all_recorded(self):
        p = harness.project_case12_wall(self._args(), self._pair(100.0, 200.0, 10.0))
        for key in (
            "t_formal_seconds",
            "t_probe_seconds",
            "formal_arm_wall_seconds",
            "formal_training_wall_seconds",
            "formal_inference_wall_seconds",
            "formula",
            "budget_seconds",
            "decision",
        ):
            assert key in p


class TestTheCheckpointActuallyControlsExecution:
    """The projection is only a safeguard if it stops the loop. Computing it
    correctly and then running all three pairs anyway is the failure this
    checkpoint was approved to prevent."""

    @pytest.fixture
    def stubbed(self, monkeypatch):
        """Cheap arms: what is under test is the control flow, not the
        training."""
        monkeypatch.setattr(
            harness, "run_case_measurement", lambda args, label: {"wall_seconds": 1.0}
        )
        monkeypatch.setattr(
            harness,
            "run_formal_execution",
            lambda args, label: {
                "wall_seconds": 100.0,
                "training_wall_seconds": 70.0,
                "inference_wall_seconds": 30.0,
                "training_status": {"status": "success"},
                "inference_status": {"status": "success"},
                "training_memory": {
                    "started_at": 1.0,
                    "ended_at": 2.0,
                    "driver_tree_peak_mib": 1474,
                    "sampling_complete": True,
                },
                "inference_memory": {
                    "started_at": 3.0,
                    "ended_at": 4.0,
                    "driver_tree_peak_mib": 1050,
                    "sampling_complete": True,
                },
            },
        )
        monkeypatch.setattr(harness, "visible_gpu_processes", list)

    def _args(self, budget):
        return harness.parse_args(
            [
                *_argv_for("c12a"),
                "--formal_train_portion",
                "0.01",
                "--formal_eval_portion",
                "0.01",
                "--formal_seed",
                "137",
                "--max_total_wall_seconds",
                str(budget),
            ]
        )

    def test_it_stops_after_pair_one_past_the_budget(self, stubbed):
        result = harness.run_formal_comparison(self._args(budget=60.0))
        assert result["pairs_completed"] == 1
        assert result["pairs_planned"] == 3
        assert result["gate_status"] == "STOPPED_BY_TIME_BOUND"
        assert result["projection"]["continue"] is False

    def test_it_runs_all_three_inside_the_budget(self, stubbed):
        """Positive control: the checkpoint must stop overruns, not every
        run."""
        result = harness.run_formal_comparison(self._args(budget=100_000.0))
        assert result["pairs_completed"] == 3
        assert result["gate_status"] is None
        assert result["projection"]["continue"] is True

    def test_stopping_is_not_a_failure(self, stubbed):
        """`STOPPED_BY_TIME_BOUND` is a budget decision. Reporting it as a
        failure would push toward shrinking the workload to make it pass."""
        result = harness.run_formal_comparison(self._args(budget=60.0))
        assert result["gate_status"] != "INCONCLUSIVE"
        assert result["pairs"][0]["formal_phases_complete"] is True

    def test_the_projection_is_recorded_with_its_inputs(self, stubbed):
        result = harness.run_formal_comparison(self._args(budget=60.0))
        p = result["projection"]
        assert p["t_formal_seconds"] == 100.0
        assert p["projected_case12_wall_seconds"] == 6 * 100.0 + 3 * 1.0


class TestProvenanceReachesTheManifest:
    def test_a_synthetic_case_records_how_it_was_induced(self, tmp_path):
        """Attempt 4 proved an injection can silently fail to happen,
        yielding an ordinary measurement under a fault label. The manifest
        must say what was injected."""
        shim = tmp_path / "nvidia-smi"
        shim.write_text("#!/bin/sh\nexit 1\n")
        shim.chmod(0o755)
        argv = _replace_paths(_argv_for("c6"), tmp_path)
        harness.main([*argv, "--injection_shim", str(shim), "--dry_run"])
        # dry-run writes no result; drive the recorded path directly.
        args = harness.parse_args([*argv, "--injection_shim", str(shim)])
        prov = harness.injection_provenance(args)
        assert prov is not None
        assert prov["harness_command"] is not None, "c6 injects a worker command"
        assert len(prov["shim_sha256"]) == 64


class TestFormalArmsAreMeasuredNotJustRun:
    """Attempt 5's pair 1 reported `formal_phases_complete: true` after 886 s
    of GPU work that recorded NO formal peak at all -- so Case 12B, which
    compares probe peaks against formal peaks, could not have been answered
    by it. "It ran" and "we measured it" are different claims."""

    def _formal(self, **over):
        base = {
            "training_status": {"status": "success"},
            "inference_status": {"status": "success"},
            "training_memory": {
                "started_at": 1.0,
                "ended_at": 2.0,
                "driver_tree_peak_mib": 1474,
                "sampling_complete": True,
            },
            "inference_memory": {
                "started_at": 3.0,
                "ended_at": 4.0,
                "driver_tree_peak_mib": 1050,
                "sampling_complete": True,
            },
        }
        base.update(over)
        return base

    def test_a_fully_measured_arm_is_complete(self):
        assert harness.formal_phases_complete(self._formal()) is True

    def test_training_without_memory_is_not_complete(self):
        assert harness.formal_phases_complete(self._formal(training_memory=None)) is False

    def test_inference_without_memory_is_not_complete(self):
        assert harness.formal_phases_complete(self._formal(inference_memory=None)) is False

    @pytest.mark.parametrize("phase", ["training_memory", "inference_memory"])
    def test_a_missing_peak_is_not_complete(self, phase):
        window = dict(self._formal()[phase], driver_tree_peak_mib=None)
        assert harness.formal_phases_complete(self._formal(**{phase: window})) is False

    @pytest.mark.parametrize("phase", ["training_memory", "inference_memory"])
    def test_incomplete_sampling_is_not_complete(self, phase):
        window = dict(self._formal()[phase], sampling_complete=False)
        assert harness.formal_phases_complete(self._formal(**{phase: window})) is False

    @pytest.mark.parametrize("phase", ["training_memory", "inference_memory"])
    def test_missing_phase_boundaries_are_not_complete(self, phase):
        window = dict(self._formal()[phase], started_at=None)
        assert harness.formal_phases_complete(self._formal(**{phase: window})) is False

    def test_the_status_only_condition_is_gone(self):
        """The exact regression: statuses present, nothing measured."""
        status_only = {
            "training_status": {"status": "success"},
            "inference_status": {"status": "success"},
        }
        assert harness.formal_phases_complete(status_only) is False

    def test_the_two_phases_are_recorded_separately(self):
        """A cumulative peak over training + inference would answer neither
        phase's question."""
        formal = self._formal()
        assert (
            formal["training_memory"]["driver_tree_peak_mib"]
            != (formal["inference_memory"]["driver_tree_peak_mib"])
        )


class TestEveryResultShapeRenders:
    """A manifest written before a traceback is not a clean Gate execution."""

    def _target(self, tmp_path):
        return tmp_path / "m.json"

    def test_a_measurement_result_renders(self, tmp_path):
        out = harness.render_summary(
            "c1",
            {
                "requirement": {"outcome": "COMPLETED_MEASUREMENT"},
                "disposition": "PROCEED",
                "authoritative": True,
            },
            self._target(tmp_path),
        )
        assert "COMPLETED_MEASUREMENT" in out and "PROCEED" in out

    def test_a_comparison_result_renders(self, tmp_path):
        """The exact attempt-5 crash: `KeyError: 'requirement'` after 30
        minutes of GPU work."""
        out = harness.render_summary(
            "c12a",
            {
                "comparison": {
                    "gate_status": "STOPPED_BY_TIME_BOUND",
                    "pairs_completed": 1,
                    "pairs_planned": 3,
                    "formal_phases_complete": True,
                    "projection": {
                        "projected_total_lite_a_wall_seconds": 5523.1,
                        "budget_seconds": 5400.0,
                    },
                }
            },
            self._target(tmp_path),
        )
        assert "STOPPED_BY_TIME_BOUND" in out and "1/3" in out

    def test_a_blocked_result_renders(self, tmp_path):
        out = harness.render_summary(
            "c12a",
            {"status": "BLOCKED_PENDING_OPERATOR_INPUT", "reason": "needs input"},
            self._target(tmp_path),
        )
        assert "BLOCKED" in out

    def test_an_unrecognised_shape_says_so_instead_of_raising(self, tmp_path):
        out = harness.render_summary("cX", {"unexpected": True}, self._target(tmp_path))
        assert "NO RESULT SHAPE RECOGNISED" in out

    @pytest.mark.parametrize(
        "result",
        [
            {"requirement": {"outcome": "X"}, "disposition": "PROCEED", "authoritative": True},
            {"comparison": {"pairs_completed": 3, "pairs_planned": 3, "projection": {}}},
            {"status": "BLOCKED_PENDING_OPERATOR_INPUT", "reason": "r"},
            {},
        ],
    )
    def test_no_shape_raises(self, tmp_path, result):
        assert isinstance(harness.render_summary("c", result, self._target(tmp_path)), str)


class TestTheSingleArmCharacterization:
    """Attempt 5 preserved no formal peak, so the saturation question cannot
    be answered from anything on disk. This mode produces the missing curve
    at the cost of ONE arm rather than a full pair -- the no-probe arm
    answers the perturbation question, not this one."""

    def test_it_is_never_a_gate_pass(self):
        assert "c12char" in harness.SINGLE_ARM_CASES
        assert "c12char" not in harness.FORMAL_COMPARISON_CASES

    def test_it_requires_the_same_formal_parameters(self, capsys):
        with pytest.raises(SystemExit):
            harness.parse_args(_argv_for("c12char"))
        assert "--formal_train_portion" in capsys.readouterr().err

    def test_it_runs_one_arm_not_a_pair(self, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(
            harness,
            "run_case_measurement",
            lambda args, label: calls.append(f"probe:{label}") or {"wall_seconds": 3.0},
        )
        monkeypatch.setattr(
            harness,
            "run_formal_execution",
            lambda args, label: (
                calls.append(f"formal:{label}")
                or {
                    "raw_samples": [],
                    "training_memory": {"started_at": 0.0, "ended_at": 1.0},
                    "inference_memory": {"started_at": 2.0, "ended_at": 3.0},
                }
            ),
        )
        args = harness.parse_args(
            [
                *_argv_for("c12char"),
                "--formal_train_portion",
                "0.01",
                "--formal_eval_portion",
                "0.01",
                "--formal_seed",
                "137",
            ]
        )
        result = harness.run_single_arm_characterization(args)
        assert calls == ["probe:char_probe", "formal:char_formal"], (
            "exactly one probe and one formal arm"
        )
        assert result["gate_pass"] is False


class TestPeakSaturationAnalysis:
    def _samples(self, series):
        return [{"at": at, "telemetry_available": True, "own_tree_mib": mib} for at, mib in series]

    def test_it_finds_when_the_peak_stopped_rising(self):
        """The load-bearing number: everything after this is a stable tail
        that a shorter workload could omit."""
        s = self._samples([(0.0, 500), (1.0, 1200), (2.0, 1474), (5.0, 1474), (9.0, 1474)])
        out = harness.peak_saturation(s, 0.0, 10.0)
        assert out["final_peak_mib"] == 1474
        assert out["last_cumulative_increase_s"] == 2.0
        assert out["stable_tail_s"] == 8.0
        assert out["stable_tail_fraction"] == 0.8

    def test_a_late_peak_is_not_hidden(self):
        """The finding that would FORBID shortening: if the peak rises near
        the end, the tail is not stable and the run cannot be cut."""
        s = self._samples([(0.0, 500), (1.0, 1200), (9.5, 3000)])
        out = harness.peak_saturation(s, 0.0, 10.0)
        assert out["final_peak_mib"] == 3000
        assert out["last_cumulative_increase_s"] == 9.5
        assert out["stable_tail_fraction"] == 0.05

    def test_samples_outside_the_phase_are_ignored(self):
        """A training sample must not set the inference peak."""
        s = self._samples([(0.0, 9999), (5.0, 1000), (15.0, 8888)])
        out = harness.peak_saturation(s, 4.0, 6.0)
        assert out["final_peak_mib"] == 1000

    def test_unmeasured_samples_are_excluded(self):
        s = [
            {"at": 1.0, "telemetry_available": False, "own_tree_mib": None},
            {"at": 2.0, "telemetry_available": True, "own_tree_mib": 700},
        ]
        out = harness.peak_saturation(s, 0.0, 3.0)
        assert out["samples_in_phase"] == 1
        assert out["final_peak_mib"] == 700

    def test_no_samples_reports_unobserved_rather_than_zero(self):
        out = harness.peak_saturation([], 0.0, 10.0)
        assert out["observed"] is False
        assert "final_peak_mib" not in out

    def test_the_curve_records_only_increases(self):
        """A monotone cumulative curve is what makes 'when did it stop
        rising' answerable at a glance."""
        s = self._samples([(0.0, 100), (1.0, 90), (2.0, 300), (3.0, 250)])
        curve = harness.peak_saturation(s, 0.0, 4.0)["cumulative_peak_curve"]
        assert [c["cumulative_peak_mib"] for c in curve] == [100, 300]
