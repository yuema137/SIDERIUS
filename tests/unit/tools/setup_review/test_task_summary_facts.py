"""Composition-child Task summary facts and job identity."""

from types import SimpleNamespace

import pytest

from execute_tools.dataset_config import DatasetProfile
from execute_tools.health_checks._composition import HealthBindingState
from execute_tools.health_checks.roster_projection import HealthRosterProjection
from execute_tools.task_data_path import StorageReadScope
from tools.setup_review.composition_check import observe_composition
from tools.setup_review.composition_models import (
    CHILD_RESULT_NAME,
    CandidateCheckOptions,
    CompositionJob,
    CompositionResult,
    DataScopeFacts,
    SampleCountFacts,
    TaskCheckSettings,
    TaskCompositionSummary,
    TaskPackageFacts,
    TaskSummaryRequest,
)
from tools.setup_review.composition_transport import read_composition_result
from tools.setup_review.package_facts import BASIS, project_package_facts


def _job(**extra) -> CompositionJob:
    return CompositionJob(
        manifest="/abs/task.yaml",
        manifest_sha256="a" * 64,
        planner_strategy=None,
        scratch="/abs/scratch/x",
        settings=TaskCheckSettings(timeout_seconds=30),
        **extra,
    )


def test_jobs_without_a_summary_keep_their_pinned_digests():
    """Defect: the optional summary field serializes when absent, changing every
    existing check/candidate job digest and orphaning recorded observations.
    Digests pinned at origin/master cd4460dfa before the field existed."""
    assert _job().digest == "943a23d44e266b372e08b2dbd459ffb792994194094f388ec7f7eaa8be2a6ced"
    candidate = _job(candidate_check=CandidateCheckOptions(allowed_output_types=None))
    assert (
        candidate.model_copy(update={"planner_strategy": "p"}).digest
        == "02ee8f7e24de17041c684242e7e5f4a7197d363add0763e194e22bbc052e7659"
    )
    summary = _job(summary=TaskSummaryRequest(data_root="/abs/data"))
    assert summary.digest != _job().digest
    assert '"count_samples"' not in summary.model_dump_json()


class _ScopedTask:
    """Builds scopes; ``storage_read_scope`` is attached per test."""

    task_data_path_id = "stub"

    def build_training_scope(self, request):
        return ("train", request.round_kind)

    def build_eval_scope(self, request):
        return ("eval", request.round_kind)

    def serialize_scope(self, scope):
        return repr(scope)

    def deserialize_scope(self, payload):
        raise NotImplementedError


class _StorageTask(_ScopedTask):
    def storage_read_scope(self, data_dir, scope):
        count = 2 if scope[0] == "train" else 1
        files = tuple(f"{data_dir}/{scope[0]}{index}" for index in range(count))
        return StorageReadScope(file_paths=files, expected_on_disk_bytes=100 * count)


def _composition(impl):
    return SimpleNamespace(
        task_data_path=impl,
        dataset_profile=DatasetProfile(
            partition_count=1, anchor_selection_files=[0], health_peek_files=[0]
        ),
        task_health_binding=HealthBindingState.EXPLICIT_NONE,
        objective=None,
        deliverable_naming=None,
        model_plugins=None,
        metric=object(),
        secondary_metrics=(),
    )


def test_storage_volume_is_reported_only_when_the_task_declares_it(tmp_path):
    """Defect: a task without ``storage_read_scope`` shown as 0 files/bytes, or a
    declaring task's formal-scope volume dropped or swapped between legs."""
    request = TaskSummaryRequest(data_root=str(tmp_path))
    undeclared = project_package_facts(_composition(_ScopedTask()), request).scopes
    assert undeclared.state == "not_declared"
    assert (undeclared.training, undeclared.evaluation) == (None, None)

    declared = project_package_facts(_composition(_StorageTask()), request)
    assert declared.scopes.state == "declared"
    assert declared.scopes.training is not None and declared.scopes.evaluation is not None
    assert (
        declared.scopes.training.file_count,
        declared.scopes.training.expected_on_disk_bytes,
    ) == (2, 200)
    assert declared.scopes.evaluation.file_count == 1
    assert declared.sample_counts is None
    assert declared.objective is None and declared.health.declaration == "explicit_none"


def test_quickstart_counts_describe_the_full_declared_split(tmp_path):
    """Defect: the Task panel reports one run's sampled workload (e.g. the formal
    training portion 0.1 -> 12 rows) instead of the task's declared split: the
    quickstart declares two 64-row training shards and one 64-row evaluation shard."""
    import sys
    from pathlib import Path

    from workflows.task_composition import compose_run_task_bindings

    repo = Path(__file__).resolve().parents[4]
    plugins = str(repo / "examples/quickstart/plugins")
    sys.path.insert(0, plugins)
    try:
        from _quickstart_task import write_data_dir
    finally:
        sys.path.remove(plugins)
    write_data_dir(tmp_path)
    composition = compose_run_task_bindings(str(repo / "configs/task_composition/quickstart.yaml"))
    facts = project_package_facts(
        composition, TaskSummaryRequest(data_root=str(tmp_path), count_samples=True)
    )
    assert facts.sample_counts is not None
    assert (facts.sample_counts.training, facts.sample_counts.evaluation) == (128, 64)
    assert facts.scopes.basis.startswith("Full task split")


def _passed(job: CompositionJob, package: TaskPackageFacts | None) -> CompositionResult:
    task = TaskCompositionSummary(
        semantic_fingerprint="b" * 64,
        task_data_path_id="stub",
        task_config={},
        dataset_profile={},
        primary_metric={},
        secondary_metrics=[],
        parameter_rules={},
        inference_preflight={},
        source_paths={},
        plugins=[],
        code_package_identity=None,
        prompt_renderer_identity=None,
        preflight_estimator_identity={},
        data_analysis_identity=None,
        task_health_declaration="explicit_none",
    )
    return CompositionResult(
        request_sha256=job.digest,
        manifest_sha256=job.manifest_sha256,
        outcome="passed",
        task=task,
        planner_strategy_identity={},
        package=package,
    )


def _facts(counts: SampleCountFacts | None) -> TaskPackageFacts:
    return TaskPackageFacts(
        health=HealthRosterProjection(declaration="explicit_none", gates=()),
        objective=None,
        deliverable=None,
        model_plugins=(),
        implementation_sources={},
        scopes=DataScopeFacts(state="not_declared", basis=BASIS),
        sample_counts=counts,
    )


@pytest.mark.parametrize(
    ("summary", "package", "match"),
    [
        (None, _facts(None), "task summary"),
        (TaskSummaryRequest(data_root="/abs/data"), None, "task summary"),
        (
            TaskSummaryRequest(data_root="/abs/data"),
            _facts(SampleCountFacts(state="counted", training=1, evaluation=1)),
            "sample count",
        ),
        (
            TaskSummaryRequest(data_root="/abs/data", count_samples=True),
            _facts(None),
            "sample count",
        ),
    ],
)
def test_transport_refuses_package_facts_that_do_not_match_the_request(
    tmp_path, summary, package, match
):
    """Defect: a child result with unrequested (or missing) package facts or sample
    counts is accepted, so the console shows facts nobody asked the child for."""
    job = _job(summary=summary).model_copy(update={"scratch": str(tmp_path)})
    (tmp_path / CHILD_RESULT_NAME).write_text(_passed(job, package).model_dump_json())
    with pytest.raises(ValueError, match=match):
        read_composition_result(job)


def test_observation_validates_the_data_root_it_mounts(tmp_path):
    """Defect: the caller's data_root is validated while the sandbox mounts the job's
    own summary data_root, so an unvalidated root could be exposed to task code."""
    manifest = tmp_path / "task.yaml"
    manifest.write_text("synthetic: true\n")
    (tmp_path / "data").mkdir()
    job = CompositionJob(
        manifest=str(manifest),
        manifest_sha256="a" * 64,
        planner_strategy=None,
        scratch=str(tmp_path / "scratch"),
        settings=TaskCheckSettings(timeout_seconds=1),
        summary=TaskSummaryRequest(data_root=str(tmp_path / "data")),
    )
    with pytest.raises(ValueError, match="differs from the task-summary job"):
        observe_composition(job, (tmp_path,), data_root=tmp_path / "other")
    assert not (tmp_path / "scratch").exists()
