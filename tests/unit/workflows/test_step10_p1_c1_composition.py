"""Step 10 / P1 C1 — the composition authority: resolution, refusal, identity.

``compose_run_task_bindings`` is the only place a run's task semantics come
into existence. Three families of defect live here, and nothing else in the
repository catches them:

* **it resolves the wrong thing, or resolves at all when it should refuse.**
  Every fail-closed branch is tested individually, because the failure mode a
  composition exists to prevent is not an exception — it is a run that
  *starts* with somebody else's dataset, metric or Health family and produces
  plausible, wrong numbers. A misspelled ref that silently resolved TIDMAD
  would look exactly like a working run.

* **it resolves the task data path more than once.** §5.2a is a structural
  claim: the composition carries the RESOLVED implementation object, and no
  downstream consumer turns an id back into an implementation. A test that
  only compared ids would pass for a second registry lookup too.

* **the semantic fingerprint confuses location with meaning.** A task package
  moved to another directory is the SAME scientific run (its resume must not
  fail); a package whose metric, profile, declaration or plugin CONTENT
  changed is a different one (its resume must fail). Both halves are proven
  with hand-built fixture pairs, because a fingerprint that accidentally
  hashed an absolute path passes every test that never relocates anything.

The framework-owned Quickstart and a synthetic external task exercise the same
contract through different declarations and plugin files.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from workflows.task_composition import (
    RunTaskComposition,
    TaskCompositionError,
    compose_run_task_bindings,
    composition_field_names,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "step10_p1"

QUICKSTART_MANIFEST = REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"
FOURTH_MANIFEST = FIXTURES / "fourth_task" / "composition.yaml"


def test_prompt_profile_enters_identity_binding_and_drift_guard(tmp_path, monkeypatch):
    """A declared renderer must reach real prompt assembly and pin its code."""
    import yaml

    from agent.prompt_rendering import PromptRenderingProfile, bind_prompt_profile
    from agent.prompt_templates.native_training import render_native_training_appendix
    from workflows import task_composition as composition

    target = tmp_path / "task"
    shutil.copytree(FOURTH_MANIFEST.parent, target)
    manifest = target / "composition.yaml"
    source = tmp_path / "provider.txt"
    source.write_text("provider v1")
    profile = PromptRenderingProfile(
        "example-v1",
        "1",
        {"native_training.appendix": lambda: "EXPLICIT"},
        frozenset(),
        {"provider": source},
    )
    monkeypatch.setattr(composition, "resolve_prompt_profile", lambda name: profile)
    native = compose_run_task_bindings(str(manifest))
    declaration = yaml.safe_load(manifest.read_text())
    declaration["prompt_renderer"] = "example-v1"
    manifest.write_text(yaml.safe_dump(declaration))
    explicit = compose_run_task_bindings(str(manifest))
    assert explicit.semantic_fingerprint != native.semantic_fingerprint
    with composition.bind_run_task_composition(explicit, physical_data_root=str(tmp_path)):
        assert render_native_training_appendix() == "EXPLICIT"
        composition.verify_composition_is_bound(explicit)
        with bind_prompt_profile(None), pytest.raises(composition.CompositionNotBoundError):
            composition.verify_composition_is_bound(explicit)
    source.write_text("provider v2")
    with pytest.raises(ValueError, match="changed after composition"):
        with composition.bind_run_task_composition(explicit, physical_data_root=str(tmp_path)):
            pytest.fail("stale provider must not bind")


@pytest.fixture(autouse=True)
def _clear_task_config_cache():
    """``load_task_config`` memoizes per absolute path, process-wide.

    A relocation test writes different content at a different path, so the
    cache is correct — but a test that rewrote content at the SAME path would
    silently read the stale parse. Clearing around each test removes the
    ambiguity rather than relying on nobody ever doing that.
    """
    from workflows.task_config import _clear_cache_for_tests

    _clear_cache_for_tests()
    yield
    _clear_cache_for_tests()


# ---------------------------------------------------------------------------
# The three shipped tracks + the fourth task
# ---------------------------------------------------------------------------


class TestFrameworkCompositionExamples:
    """Design §6: the same interface, different supplied values."""

    def test_quickstart_composes_through_the_public_loader(self):
        composition = compose_run_task_bindings(str(QUICKSTART_MANIFEST))

        assert composition.task_data_path_id == "quickstart_tabular"
        assert composition.metric.spec.id == "accuracy"
        assert composition.metric.spec.direction == "higher"
        assert composition.interpretation_blocks is None
        assert composition.task_description.strip()

    def test_the_two_compositions_are_semantically_distinct(self):
        """One fingerprint per task package. Two tasks colliding on one
        digest would make the resume guard vacuous."""
        fingerprints = {
            manifest.parent.name: compose_run_task_bindings(str(manifest)).semantic_fingerprint
            for manifest in (QUICKSTART_MANIFEST, FOURTH_MANIFEST)
        }
        assert len(set(fingerprints.values())) == 2, fingerprints


class TestFourthTaskNeedsNoFrameworkEdit:
    """The adversarial case (design §6, C4's proof anchors here).

    Everything this task needs is its own: a data-path plugin FILE, a metric
    implementation plugin FILE, its own declaration, Health family,
    interpretation prose and task config.
    """

    def test_it_composes_entirely_from_out_of_tree_plugin_files(self):
        composition = compose_run_task_bindings(str(FOURTH_MANIFEST))

        assert composition.task_data_path_id == "spectro_segmentation_v0"
        assert composition.metric.spec.id == "band_coverage_error"
        assert composition.metric.spec.direction == "lower"
        assert type(composition.metric).__name__ == "BandCoverageMetric"
        assert composition.interpretation_blocks is not None
        assert composition.interpretation_blocks.per_model_guidance is None

    def test_its_plugin_files_are_pinned_by_CONTENT_not_by_location(self):
        composition = compose_run_task_bindings(str(FOURTH_MANIFEST))
        plugins = composition.provenance.plugins

        assert {plugin.configured_ref for plugin in plugins} == {
            "plugins/spectro_data_path.py",
            "plugins/band_coverage_metric.py",
        }
        for plugin in plugins:
            assert len(plugin.content_sha256) == 64
            # The absolute path is diagnostics ONLY and must not appear in
            # the identity that the run lock pins.
            assert "absolute_path" not in plugin.canonical_identity()

    def test_the_framework_registry_learns_the_id_only_by_loading_the_task_s_file(self):
        """Registration happens because the task's OWN file ran — not because
        anything in SIDERIUS lists this id."""
        from execute_tools.task_data_path import registered_task_data_path_ids

        composition = compose_run_task_bindings(str(FOURTH_MANIFEST))
        assert composition.task_data_path_id in registered_task_data_path_ids()

        production_sources = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for directory in (
                "src/workflows",
                "src/core",
                "src/execute_tools",
                "src/nodes",
                "src/agent",
            )
            for path in (REPO_ROOT / directory).rglob("*.py")
            if "__pycache__" not in path.parts
        )
        assert "spectro_segmentation_v0" not in production_sources


# ---------------------------------------------------------------------------
# §5.2a — resolved exactly once
# ---------------------------------------------------------------------------


class TestTaskDataPathIsResolvedExactlyOnce:
    def test_the_composition_carries_the_implementation_object_not_an_id(self):
        composition = compose_run_task_bindings(str(FOURTH_MANIFEST))

        assert not isinstance(composition.task_data_path, str)
        for method in (
            "training_dataset",
            "validation_dataset",
            "write_deliverable",
            "read_evaluation_payload",
        ):
            assert callable(getattr(composition.task_data_path, method))

    def test_a_class_symbol_is_INSTANTIATED_not_carried_as_the_class(self):
        """A class and a factory are both callable, and a class also answers
        ``task_data_path_id`` — so carrying the class would pass registration
        (its methods are callable) and then hand every consumer unbound
        functions."""
        impl = compose_run_task_bindings(str(FOURTH_MANIFEST)).task_data_path
        assert not isinstance(impl, type), "composition carried the class instead of an instance"

    def test_the_id_is_read_FROM_the_resolved_object(self):
        """``task_data_path_id`` is a property over the resolved object, not a
        stored field — so there is no way for the carried id and the carried
        implementation to disagree."""
        composition = compose_run_task_bindings(str(FOURTH_MANIFEST))

        assert "task_data_path_id" not in composition_field_names()
        assert composition.task_data_path_id == composition.task_data_path.task_data_path_id

    def test_recomposing_in_one_process_yields_the_REGISTERED_object(self):
        """One id, one object. A second instance of the same class would make
        the parent's bound object and the child's resolved object different
        while every id comparison still passed."""
        from execute_tools.task_data_path import (
            TaskBindingContext,
            resolve_task_data_path,
        )

        first = compose_run_task_bindings(str(FOURTH_MANIFEST))
        second = compose_run_task_bindings(str(FOURTH_MANIFEST))
        registered = resolve_task_data_path(
            TaskBindingContext(task_data_path_id=first.task_data_path_id)
        )

        assert second.task_data_path is registered
        assert second.task_data_path is first.task_data_path


# ---------------------------------------------------------------------------
# Fail-closed matrix — no branch resolves TIDMAD
# ---------------------------------------------------------------------------


def _write_manifest(tmp_path: Path, body: str) -> Path:
    """A manifest in a temp dir whose refs point back at the fourth task."""
    package = tmp_path / "pkg"
    shutil.copytree(FIXTURES / "fourth_task", package)
    manifest = package / "composition.yaml"
    manifest.write_text(body, encoding="utf-8")
    return manifest


_VALID_BODY = (FIXTURES / "fourth_task" / "composition.yaml").read_text(encoding="utf-8")


class TestFailClosed:
    """Every branch names what it found; none falls back."""

    def test_a_missing_manifest_refuses(self, tmp_path):
        with pytest.raises(TaskCompositionError, match="not found"):
            compose_run_task_bindings(str(tmp_path / "absent.yaml"))

    def test_a_non_mapping_manifest_refuses(self, tmp_path):
        manifest = _write_manifest(tmp_path, "- just\n- a list\n")
        with pytest.raises(TaskCompositionError, match="must be a YAML mapping"):
            compose_run_task_bindings(str(manifest))

    def test_invalid_yaml_refuses(self, tmp_path):
        manifest = _write_manifest(tmp_path, "task_data_path: [unclosed\n")
        with pytest.raises(TaskCompositionError, match="not valid YAML"):
            compose_run_task_bindings(str(manifest))

    def test_an_unknown_section_refuses_rather_than_being_ignored(self, tmp_path):
        """A misspelled section that was ignored would leave its family
        resolving the legacy default — silent TIDMAD by typo."""
        manifest = _write_manifest(
            tmp_path, _VALID_BODY + "\ninterpretaton_blocks:\n  none: true\n"
        )
        with pytest.raises(TaskCompositionError, match="unknown key"):
            compose_run_task_bindings(str(manifest))

    @pytest.mark.parametrize(
        "section", ["task_data_path", "dataset_profile", "metric", "task_health", "task_config"]
    )
    def test_every_required_section_must_be_stated(self, tmp_path, section):
        body = "\n".join(
            block
            for block in _VALID_BODY.split("\n\n")
            if not block.lstrip().startswith(f"{section}:")
        )
        manifest = _write_manifest(tmp_path, body)
        with pytest.raises(TaskCompositionError, match="missing required"):
            compose_run_task_bindings(str(manifest))

    def test_a_misspelled_plugin_file_ref_refuses(self, tmp_path):
        manifest = _write_manifest(
            tmp_path, _VALID_BODY.replace("plugins/spectro_data_path.py", "plugins/spectro_dta.py")
        )
        with pytest.raises(TaskCompositionError, match="does not exist"):
            compose_run_task_bindings(str(manifest))

    def test_a_misspelled_symbol_refuses_and_names_what_is_available(self, tmp_path):
        manifest = _write_manifest(
            tmp_path, _VALID_BODY.replace("symbol: SpectroTaskDataPath", "symbol: SpectroTaskPath")
        )
        with pytest.raises(TaskCompositionError, match="defines no symbol"):
            compose_run_task_bindings(str(manifest))

    def test_an_unimportable_module_ref_refuses(self, tmp_path):
        manifest = _write_manifest(
            tmp_path,
            _VALID_BODY.replace(
                "  file: plugins/spectro_data_path.py", "  module: execute_tools.no_such_module"
            ),
        )
        with pytest.raises(TaskCompositionError, match="could not be imported"):
            compose_run_task_bindings(str(manifest))

    def test_declaring_both_file_and_module_refuses(self, tmp_path):
        manifest = _write_manifest(
            tmp_path,
            _VALID_BODY.replace(
                "  file: plugins/spectro_data_path.py",
                "  file: plugins/spectro_data_path.py\n  module: execute_tools.tidmad_data_path",
            ),
        )
        with pytest.raises(TaskCompositionError, match="exactly ONE"):
            compose_run_task_bindings(str(manifest))

    def test_a_plugin_that_raises_on_import_refuses_with_the_ref_named(self, tmp_path):
        manifest = _write_manifest(tmp_path, _VALID_BODY)
        (manifest.parent / "plugins" / "spectro_data_path.py").write_text(
            "raise RuntimeError('deliberate fixture failure')\n", encoding="utf-8"
        )
        with pytest.raises(TaskCompositionError, match="raised while importing"):
            compose_run_task_bindings(str(manifest))

    def test_an_id_cross_check_mismatch_refuses(self, tmp_path):
        """The implementation is the authority on its own id; the manifest's
        value is a cross-check, and a mismatch means the composition names
        something other than what it thinks it names."""
        manifest = _write_manifest(
            tmp_path, _VALID_BODY.replace("id: spectro_segmentation_v0", "id: spectro_v0")
        )
        with pytest.raises(TaskCompositionError, match="expects id"):
            compose_run_task_bindings(str(manifest))

    def test_a_broken_dataset_profile_refuses(self, tmp_path):
        manifest = _write_manifest(tmp_path, _VALID_BODY)
        (manifest.parent / "declared" / "dataset_profile.json").write_text(
            '{"dataset": {}}', encoding="utf-8"
        )
        with pytest.raises(TaskCompositionError, match=r"dataset_profile.*could not be loaded"):
            compose_run_task_bindings(str(manifest))

    def test_a_metric_declaration_with_an_unknown_scoreability_contract_refuses(self, tmp_path):
        manifest = _write_manifest(tmp_path, _VALID_BODY)
        declaration = manifest.parent / "declared" / "metric_band_coverage.json"
        payload = json.loads(declaration.read_text(encoding="utf-8"))
        payload["scoreability"] = {"contract_id": "no_such_contract"}
        declaration.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(TaskCompositionError, match="not a valid MetricSpec"):
            compose_run_task_bindings(str(manifest))

    def test_a_metric_implementation_that_is_not_an_EvaluationMetric_refuses(self, tmp_path):
        """The metric HANDLE is the one scoring contract (Step 06). A
        composition may choose which instance, never a different contract."""
        manifest = _write_manifest(tmp_path, _VALID_BODY)
        (manifest.parent / "plugins" / "band_coverage_metric.py").write_text(
            "class BandCoverageMetric:\n    def __init__(self, spec):\n        self.spec = spec\n",
            encoding="utf-8",
        )
        with pytest.raises(TaskCompositionError, match="not an EvaluationMetric"):
            compose_run_task_bindings(str(manifest))

    def test_a_missing_task_health_config_refuses(self, tmp_path):
        manifest = _write_manifest(tmp_path, _VALID_BODY)
        (manifest.parent / "declared" / "task_health.yaml").unlink()
        with pytest.raises(TaskCompositionError, match="never falls back"):
            compose_run_task_bindings(str(manifest))

    def test_declaring_both_a_health_config_and_none_refuses(self, tmp_path):
        manifest = _write_manifest(
            tmp_path,
            _VALID_BODY.replace(
                "task_health:\n  config: declared/task_health.yaml",
                "task_health:\n  none: true\n  config: declared/task_health.yaml",
            ),
        )
        with pytest.raises(TaskCompositionError, match="either has a Health family"):
            compose_run_task_bindings(str(manifest))

    def test_an_empty_task_description_refuses(self, tmp_path):
        manifest = _write_manifest(tmp_path, _VALID_BODY)
        config = manifest.parent / "declared" / "task_config.yaml"
        config.write_text(
            'task_description: "   "\n'
            "forward_contract:\n"
            '  input_shape: "[B, T] int"\n'
            '  output_shape: "[B, 256, T] float"\n',
            encoding="utf-8",
        )
        with pytest.raises(TaskCompositionError, match="task_config"):
            compose_run_task_bindings(str(manifest))

    def test_a_forward_contract_typo_refuses(self, tmp_path):
        """``ForwardContract`` forbids extra keys precisely so a plural typo
        raises instead of rendering empty downstream. The composition must
        surface that rather than swallow it."""
        manifest = _write_manifest(tmp_path, _VALID_BODY)
        config = manifest.parent / "declared" / "task_config.yaml"
        config.write_text(
            'task_description: a task\nforward_contract:\n  input_shapes: "[B, T] int"\n',
            encoding="utf-8",
        )
        with pytest.raises(TaskCompositionError, match="could not be loaded"):
            compose_run_task_bindings(str(manifest))

    def test_a_broken_interpretation_declaration_refuses(self, tmp_path):
        manifest = _write_manifest(tmp_path, _VALID_BODY)
        (manifest.parent / "declared" / "interpretation.yaml").write_text(
            "evidence_readng: typo'd key\n", encoding="utf-8"
        )
        with pytest.raises(TaskCompositionError, match="could not be loaded"):
            compose_run_task_bindings(str(manifest))

    @pytest.mark.parametrize(
        "break_it",
        [
            lambda body: body.replace("plugins/spectro_data_path.py", "plugins/absent.py"),
            lambda body: body.replace("symbol: SpectroTaskDataPath", "symbol: Nope"),
            lambda body: "\n".join(
                block for block in body.split("\n\n") if not block.lstrip().startswith("metric:")
            ),
            lambda body: body + "\nnot_a_section:\n  none: true\n",
        ],
    )
    def test_a_failed_fourth_task_composition_never_names_another_task(self, tmp_path, break_it):
        """The prose contract, executably: refusing a fourth task's broken
        composition must not name another task at all.

        A message offering TIDMAD would be an invitation to do the one thing
        the composition exists to forbid — and an error string is exactly how
        a task-name literal first creeps onto a generic surface. It caught a
        real one during C1: the missing-section message said "would silently
        resolve TIDMAD".
        """
        manifest = _write_manifest(tmp_path, break_it(_VALID_BODY))
        with pytest.raises(TaskCompositionError) as excinfo:
            compose_run_task_bindings(str(manifest))
        message = str(excinfo.value).lower()
        for task_name in ("tidmad", "pets", "oxford", "davis"):
            assert task_name not in message, f"the refusal named {task_name}: {message}"


class TestLegacyOmittedIsUnreachableFromAComposition:
    def test_the_two_expressible_health_states_are_explicit_path_and_explicit_none(self, tmp_path):
        """08b has three binding states; a composition may express two.

        ``LEGACY_OMITTED`` means "the caller said nothing", which resolves
        TIDMAD's task health config — so a composition able to express it
        could compose a Pets run that silently used TIDMAD's roster and
        thresholds."""
        from execute_tools.health_checks._composition import HealthBindingState

        explicit_path = compose_run_task_bindings(str(FOURTH_MANIFEST))
        assert isinstance(explicit_path.task_health_binding, str)
        assert not isinstance(explicit_path.task_health_binding, HealthBindingState)

        manifest = _write_manifest(
            tmp_path,
            _VALID_BODY.replace(
                "task_health:\n  config: declared/task_health.yaml",
                "task_health:\n  none: true",
            ),
        )
        explicit_none = compose_run_task_bindings(str(manifest))
        assert explicit_none.task_health_binding is HealthBindingState.EXPLICIT_NONE

    def test_no_composed_value_can_be_legacy_omitted(self, tmp_path):
        from execute_tools.health_checks._composition import HealthBindingState

        for manifest in (QUICKSTART_MANIFEST, FOURTH_MANIFEST):
            binding = compose_run_task_bindings(str(manifest)).task_health_binding
            assert binding is not HealthBindingState.LEGACY_OMITTED


# ---------------------------------------------------------------------------
# §5.9 — semantic fingerprint vs diagnostic provenance
# ---------------------------------------------------------------------------


class TestSemanticFingerprint:
    def test_relocating_the_whole_package_preserves_the_fingerprint(self, tmp_path):
        """The property an absolute path in the digest would break: two
        checkouts of the same task package are the same scientific run, and a
        fingerprint that disagreed would fail their resumes for a reason that
        has nothing to do with the science."""
        here = tmp_path / "somewhere" / "pkg"
        there = tmp_path / "elsewhere" / "deeper" / "pkg"
        shutil.copytree(FIXTURES / "fourth_task", here)
        shutil.copytree(FIXTURES / "fourth_task", there)

        first = compose_run_task_bindings(str(here / "composition.yaml"))
        second = compose_run_task_bindings(str(there / "composition.yaml"))

        assert first.semantic_fingerprint == second.semantic_fingerprint
        # ...while the DIAGNOSTIC provenance does differ, which is the whole
        # reason the two are separate fields.
        assert first.provenance.manifest_path != second.provenance.manifest_path

    @pytest.mark.parametrize(
        ("what", "mutate"),
        [
            (
                "metric declaration",
                lambda pkg: (pkg / "declared" / "metric_band_coverage.json").write_text(
                    json.dumps(
                        {
                            **json.loads(
                                (pkg / "declared" / "metric_band_coverage.json").read_text()
                            ),
                            "aggregation": "median_absolute_band_coverage_error",
                        }
                    ),
                    encoding="utf-8",
                ),
            ),
            (
                "dataset profile",
                lambda pkg: (pkg / "declared" / "dataset_profile.json").write_text(
                    (pkg / "declared" / "dataset_profile.json")
                    .read_text()
                    .replace('"num_files": 5', '"num_files": 6'),
                    encoding="utf-8",
                ),
            ),
            (
                "plugin content",
                lambda pkg: (pkg / "plugins" / "band_coverage_metric.py").write_text(
                    (pkg / "plugins" / "band_coverage_metric.py").read_text()
                    + "\n# a behavioural edit would look exactly like this to a digest\n",
                    encoding="utf-8",
                ),
            ),
            (
                "task description",
                lambda pkg: (pkg / "declared" / "task_config.yaml").write_text(
                    (pkg / "declared" / "task_config.yaml")
                    .read_text()
                    .replace("LOWER is better.", "LOWER is better. Revised."),
                    encoding="utf-8",
                ),
            ),
            (
                "interpretation prose",
                lambda pkg: (pkg / "declared" / "interpretation.yaml").write_text(
                    (pkg / "declared" / "interpretation.yaml")
                    .read_text()
                    .replace("coverage units", "normalised coverage units"),
                    encoding="utf-8",
                ),
            ),
            (
                "health config content",
                lambda pkg: (pkg / "declared" / "task_health.yaml").write_text(
                    (pkg / "declared" / "task_health.yaml")
                    .read_text()
                    .replace("min_std: 0.02", "min_std: 0.04"),
                    encoding="utf-8",
                ),
            ),
        ],
    )
    def test_changed_semantic_content_changes_the_fingerprint(self, tmp_path, what, mutate):
        baseline_pkg = tmp_path / "base" / "pkg"
        mutated_pkg = tmp_path / "mutated" / "pkg"
        shutil.copytree(FIXTURES / "fourth_task", baseline_pkg)
        shutil.copytree(FIXTURES / "fourth_task", mutated_pkg)
        mutate(mutated_pkg)

        baseline = compose_run_task_bindings(str(baseline_pkg / "composition.yaml"))
        mutated = compose_run_task_bindings(str(mutated_pkg / "composition.yaml"))

        assert baseline.semantic_fingerprint != mutated.semantic_fingerprint, (
            f"a changed {what} left the semantic fingerprint unchanged; a "
            "composed resume would accept a different scientific run"
        )

    def test_a_cosmetic_ref_respelling_does_not_change_the_fingerprint(self, tmp_path):
        """``./plugins/x.py`` and ``plugins/x.py`` name the same file. Leaving
        both spellings alive would let a purely cosmetic config edit
        invalidate a workspace."""
        plain = tmp_path / "plain" / "pkg"
        dotted = tmp_path / "dotted" / "pkg"
        shutil.copytree(FIXTURES / "fourth_task", plain)
        shutil.copytree(FIXTURES / "fourth_task", dotted)
        manifest = dotted / "composition.yaml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace("file: plugins/", "file: ./plugins/"),
            encoding="utf-8",
        )

        assert (
            compose_run_task_bindings(str(plain / "composition.yaml")).semantic_fingerprint
            == compose_run_task_bindings(str(manifest)).semantic_fingerprint
        )

    def test_provenance_is_never_hashed_into_the_fingerprint(self):
        """The structural half of the claim: no absolute path from this host
        appears anywhere in the hashed payload."""
        composition = compose_run_task_bindings(str(FOURTH_MANIFEST))
        assert composition.provenance.manifest_path.startswith("/")
        assert composition.provenance.source_paths
        for plugin in composition.provenance.plugins:
            assert plugin.absolute_path.startswith("/")
            assert str(FIXTURES) not in json.dumps(plugin.canonical_identity())


# ---------------------------------------------------------------------------
# Ownership guard
# ---------------------------------------------------------------------------


class TestOwnershipGuard:
    def test_the_composition_declares_no_chain_state_field(self):
        from core.chain_state import chain_state_field_names

        assert chain_state_field_names() & composition_field_names() == set()

    def test_the_guard_actually_runs_and_is_derived_not_hardcoded(self, monkeypatch):
        """Plant the collision from the OTHER side.

        Making ``ChainState`` claim one of the composition's real field names
        must make construction fail. That proves two things a static
        comparison cannot: ``__post_init__`` is genuinely executed, and the
        forbidden set is READ from ``ChainState`` at construction rather than
        frozen into a list that would go stale the first time the state
        carrier grows.
        """
        import core.chain_state as chain_state

        composition = compose_run_task_bindings(str(FOURTH_MANIFEST))
        stolen = "dataset_profile"
        assert stolen in composition_field_names()

        monkeypatch.setattr(chain_state, "chain_state_field_names", lambda: frozenset({stolen}))
        with pytest.raises(TypeError, match="must not carry mutable chain state"):
            RunTaskComposition(
                task_data_path=composition.task_data_path,
                dataset_profile=composition.dataset_profile,
                metric=composition.metric,
                task_health_binding=composition.task_health_binding,
                interpretation_blocks=composition.interpretation_blocks,
                task_description=composition.task_description,
                forward_contract=composition.forward_contract,
                semantic_fingerprint=composition.semantic_fingerprint,
                provenance=composition.provenance,
            )
