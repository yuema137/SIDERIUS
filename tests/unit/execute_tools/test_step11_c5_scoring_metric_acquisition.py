"""Step 11 C5 — the scoring child stops unconditionally deriving TIDMAD's metric.

The gap. ``denoising_score_single.py:195`` called
``derive_tidmad_metric(...)`` on every path. Step 06 chose that deliberately
— *"no spec or metric is serialized, no argv is added"* — because nothing
else crossed the boundary at the time. That choice is precisely what makes
the child TIDMAD-only, and **R-11-4** supersedes it for a COMPOSED run.

The audit that shaped the design, recorded because the design asked for it
first ("what does the scoring child actually consume from the metric?"):

* the metric is used at **exactly one** site, ``metric.evaluate(...)``;
* ``evaluate`` needs a real ``EvaluationMetric`` INSTANCE — the spec's
  ``id``/``direction``, its executable ``scoreability`` contract, and the
  implementation's ``_compute``;
* an instance is a ``MetricSpec`` (from a JSON declaration) **plus** an
  implementation class loaded from a symbol ref, and ``RunTaskComposition``
  retains neither, only the resolved instance;
* an instance cannot cross a process boundary.

So what crosses is the run's **manifest path**, and the child re-composes
the metric section through :func:`compose_metric_from_manifest` — a thin
public entry over the SAME ``_compose_metric`` authority the parent used.
Step 11 transports; it derives nothing.

What this module deliberately does NOT touch: metric semantics, direction
logic, scoring arithmetic, and secondary metrics (R-11-4 says not to
transport them speculatively — they are observational and have their own
Step-10 lifecycle).
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

from tests.helpers.composed_manifest import write_complete_manifest
from workflows.task_composition import (
    TaskCompositionError,
    active_task_manifest_path,
    bind_task_manifest_path,
    compose_metric_from_manifest,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
TIDMAD_MANIFEST = REPO_ROOT / "configs" / "task_composition" / "tidmad.yaml"
SCORING_CHILD = REPO_ROOT / "execute_tools" / "denoising_score_single.py"


# ----------------------------------------------------------------------
# Acquisition through the Step-10 authority
# ----------------------------------------------------------------------


class TestTheMetricComesFromTheDeclaration:
    def test_a_real_manifest_composes_its_declared_metric(self):
        from execute_tools.evaluation_metric import EvaluationMetric

        metric = compose_metric_from_manifest(str(TIDMAD_MANIFEST))
        assert isinstance(metric, EvaluationMetric)

    def test_the_composed_metric_matches_the_declaration_on_disk(self):
        """Not self-referential: the expectation is read from the DECLARATION
        FILE, which is the input, and compared against the composed
        instance's spec, which is the output.
        """
        declaration = json.loads(
            (REPO_ROOT / "examples/tidmad/resolved/metric_spec.json").read_text(encoding="utf-8")
        )
        metric = compose_metric_from_manifest(str(TIDMAD_MANIFEST))
        assert metric.spec.id == declaration["id"]
        assert metric.spec.direction == declaration["direction"]

    def test_it_composes_ONLY_the_metric(self):
        """A scoring child must not re-resolve the profile, the Health family
        or the interpretation blocks. Asserted structurally over the
        function's own body rather than by running it, because "did not
        happen" is what needs proving.
        """
        src = (REPO_ROOT / "workflows" / "task_composition.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "compose_metric_from_manifest"
        )
        called = {
            node.func.id
            for node in ast.walk(fn)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "_compose_metric" in called
        for forbidden in (
            "_compose_task_health",
            "_compose_dataset_profile",
            "_compose_task_config",
        ):
            assert forbidden not in called

    @pytest.mark.parametrize("bad", ["/nonexistent/manifest.yaml"])
    def test_an_unusable_manifest_refuses(self, bad):
        with pytest.raises((TaskCompositionError, FileNotFoundError, OSError)):
            compose_metric_from_manifest(bad)

    def test_a_manifest_without_a_metric_section_refuses(self, tmp_path):
        with pytest.raises(TaskCompositionError):
            compose_metric_from_manifest(str(write_complete_manifest(tmp_path, metric=None)))

    def test_a_declared_implementation_that_is_not_a_metric_refuses(self, tmp_path):
        """The fail-closed branch that matters most: a composed run must
        never end up with something that merely has an `evaluate`.

        Written against a COMPLETE manifest on purpose. A fragment would
        still raise — `_read_manifest` refuses a missing required section —
        so the test would pass while never reaching the implementation
        check it names. That is the "green for the wrong reason" shape this
        PR keeps finding.
        """
        declaration = str(REPO_ROOT / "examples/tidmad/resolved/metric_spec.json")
        # `str(spec)` constructs fine and is emphatically not a metric, so
        # this reaches the isinstance branch rather than stopping earlier.
        manifest = write_complete_manifest(
            tmp_path,
            metric={
                "declaration": declaration,
                "implementation": {"module": "builtins", "symbol": "str"},
            },
        )
        with pytest.raises(TaskCompositionError, match="not an EvaluationMetric"):
            compose_metric_from_manifest(str(manifest))

    def test_an_implementation_that_cannot_take_the_spec_refuses(self, tmp_path):
        """A different fail-closed branch of the same authority, pinned
        separately so a change to one cannot silently absorb the other.
        """
        declaration = str(REPO_ROOT / "examples/tidmad/resolved/metric_spec.json")
        manifest = write_complete_manifest(
            tmp_path,
            metric={
                "declaration": declaration,
                "implementation": {"module": "json", "symbol": "JSONDecoder"},
            },
        )
        with pytest.raises(TaskCompositionError, match="could not be instantiated"):
            compose_metric_from_manifest(str(manifest))

    def test_a_declared_metric_that_does_exist_composes(self, tmp_path):
        """The positive counterpart, so the refusal above is not the only
        outcome this fixture can produce.
        """
        from execute_tools.evaluation_metric import EvaluationMetric

        manifest = write_complete_manifest(tmp_path)
        assert isinstance(compose_metric_from_manifest(str(manifest)), EvaluationMetric)


# ----------------------------------------------------------------------
# The transport
# ----------------------------------------------------------------------


class TestTheManifestBinding:
    def test_unbound_is_none(self):
        assert active_task_manifest_path() is None

    def test_binding_activates_and_resets(self, tmp_path):
        m = tmp_path / "m.yaml"
        m.write_text("metric: {}\n", encoding="utf-8")
        with bind_task_manifest_path(str(m)):
            assert active_task_manifest_path() == str(m)
        assert active_task_manifest_path() is None

    def test_the_bound_path_is_absolute(self, tmp_path, monkeypatch):
        """A child inherits the parent's cwd today, but the flag must not
        depend on that — the same anchoring C7 applies to script paths.
        """
        m = tmp_path / "m.yaml"
        m.write_text("metric: {}\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        with bind_task_manifest_path("m.yaml"):
            bound = active_task_manifest_path()
            assert bound is not None and pathlib.Path(bound).is_absolute()

    def test_it_resets_on_an_exception(self, tmp_path):
        m = tmp_path / "m.yaml"
        m.write_text("metric: {}\n", encoding="utf-8")
        with pytest.raises(RuntimeError), bind_task_manifest_path(str(m)):
            raise RuntimeError("boom")
        assert active_task_manifest_path() is None


class TestTheChildBranchesOnPresenceNotOnTaskName:
    """The discrimination rule this whole milestone rests on."""

    def test_the_child_parses_the_flag(self):
        src = SCORING_CHILD.read_text(encoding="utf-8")
        assert '"--task_manifest"' in src

    def test_the_composed_branch_keys_on_presence(self):
        src = SCORING_CHILD.read_text(encoding="utf-8")
        assert "if args.task_manifest is not None:" in src

    def test_the_child_contains_no_task_name_branch(self):
        """No `if task == "tidmad"` may appear on the acquisition path."""
        src = SCORING_CHILD.read_text(encoding="utf-8")
        assert 'if "tidmad"' not in src
        assert '== "tidmad"' not in src

    def test_the_derivation_is_no_longer_unconditional(self):
        """The exact defect: `derive_tidmad_metric` must sit inside an
        `else`, not at module scope.
        """
        tree = ast.parse(SCORING_CHILD.read_text(encoding="utf-8"))
        module_level_calls = {
            node.func.id
            for stmt in tree.body
            if isinstance(stmt, (ast.Assign, ast.Expr))
            for node in ast.walk(stmt)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "derive_tidmad_metric" not in module_level_calls, (
            "the TIDMAD metric derivation is still unconditional at module "
            "scope — a composed run would score with it"
        )

    def test_the_legacy_branch_still_derives_tidmads_metric(self):
        """Parity: an un-composed run's behaviour is unchanged. Without this
        the test above would pass on a child that had lost the legacy path
        entirely.
        """
        src = SCORING_CHILD.read_text(encoding="utf-8")
        assert "metric = derive_tidmad_metric(dataset_profile, deliverable_spec)" in src

    def test_there_is_no_fallback_after_a_failed_composition(self):
        """A composed run must never silently score with TIDMAD's metric.
        The composed branch must not be wrapped in a try/except that
        recovers into the legacy derivation.
        """
        tree = ast.parse(SCORING_CHILD.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                body_src = ast.dump(node)
                if "compose_metric_from_manifest" in body_src:
                    pytest.fail(
                        "the composed metric acquisition is inside a try — a "
                        "recovery there is the C-P56-1 failure class one layer down"
                    )


class TestOnlyScoringGetsTheManifest:
    """R-11-4 / R-11-1: the transport is scoped to the child that needs it."""

    def test_the_emitter_is_used_once_and_only_by_scoring(self):
        src = (REPO_ROOT / "core" / "sandbox_executor.py").read_text(encoding="utf-8")
        assert src.count("*_task_manifest_argv(),") == 1

    def test_the_emitter_requires_a_binding(self):
        from core.sandbox_executor import _task_manifest_argv

        assert _task_manifest_argv() == []

    def test_the_emitter_produces_the_flag_when_bound(self, tmp_path):
        from core.sandbox_executor import _task_manifest_argv

        m = tmp_path / "m.yaml"
        m.write_text("metric: {}\n", encoding="utf-8")
        with bind_task_manifest_path(str(m)):
            assert _task_manifest_argv() == ["--task_manifest", str(m)]

    def test_a_composed_scoring_launch_really_carries_it(self, tmp_path):
        """Reachability through the REAL launch, not the helper.

        The emitter returning the right fragment proves nothing about
        whether it was spliced into the scoring builder — which is exactly
        the F-11-2 shape (a value emitted by nobody, or parsed by nobody).
        """
        import json as _json
        from unittest.mock import MagicMock, mock_open, patch

        from core.sandbox_executor import TidmadSandbox

        manifest = tmp_path / "m.yaml"
        manifest.write_text("metric: {}\n", encoding="utf-8")

        with patch("core.sandbox_executor.subprocess.run") as mock_run:
            result = MagicMock()
            result.returncode, result.stdout, result.stderr = 0, "done\n", ""
            mock_run.return_value = result
            sb = TidmadSandbox(run_name="c5_run", workspace=str(tmp_path / "ws"))
            with bind_task_manifest_path(str(manifest)):
                with patch(
                    "builtins.open", mock_open(read_data=_json.dumps({"denoising_score": 0.9}))
                ):
                    with patch("os.path.exists", return_value=True), patch("os.remove"):
                        sb.execute_scoring(
                            "c5_exp",
                            "c5_run",
                            "fcnet",
                            {"model_type": "fcnet", "segmentation_size": 10000},
                            {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"},
                            {"loss_type": "ce"},
                        )
            cmd = mock_run.call_args[0][0]

        assert "--task_manifest" in cmd
        assert cmd[cmd.index("--task_manifest") + 1] == str(manifest)

    def test_training_and_inference_do_not_get_it(self, tmp_path):
        """Only the child that constructs a metric receives the manifest."""
        from unittest.mock import MagicMock, patch

        from core.sandbox_executor import TidmadSandbox

        manifest = tmp_path / "m.yaml"
        manifest.write_text("metric: {}\n", encoding="utf-8")

        with patch("core.sandbox_executor._run_observed_subprocess") as mock_run:
            sb = TidmadSandbox(run_name="c5_run", workspace=str(tmp_path / "ws2"))

            def _ok(*_a, **_k):
                import os as _os

                _os.makedirs(sb.dirs["models"], exist_ok=True)
                open(_os.path.join(sb.dirs["models"], "_OK_c5_exp"), "wb").close()
                r = MagicMock()
                r.returncode, r.stdout, r.stderr = 0, "done\n", ""
                return r, None

            mock_run.side_effect = _ok
            with bind_task_manifest_path(str(manifest)):
                sb.execute_training(
                    "c5_exp",
                    "c5_run",
                    "fcnet",
                    {"model_type": "fcnet", "segmentation_size": 10000},
                    {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"},
                    {"loss_type": "ce"},
                )
            assert "--task_manifest" not in mock_run.call_args[0][0]

    def test_secondaries_are_not_transported(self):
        """R-11-4 explicitly: do not speculatively transport every secondary
        metric. They are observational and have their own P2b lifecycle.
        """
        src = SCORING_CHILD.read_text(encoding="utf-8")
        assert "secondary_metric" not in src
        assert "compose_secondary" not in src
