"""Step 10 / P5+P6 — C5: the composed-chain wiring closures W1-W5.

Design:
``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p5_6_lifecycle_and_three_task_closure.md`` §2.5, §10.5, §13 C5.

Five gaps that together made a composed run un-launchable and dishonest, plus
W6 (its own module, ``..._c5_w6_composed_health.py``). Read as one family they
are all **legacy-fallback removal**:

    W1  the chain launcher cannot pass --task_composition        -> unreachable
    W2  no shipped composition manifest exists                   -> nothing to pass
    W3  children bootstrap only the TIDMAD data path             -> id unresolvable
    W4  legacy TIDMAD reference science loads unconditionally    -> silent wrong science
    W5  composed scoring must consume the BOUND metric           -> pin, not a fix
    W6  legacy TIDMAD Health requirements resolve implicitly     -> run cannot start

The half that must NOT move is asserted just as hard as the half that does: an
un-composed run is byte-for-byte what it was, because C-P56-1 is a rule about
composed mode ONLY.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from workflows.task_composition import compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
CHAIN_COMMON = REPO_ROOT / "sdsc_submission_scripts" / "_chain_common.sh"
RUN_CHAIN = REPO_ROOT / "sdsc_submission_scripts" / "run_chain.sh"
SHIPPED_MANIFEST = REPO_ROOT / "configs" / "task_composition" / "tidmad.yaml"
TUNER = REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "ml_hyperparameter_tune_agent.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "step10_p1"

CHILDREN = [
    "execute_tools/train_engine_sandbox.py",
    "execute_tools/inference_single.py",
    "execute_tools/denoising_score_single.py",
]


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


# ---------------------------------------------------------------------------
# W1 — the operator surface
# ---------------------------------------------------------------------------


class TestW1ChainForwarding:
    def test_the_flag_is_parsed_defaulted_and_forwarded(self):
        """Three edits, asserted separately: a flag parsed but never forwarded
        is exactly the shape that made this gap invisible for a milestone."""
        source = CHAIN_COMMON.read_text(encoding="utf-8")
        assert 'TASK_COMPOSITION=""' in source
        assert "--task_composition)" in source
        assert 'APP_ARGS+=(--task_composition "$TASK_COMPOSITION")' in source

    def test_it_is_forwarded_ONLY_when_set(self):
        """The legacy-parity mechanism: an un-composed launch must emit no new
        token at all, not an empty one."""
        source = CHAIN_COMMON.read_text(encoding="utf-8")
        guarded = re.search(
            r'if \[ -n "\$TASK_COMPOSITION" \]; then\s*\n\s*APP_ARGS\+=\(--task_composition '
            r'"\$TASK_COMPOSITION"\)\s*\n\s*fi',
            source,
        )
        assert guarded, "the forward must sit inside a non-empty guard"

    def test_both_scripts_still_parse(self):
        for script in (CHAIN_COMMON, RUN_CHAIN):
            assert subprocess.run(["bash", "-n", str(script)]).returncode == 0

    def test_the_operator_docs_describe_it(self):
        """The node/skill doc-sync rule: the operator's map must show the flag
        and name the shipped manifest."""
        usage = RUN_CHAIN.read_text(encoding="utf-8")
        assert "--task_composition" in usage
        assert "configs/task_composition/tidmad.yaml" in usage
        assert "Task composition" in CHAIN_COMMON.read_text(encoding="utf-8")

    def test_the_sdsc_leg_needs_no_edit_because_it_forwards_unknown_tokens(self):
        """Recorded rather than assumed: `submit_one_iteration.slurm` owns only
        four flags and forwards everything else verbatim, so W1 is a
        `_chain_common.sh` change and nothing more."""
        slurm = (REPO_ROOT / "sdsc_submission_scripts" / "submit_one_iteration.slurm").read_text(
            encoding="utf-8"
        )
        assert "FORWARD_ARGS+=(" in slurm


# ---------------------------------------------------------------------------
# W2 — the shipped manifest
# ---------------------------------------------------------------------------


class TestW2ShippedManifest:
    def test_it_exists_beside_the_other_shipped_task_families(self):
        assert SHIPPED_MANIFEST.is_file()
        assert (REPO_ROOT / "configs" / "task_health" / "tidmad.yaml").is_file()

    def test_it_composes(self):
        composition = compose_run_task_bindings(str(SHIPPED_MANIFEST))
        assert composition.metric.spec.id == "tidmad_denoising_score"
        assert composition.metric.spec.direction == "higher"
        assert composition.task_data_path.task_data_path_id == "tidmad"
        assert composition.dataset_profile.partition_count == 20

    def test_it_declares_no_secondaries(self):
        """TIDMAD's zero-secondary state is SEMANTIC emptiness (P2b §4.7): a
        run that declares none writes no record key and renders zero bytes."""
        assert compose_run_task_bindings(str(SHIPPED_MANIFEST)).secondary_metrics == ()

    def test_it_is_the_SAME_composition_the_p1_fixture_proved(self):
        """The strongest available equivalence: the semantic fingerprint is
        what the run-invariants lock pins, so an identical fingerprint means
        the shipped manifest is the fixture relocated, not a re-specification.
        """
        shipped = compose_run_task_bindings(str(SHIPPED_MANIFEST))
        _plugin_binding.reset_run_scope()
        fixture = compose_run_task_bindings(str(FIXTURES / "tidmad" / "composition.yaml"))
        assert shipped.semantic_fingerprint == fixture.semantic_fingerprint


# ---------------------------------------------------------------------------
# W3 — child bootstrap
# ---------------------------------------------------------------------------


class TestW3ChildBootstrap:
    @pytest.mark.parametrize("child", CHILDREN)
    def test_every_child_bootstraps_all_three_in_tree_data_paths(self, child):
        source = (REPO_ROOT / child).read_text(encoding="utf-8")
        assert "import execute_tools.tidmad_data_path" in source or (
            "from execute_tools.tidmad_data_path import" in source
        )
        assert "import execute_tools.pets_data_path" in source
        assert "import execute_tools.davis_data_path" in source

    @pytest.mark.parametrize(
        "child_module",
        ["execute_tools.train_engine_sandbox", "execute_tools.inference_single"],
    )
    def test_importing_a_child_registers_all_three_ids(self, child_module):
        """The RUNTIME half — a source census alone would pass on an import
        that registered nothing.

        ``denoising_score_single`` is deliberately absent from this
        parametrization: it calls ``parser.parse_args()`` at MODULE level
        (:116), so it is a script rather than an importable module and cannot
        be exercised this way. Its bootstrap is covered by the source census
        above and by the Gate's real scoring subprocess.
        """
        import importlib

        importlib.import_module(child_module)
        from execute_tools.task_data_path import registered_task_data_path_ids

        assert {"tidmad", "oxford_iiit_pet", "davis_future_prediction"} <= set(
            registered_task_data_path_ids()
        )

    def test_an_unknown_id_still_fails_closed(self):
        """W3 widened the built-ins; it must NOT have introduced a fallback."""
        from execute_tools.task_data_path import (
            TaskDataPathResolutionError,
            resolve_transported_task_data_path,
        )

        with pytest.raises(TaskDataPathResolutionError):
            resolve_transported_task_data_path("no_such_task")


# ---------------------------------------------------------------------------
# W4 — no implicit legacy reference science in composed mode
# ---------------------------------------------------------------------------


class TestW4NoImplicitLegacyReferenceScience:
    """The five C-P56-1 tests. Test 5 is the one the operator's review added,
    and it pins the shape the task-name census is blind to."""

    #: The expression the W4 guard keys on. Step 12 / PR-12a (D-12a-1) re-keyed
    #: it from the AMBIENT `active_task_data_path()` to the run's own INPUT
    #: projection: a node should learn whether ITS run is composed from what it
    #: was handed, not from a ContextVar that happens to be bound in the
    #: process. The forbidden-token list below is UNCHANGED — that is the
    #: half of this census that must never be relaxed.
    GUARD_KEY = "task_composition_ref"

    @staticmethod
    def _guard_node() -> ast.If:
        tree = ast.parse(TUNER.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and TestW4NoImplicitLegacyReferenceScience.GUARD_KEY in (
                ast.dump(node.test)
            ):
                return node
        raise AssertionError("the W4 guard was not found")

    def test_1_the_legacy_branch_still_loads_the_full_reference_set(self):
        """Un-composed behaviour, byte-for-byte: 20 per-file entries."""
        from nodes.scoring_reference import load_reference_scores

        refs = load_reference_scores(use_cache=False)
        assert len(refs.raw_per_file_log) == 20
        assert len(refs.gt_per_file_log) == 20

    def test_2_3_4_the_guard_keys_on_composition_presence_for_every_task(self):
        """One guard covers composed TIDMAD, Pets and DAVIS identically —
        there is no per-task branch to test separately, which IS the property.

        Step 12 / PR-12a: the presence VALUE is now the projection the workflow
        builds, so this asserts on that instead of on the ContextVar. The
        property is unchanged — one discriminator, three tasks, no branch.
        """
        from workflows.model_exploration import build_task_composition_ref

        assert build_task_composition_ref(None) is None  # legacy -> loads
        for task in ("tidmad", "pets", "davis"):
            _plugin_binding.reset_run_scope()
            composition = compose_run_task_bindings(str(FIXTURES / task / "composition.yaml"))
            assert build_task_composition_ref(composition) is not None  # composed -> skips

    def test_5_no_metric_identity_conditional_entered_generic_core(self):
        """The census-invisible shape the operator's review rejected.

        A `TIDMAD_METRIC_ID` / task-name / score-sign conditional guarding a
        TIDMAD-only science table is still a science-identity branch inside
        generic orchestration. The guard's test must mention NONE of them.
        """
        guard = self._guard_node()
        rendered = ast.dump(guard.test)
        for forbidden in ("TIDMAD_METRIC_ID", "tidmad", "denoising_score", "s_max"):
            assert forbidden not in rendered, (
                f"the W4 guard tests {forbidden!r} — it must key on composition "
                "PRESENCE only (C-P56-1)"
            )
        assert self.GUARD_KEY in rendered

    def test_the_composed_branch_produces_a_named_absence_not_a_crash(self):
        """`reference_scores is None` is a supported downstream state, and the
        score-table build SKIPS explicitly rather than relying on an exception
        — otherwise a composed run would log a build failure every round."""
        execution = (
            REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "execution.py"
        ).read_text(encoding="utf-8")
        assert "reference_scores is not None" in execution


# ---------------------------------------------------------------------------
# W5 — composed scoring consumes the BOUND metric (a pin, not a fix)
# ---------------------------------------------------------------------------


class TestW5BoundMetricScoringPin:
    def test_the_tuner_acquires_its_metric_from_the_binding(self):
        """P1 hand-off (a) is closed BY CONSTRUCTION; this pins it.

        The composed value comes FIRST and the legacy derivation is only the
        un-composed fallback. Reversing them would silently score every
        composed run under TIDMAD's metric.

        **Step 12 / PR-12d seam B** moved that rule out of the tuner and into
        `evaluation_metric.resolve_run_metric`, so this follows it there. The
        tuner's own half — that it acquires the metric through THAT resolver
        and nothing else — is asserted first.
        """
        tuner = ast.parse(TUNER.read_text(encoding="utf-8"))
        acquisitions = [
            node
            for node in ast.walk(tuner)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("resolve_run_metric", "resolve_bound_run_metric")
        ]
        assert [n.func.id for n in acquisitions] == ["resolve_run_metric"], (
            "the tuner must acquire its metric through the ONE resolver"
        )

        resolver = next(
            node
            for node in ast.walk(
                ast.parse(
                    (REPO_ROOT / "execute_tools" / "evaluation_metric.py").read_text(
                        encoding="utf-8"
                    )
                )
            )
            if isinstance(node, ast.FunctionDef) and node.name == "resolve_run_metric"
        )
        called = [
            node.func.id
            for node in ast.walk(resolver)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "resolve_bound_run_metric" in called, "the bound-metric consult was not found"
        assert called.index("resolve_bound_run_metric") < called.index("derive_tidmad_metric"), (
            f"the bound metric must be consulted FIRST, got {called}"
        )

    def test_a_bound_metric_is_what_resolves(self):
        """The mutation: rebind, and the resolved identity moves."""
        from execute_tools.evaluation_metric import bind_run_metric, resolve_bound_run_metric

        assert resolve_bound_run_metric() is None

        tidmad = compose_run_task_bindings(str(SHIPPED_MANIFEST)).metric
        with bind_run_metric(tidmad):
            assert resolve_bound_run_metric().spec.id == "tidmad_denoising_score"

        _plugin_binding.reset_run_scope()
        davis = compose_run_task_bindings(str(FIXTURES / "davis" / "composition.yaml")).metric
        with bind_run_metric(davis):
            resolved = resolve_bound_run_metric()
            assert resolved.spec.id == "mse"
            assert resolved.spec.direction == "lower"

    def test_the_subprocess_re_derivation_is_legacy_path_only(self):
        """The standing note §10.5 requires. `denoising_score_single` re-derives
        TIDMAD's metric at module level; it is reached ONLY by
        `execute_scoring`, i.e. the legacy single-file branch, never by the
        chain route that honours the binding.
        """
        sandbox = (REPO_ROOT / "core" / "sandbox_executor.py").read_text(encoding="utf-8")
        assert sandbox.count("denoising_score_single") >= 1
        execution = (
            REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "execution.py"
        ).read_text(encoding="utf-8")
        assert "sandbox.evaluate_metric(" in execution


# ---------------------------------------------------------------------------
# W7 — the chain runner's PRE-FLIGHT must resolve the same Health binding
# ---------------------------------------------------------------------------


class TestW7PreflightAndWorkflowAgree:
    """Found by the FIRST real composed chain run (Gate 2 attempt 1 = FAIL).

    ``run_one_iteration.compute_expected_invariants`` materializes the
    effective Health config BEFORE ``run_workflow`` does, and its docstring
    claims the two are idempotent. P1 gave ``run_workflow`` a
    ``task_health_binding`` but not this earlier pre-flight, so a COMPOSED run
    wrote ``task_health_binding: legacy_default`` first and then asked for
    ``explicit`` — two documents, two body shas, and the workspace-immutability
    check correctly refused the run before any LLM spend.

    No test caught it because none drove the REAL chain runner under a
    composition; the module CLI resolves the composition before its only
    materialization, so that path was always consistent.

    **This class censuses the composition-derived keyword NAMES.** The VALUE
    half lives in ``test_step12_pr12a_c1_composed_invariants.TestW7ValueAgreement``
    (Step 12 / PR-12a, F-12-1): ``resolved_data_scope`` is passed by both call
    sites and spelled identically while being computed from different
    topologies, which a name census is structurally incapable of seeing.
    """

    @staticmethod
    def _materialize(workspace, binding=None):
        from execute_tools.health_checks.config import materialize_effective_config

        kwargs = {} if binding is None else {"task_health_binding": binding}
        return materialize_effective_config(
            None, [4, 5, 6, 7, 8, 9], workspace, resolved_scope=list(range(4, 10)), **kwargs
        )

    def test_a_composed_run_materializes_the_same_document_twice(self, tmp_path):
        """THE REGRESSION. Second call must be a no-op, not a refusal."""
        binding = compose_run_task_bindings(str(SHIPPED_MANIFEST)).task_health_binding
        _p1, sha1 = self._materialize(str(tmp_path), binding)
        _p2, sha2 = self._materialize(str(tmp_path), binding)
        assert sha1 == sha2

    def test_the_two_bindings_really_DO_produce_different_documents(self, tmp_path):
        """Anti-vacuity: the test above would pass trivially if the binding
        made no difference to the materialized body. It does — the document
        records the binding STATE — which is exactly why the pre-flight had to
        be told about it rather than left to default.
        """
        binding = compose_run_task_bindings(str(SHIPPED_MANIFEST)).task_health_binding
        _lp, legacy_sha = self._materialize(str(tmp_path / "legacy"))
        _cp, composed_sha = self._materialize(str(tmp_path / "composed"), binding)
        assert legacy_sha != composed_sha

    def test_the_legacy_document_is_unchanged(self, tmp_path):
        """W7 must not have moved the un-composed path. This sha is the one
        the failed Gate run actually wrote, recorded here as the parity pin.
        """
        _p, sha = self._materialize(str(tmp_path))
        assert sha == "abced73458b130968d7b0363fff7f4ad4ca21fb105fae18f8d079e557466629b"

    def test_the_preflight_passes_EVERY_composition_derived_invariant(self):
        """The census that prevents a THIRD occurrence of this defect.

        W7's first cut threaded ``task_health_binding`` alone and forgot its
        sibling ``task_composition_fingerprint``; iteration 2's pre-flight then
        computed ``None`` against a lock that already held the fingerprint, and
        the chain refused itself. Asserting the two argument NAMES would carry
        the same blind spot the next time a third is added — so this compares
        the two call sites' composition-derived keyword SETS.
        """
        runner = REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py"
        workflow = REPO_ROOT / "workflows" / "model_exploration.py"

        def _invariant_kwargs(path):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found = set()
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "build_run_invariants"
                ):
                    found |= {
                        kw.arg
                        for kw in node.keywords
                        if kw.arg and ("task_" in kw.arg or "composition" in kw.arg)
                    }
            return found

        workflow_kwargs = _invariant_kwargs(workflow)
        runner_kwargs = _invariant_kwargs(runner)
        assert workflow_kwargs, "no composition-derived invariants found in run_workflow"
        assert workflow_kwargs == runner_kwargs, (
            "the chain runner's pre-flight and run_workflow must pass the SAME "
            f"composition-derived invariants; workflow={sorted(workflow_kwargs)} "
            f"runner={sorted(runner_kwargs)}. A divergence makes the workspace "
            "lock contradict itself on iteration 2."
        )

    def test_the_preflight_takes_the_composition_object_not_derived_values(self):
        """Structural, so the divergence cannot recur: the pre-flight receives
        the COMPOSITION and derives every value itself."""
        runner = (REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py").read_text(
            encoding="utf-8"
        )
        assert "compute_expected_invariants(args, run_composition=run_composition)" in runner

    def test_the_composition_is_resolved_before_the_preflight(self):
        """Ordering is the fix's substance: composing AFTER the pre-flight
        would leave it with nothing to pass."""
        runner_path = REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py"
        source = runner_path.read_text(encoding="utf-8")
        compose_at = source.index("run_composition = (")
        preflight_at = source.index("expected_invariants = compute_expected_invariants(")
        assert compose_at < preflight_at, (
            "the composition must be resolved BEFORE the invariants pre-flight"
        )
