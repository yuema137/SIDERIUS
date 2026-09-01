"""Step 12 / PR-12d — D2 (seam B): the composed attempt-scope authority.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §D.B / §M `D2`.

The failure class is **not** "N calls to ``tidmad_topology``". It is that a
composed run **already holds a bound task scope capability while planning and
execution separately construct TIDMAD facts** — five DIRECT decoders
(``planning.py`` 381/460/465, ``execution.py`` 1066,
``ml_hyperparameter_tune_agent.py`` 758) and one TRANSITIVE one
(``run():625`` → ``derive_tidmad_deliverable_spec`` → ``tidmad_topology`` ×4),
each of which killed a composed contrast run before any training.

What each class owns
--------------------

``TestProjectionAuthority``
    One projection, asked as a MEMBERSHIP question. A profile that declares
    the sections but carries a malformed payload still RAISES: a broken
    declaration is not an absent one.

``TestConsumerSitesReadFacts``
    The AST census: zero direct topology decodes remain among the CONSUMERS,
    and the single decode lives in the projection.

``TestDifferentialOracleUnderTidmad``
    Legacy values arrive BY CONSTRUCTION. Every fact a TIDMAD profile yields
    is the object it yielded before, so nothing observable moved.

``TestDeclaredAbsence``
    A task with no physical geometry SKIPS or DECLINES BY NAME — never
    guesses, never invents a number a record would carry as a measurement.

``TestFailClosed``
    The two frozen falsifiers.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from execute_tools.dataset_config import (
    NUM_FILES,
    SEGMENTS_PER_FILE,
    TIDMAD_PROFILE,
    ChannelIdentity,
    DatasetConfig,
    DatasetProfile,
    ValueEncoding,
    declares_tidmad_topology,
    tidmad_topology,
)
from nodes.ml_hyperparameter_tune_agent.scope_acquisition import (
    AttemptTopologyFacts,
    TaskTopologyUnavailableError,
    project_attempt_topology_facts,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
TUNER = REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent"


def contrast_profile() -> DatasetProfile:
    """A Q-12-4-honest profile with an opaque, non-TIDMAD topology."""
    return DatasetProfile(
        partition_count=3,
        topology={"kind": "d2_contrast_shaped_v1", "num_classes": 37},
        anchor_selection_files=[0],
        health_peek_files=[0],
    )


def malformed_tidmad_profile() -> DatasetProfile:
    """Declares TIDMAD's SECTION NAMES but not a valid payload."""
    return DatasetProfile(
        partition_count=3,
        topology={"dataset": {"nonsense": 1}, "channels": {}, "encoding": {}},
        anchor_selection_files=[0],
        health_peek_files=[0],
    )


# ======================================================================


class TestProjectionAuthority:
    """One projection; a MISS is a membership test, not an exception to catch."""

    def test_a_tidmad_profile_yields_its_physical_dataset(self):
        facts = project_attempt_topology_facts(TIDMAD_PROFILE)
        assert facts.declares_physical_geometry
        assert isinstance(facts.physical_dataset, DatasetConfig)

    def test_a_contrast_profile_yields_a_DECLARED_absence(self):
        facts = project_attempt_topology_facts(contrast_profile())
        assert not facts.declares_physical_geometry
        assert facts.physical_dataset is None

    def test_a_MALFORMED_tidmad_topology_still_RAISES(self):
        """The distinction the membership test exists to preserve.

        ``tidmad_topology`` raises for two different reasons — "no sections"
        and "sections present but invalid". Inferring absence from catching
        its ``ValueError`` would silently accept a BROKEN declaration as "this
        task simply declares none", which is 12bc's row-2-vs-row-4 rule one
        subsystem over.
        """
        profile = malformed_tidmad_profile()
        assert declares_tidmad_topology(profile), "the sections ARE present"
        with pytest.raises(ValueError):
            project_attempt_topology_facts(profile)

    def test_the_predicate_and_the_decoder_agree_on_TIDMAD(self):
        profile = TIDMAD_PROFILE
        assert declares_tidmad_topology(profile)
        assert tidmad_topology(profile).dataset is not None

    def test_require_physical_dataset_declines_BY_NAME(self):
        facts = AttemptTopologyFacts()
        with pytest.raises(TaskTopologyUnavailableError) as excinfo:
            facts.require_physical_dataset("a worked example")
        message = str(excinfo.value)
        assert "a worked example" in message
        assert "declares none" in message


class TestConsumerSitesReadFacts:
    """The census D2 must drive to zero — direct OR transitive."""

    CONSUMER_MODULES = (
        "planning.py",
        "execution.py",
        "ml_hyperparameter_tune_agent.py",
        "policy.py",
        "records.py",
        "runtime.py",
        "feedback.py",
        "contracts.py",
        "cli.py",
    )

    @pytest.mark.parametrize("module", CONSUMER_MODULES)
    def test_no_consumer_module_decodes_topology_directly(self, module):
        tree = ast.parse((TUNER / module).read_text(encoding="utf-8"))
        decoders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("tidmad_topology", "resolve_tidmad_topology")
        ]
        assert decoders == [], (
            f"{module} decodes TIDMAD topology directly at {decoders}; the "
            f"projection in scope_acquisition.py is the package's ONE decoder."
        )

    def test_the_projection_is_the_single_decoder(self):
        tree = ast.parse((TUNER / "scope_acquisition.py").read_text(encoding="utf-8"))
        decoders = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "tidmad_topology"
        ]
        assert len(decoders) == 1

    def test_the_tuner_no_longer_derives_the_TIDMAD_deliverable_spec(self):
        """B11, the TRANSITIVE blocker, asserted at its own site."""
        source = (TUNER / "ml_hyperparameter_tune_agent.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "derive_tidmad_deliverable_spec" not in calls
        assert "derive_run_deliverable_spec" in calls

    def test_no_task_name_entered_the_projection(self):
        lowered = (TUNER / "scope_acquisition.py").read_text(encoding="utf-8").lower()
        for task in ("pets", "oxford", "davis"):
            assert task not in lowered

    def test_the_legacy_sample_set_builder_is_not_a_composed_task_transport(self):
        """A composed task transports its opaque task-owned scopes only.

        The legacy ``build_sample_set`` remains available to an uncomposed
        caller whose profile declares the old physical geometry.  A composed
        task already owns training and evaluation scopes, so sending the
        legacy sample-set pair beside those scopes creates two authorities and
        the task-generic training engine must refuse it.  This assertion fails
        if planning reintroduces that contradictory transport.
        """
        tree = ast.parse((TUNER / "planning.py").read_text(encoding="utf-8"))
        prepare = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "prepare_attempt"
        )
        guards = [
            ast.unparse(node.test)
            for node in ast.walk(prepare)
            if isinstance(node, ast.If)
            and any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "build_sample_set"
                for call in ast.walk(node)
            )
        ]
        assert guards, "the builder is still called from prepare_attempt"
        assert any(
            "declares_physical_geometry" in guard and "task_composition_ref is None" in guard
            for guard in guards
        ), f"the legacy builder can still run for a composed task: {guards}"

    def test_the_builder_itself_still_fails_closed_without_topology(self):
        """PRESERVED. Its refusal is what makes the guard above necessary."""
        from execute_tools.sample_set_builder import build_sample_set

        with pytest.raises(ValueError, match="declares no TIDMAD topology"):
            build_sample_set(
                is_trial=True,
                trial_strategy="snapshot",
                trial_portion=1.0,
                target_files=None,
                seed=1,
                scope=None,
                profile=contrast_profile(),
            )


class TestDifferentialOracleUnderTidmad:
    """Legacy values arrive BY CONSTRUCTION — nothing observable moved.

    12bc's C1a precedent: sites change shape, the observable stays put. The
    oracle compares the projection's answers against the pre-D2 expressions,
    computed here from the SAME profile.
    """

    def test_the_physical_dataset_is_the_same_object_the_decode_produced(self):
        profile = TIDMAD_PROFILE
        assert (
            project_attempt_topology_facts(profile).physical_dataset
            == tidmad_topology(profile).dataset
        )

    def test_the_legacy_segment_count_is_unchanged(self):
        from nodes.ml_hyperparameter_tune_agent.planning import _psd_segment_counts

        profile = TIDMAD_PROFILE
        facts = project_attempt_topology_facts(profile)
        train, evaluation = _psd_segment_counts(None, None, facts)
        expected = tidmad_topology(profile).dataset.segments_per_file
        assert (train, evaluation) == (expected, expected) == (SEGMENTS_PER_FILE,) * 2

    def test_a_built_sample_set_still_reports_what_it_holds(self):
        from nodes.ml_hyperparameter_tune_agent.planning import _psd_segment_counts

        facts = project_attempt_topology_facts(TIDMAD_PROFILE)
        assert _psd_segment_counts({0: [1, 2], 3: [0]}, {5: [4]}, facts) == (3, 1)

    def test_the_full_scope_reference_volume_is_unchanged(self):
        from agent.prompt_templates.tuner.rendering import (
            render_full_scope_segments,
            render_full_scope_segments_token,
        )

        dataset = tidmad_topology(TIDMAD_PROFILE).dataset
        value = render_full_scope_segments(dataset)
        assert value == NUM_FILES * SEGMENTS_PER_FILE
        assert render_full_scope_segments_token(value) == str(value)

    def test_the_legacy_single_file_notice_is_byte_identical(self):
        from nodes.ml_hyperparameter_tune_agent.planning import _no_sample_set_notice

        assert _no_sample_set_notice("single_file", 6) == "  Legacy mode: file_index=6"

    def test_the_deliverable_spec_is_unchanged_for_a_tidmad_profile(self):
        from execute_tools.deliverable_spec import (
            derive_run_deliverable_spec,
            derive_tidmad_deliverable_spec,
        )

        profile = TIDMAD_PROFILE
        assert derive_run_deliverable_spec(profile) == derive_tidmad_deliverable_spec(profile)

    def test_run_metric_resolution_refuses_an_unbound_run(self):
        from execute_tools.evaluation_metric import NoRunMetricError, resolve_run_metric

        with pytest.raises(NoRunMetricError, match="no metric bound from a task composition"):
            resolve_run_metric()


class TestDeclaredAbsence:
    """A task with no physical geometry SKIPS or DECLINES — never guesses."""

    def test_the_segment_counts_are_None_not_zero(self):
        from nodes.ml_hyperparameter_tune_agent.planning import _psd_segment_counts

        facts = project_attempt_topology_facts(contrast_profile())
        assert _psd_segment_counts(None, None, facts) == (None, None), (
            "an invented 0 would be persisted as a measurement; the record "
            "fields are already `int | None`"
        )

    def test_the_deliverable_spec_is_a_DECLARED_absence(self):
        from execute_tools.deliverable_spec import derive_run_deliverable_spec

        assert derive_run_deliverable_spec(contrast_profile()) is None

    def test_the_full_scope_reference_volume_says_so(self):
        from agent.prompt_templates.tuner.rendering import (
            render_full_scope_segments,
            render_full_scope_segments_token,
        )

        assert render_full_scope_segments(None) is None
        assert render_full_scope_segments_token(None) == "N/A"

    def test_the_no_sample_set_notice_names_the_task_owned_scope(self):
        from nodes.ml_hyperparameter_tune_agent.planning import _no_sample_set_notice

        notice = _no_sample_set_notice("formal", None)
        assert "Task-owned scope" in notice
        assert "Legacy mode" not in notice

    def test_the_task_render_composes_without_physical_geometry(self):
        """The fifth site, exercised through its real authority."""
        from types import SimpleNamespace

        from agent.prompt_templates.tuner.rendering import build_tuner_task_render

        render = build_tuner_task_render(
            dataset=project_attempt_topology_facts(contrast_profile()).physical_dataset,
            model_io_contract=None,
            # `render_gate_name_tokens` reads `.health_gates`; a task with no
            # declared Health family is 08b's EXPLICIT_NONE and contributes no
            # gate names. Only the dataset half is under test here.
            health_config=SimpleNamespace(health_gates=()),
            efficiency_band_fraction=0.1,
        )
        assert render.full_scope_segments is None
        assert render.gate_check_names == ()


class TestFailClosed:
    """The two frozen falsifiers."""

    def test_a_composed_run_with_an_unbound_binding_FAILS_CLOSED(self):
        """FALSIFIER 1. Falling back to TIDMAD's facts here is C-P56-1."""
        from nodes.ml_hyperparameter_tune_agent.scope_acquisition import (
            acquire_attempt_scopes,
        )

        with pytest.raises(RuntimeError, match="no resolvable task data path"):
            acquire_attempt_scopes(
                composed=True,
                mode="formal",
                trial_strategy="snapshot",
                trial_portion=1.0,
                eval_strategy="snapshot",
                eval_portion=1.0,
                train_sampling_seed=None,
                eval_sampling_seed=None,
                target_files=None,
                subset=None,
                validation_max_samples=None,
                task_parameters={},
            )

    def test_a_skip_is_NAMED_not_a_silent_pass(self):
        """FALSIFIER 2. The peek's target resolver declines, it does not lie.

        A check that genuinely asks for a raw validation-file path under a
        task with no such concept must be told so — never handed a fabricated
        filename that would then fail to open somewhere less informative.
        """
        facts = project_attempt_topology_facts(contrast_profile())
        with pytest.raises(TaskTopologyUnavailableError) as excinfo:
            facts.require_physical_dataset("resolving a raw validation-file path for a Health peek")
        assert "Health peek" in str(excinfo.value)

    def test_the_channel_identity_and_encoding_are_untouched_by_the_projection(self):
        """The projection carries the DATASET half only.

        Recorded because the temptation is to widen it to the whole
        ``TidmadTopology``: nothing in the five consumer sites asks for
        channels or encoding, and a carrier that offered them would invite the
        next site to take a topology dependency the projection was created to
        remove.
        """
        assert set(AttemptTopologyFacts.model_fields) == {"physical_dataset"}
        assert isinstance(tidmad_topology(TIDMAD_PROFILE).channels, ChannelIdentity)
        assert isinstance(tidmad_topology(TIDMAD_PROFILE).encoding, ValueEncoding)
