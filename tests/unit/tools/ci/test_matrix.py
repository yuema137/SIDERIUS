"""Bulk-lane matrix split — the properties whose violation looks like a green run.

Splitting one shard plan across CI jobs (issue #990) can lose work in ways a
single job could not: a strided assignment that skips an index, jobs planning
different file sets, a missing matrix entry, an empty shard that silently runs
the whole tree. Each test names one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ci import execution
from tools.ci.matrix import (
    REPORT_NAME,
    job_report,
    job_shard_indices,
    main,
    plan_digest,
    verify_reports,
)
from tools.ci.shards import Shard, ShardPlan, plan_shards

FILES = [f"tests/unit/{d}/test_{i}.py" for d in ("agent", "core", "nodes") for i in range(9)]
SENSITIVE = ["tests/unit/core/test_3.py"]


class TestJobAssignment:
    @pytest.mark.parametrize(("shards", "jobs"), [(8, 4), (7, 3), (5, 5), (4, 1)])
    def test_jobs_partition_the_unsharded_selection(self, shards: int, jobs: int):
        """The union of every job's files is the selection, each file once.

        Covers counts that do not divide evenly, where an off-by-one stride
        drops the trailing shard. Fails as: a file is executed by no job or by
        two, while each job individually reports green.
        """
        weights = {f: float(len(f) % 7 + 1) for f in FILES}
        plan = plan_shards(FILES, count=shards, sensitive=SENSITIVE, weights=weights)
        executed: list[str] = []
        for job in range(jobs):
            mine = job_shard_indices(shards, jobs, job)
            executed.extend(f for s in plan.shards if s.index in mine for f in s.files)
        assert len(executed) == len(set(executed))
        assert sorted(executed) == sorted(set(FILES) - set(SENSITIVE))

    def test_more_jobs_than_shards_is_refused(self):
        """A job with no shard would report green having executed nothing.

        Fails as: job_count > shard_count yields an empty assignment instead of
        an error, so a matrix/shard-count drift passes silently.
        """
        with pytest.raises(ValueError, match="exceeds"):
            job_shard_indices(2, 3, 2)

    def test_the_cli_refuses_an_invalid_split_before_running_anything(self):
        """The harness wiring must apply the same refusal.

        Fails as: ``tools.ci`` accepts ``--job-index`` outside ``--job-count``
        and plans a run whose report can never be verified.
        """
        from tools.ci.__main__ import main as ci_main

        with pytest.raises(SystemExit) as exc:
            ci_main(["plan", "--shards", "4", "--job-index", "4", "--job-count", "4"])
        assert exc.value.code == 2


def _green(job: int, *, jobs: int = 2, shards: int = 4, digest: str = "d") -> dict[str, object]:
    return job_report(
        job_index=job,
        job_count=jobs,
        shard_count=shards,
        digest=digest,
        shards_run=list(job_shard_indices(shards, jobs, job)),
        ok=True,
        full_suite=True,
        files=10,
    )


class TestAggregateVerification:
    def test_a_whole_green_matrix_verifies(self):
        assert verify_reports([_green(1), _green(0)]) == []

    def test_a_missing_job_is_reported(self):
        """A matrix entry dropped from the workflow leaves shards unrun.

        Fails as: verification checks only the reports present, so shards 1
        and 3 (job 1's) are never executed and the aggregate is green.
        """
        problems = verify_reports([_green(0)])
        assert any("executed by no job: [1, 3]" in p for p in problems)

    def test_jobs_that_planned_differently_are_reported(self):
        """Two runners computing different plans is a silent coverage hole.

        Fails as: digests are not compared, so job 0's shards and job 1's
        shards come from different partitions of the selection.
        """
        problems = verify_reports([_green(0, digest="a"), _green(1, digest="b")])
        assert any("disagree on plan_digest" in p for p in problems)

    def test_a_red_job_fails_the_aggregate(self):
        red = {**_green(1), "ok": False}
        assert any("job 1" in p for p in verify_reports([_green(0), red]))

    def test_a_job_that_ran_the_wrong_shards_is_reported(self):
        """Fails as: a job executing a sibling's shards is accepted, so one
        shard runs twice and its own assigned shard never runs."""
        wrong = {**_green(1), "shards_run": [0, 2]}
        problems = verify_reports([_green(0), wrong])
        assert any("more than one job" in p for p in problems)
        assert any("executed by no job" in p for p in problems)

    def test_a_boolean_index_is_malformed_not_job_one(self):
        """``True == 1`` in Python; a corrupted report must not pass as job 1."""
        corrupt = {**_green(1), "job_index": True}
        assert any("malformed" in p for p in verify_reports([_green(0), corrupt]))

    def test_the_digest_covers_placement_not_only_membership(self):
        """Fails as: the digest hashes only the file set, so two plans that
        place the same files in different shards look identical."""
        a = plan_digest([(0, ["x.py"]), (1, ["y.py"])], [])
        b = plan_digest([(0, ["y.py"]), (1, ["x.py"])], [])
        assert a != b


class TestVerifyEntrypoint:
    def test_reports_nested_per_artifact_are_found(self, tmp_path: Path):
        """download-artifact puts each artifact in its own sub-directory.

        Fails as: discovery globs only the top level, finds nothing and the
        aggregate turns RED on every green run (or, if "no reports" were ever
        treated as success, green on every run).
        """
        for job in (0, 1):
            target = tmp_path / f"ci-parity-evidence-bulk-{job}"
            target.mkdir()
            (target / REPORT_NAME).write_text(json.dumps(_green(job)), encoding="utf-8")
        assert main(["verify", "--reports-dir", str(tmp_path)]) == 0

    def test_no_reports_is_red(self, tmp_path: Path):
        assert main(["verify", "--reports-dir", str(tmp_path)]) == 1


class TestEmptyShards:
    def test_an_empty_shard_never_launches_pytest(self, tmp_path: Path, monkeypatch):
        """pytest with no path arguments runs the configured testpaths.

        A narrow selection planned over more shards than it has files leaves
        empty shards; launching one would run the whole tree, integration
        included. Fails as: run_shard is invoked with no files.
        """
        calls: list[tuple[int, tuple[str, ...]]] = []

        def fake_run_shard(root, index, files, **_kw):
            calls.append((index, tuple(files)))
            return execution.ShardResult(
                index=index, files=tuple(files), returncode=0, duration_s=0.0, tmpdir=""
            )

        monkeypatch.setattr(execution, "run_shard", fake_run_shard)
        plan = ShardPlan(
            shards=[
                Shard(index=0, files=("tests/unit/a/test_a.py",), weight=1.0),
                Shard(index=1, files=(), weight=0.0),
            ]
        )
        result = execution.run_bulk(
            tmp_path / "root", plan, sha="s", workdir=tmp_path / "work", threads=1
        )
        assert calls == [(0, ("tests/unit/a/test_a.py",))]
        assert [s.index for s in result.shards] == [0, 1]
        assert result.ok


class TestDeclaredProfile:
    def test_a_smaller_matrix_than_declared_is_refused(self):
        """A consistent report set from the wrong profile is not the declared run.

        Fails as: one job planning one shard (say, the workflow's matrix
        shrank to ``[0]`` and the job ran with ``--job-count 1``) verifies as
        whole while the declared 4-job/8-shard profile never executed.
        """
        lone = _green(0, jobs=1, shards=1)
        assert verify_reports([lone]) == []
        problems = verify_reports([lone], expect_jobs=4)
        assert any("the workflow declares 4" in p for p in problems)

    def test_a_different_shard_count_than_declared_is_refused(self):
        """Fails as: jobs that all planned 4 shards pass a workflow declaring 8."""
        reports = [_green(0), _green(1)]
        assert verify_reports(reports, expect_jobs=2, expect_shards=4) == []
        problems = verify_reports(reports, expect_jobs=2, expect_shards=8)
        assert any("the workflow declares 8" in p for p in problems)

    def test_the_cli_passes_the_declared_profile_through(self, tmp_path: Path):
        """Fails as: --expect-jobs / --expect-shards are parsed but ignored."""
        for job in (0, 1):
            (tmp_path / f"r{job}").mkdir()
            (tmp_path / f"r{job}" / REPORT_NAME).write_text(json.dumps(_green(job)))
        base = ["verify", "--reports-dir", str(tmp_path)]
        assert main([*base, "--expect-jobs", "2", "--expect-shards", "4"]) == 0
        assert main([*base, "--expect-jobs", "4"]) == 1
        assert main([*base, "--expect-shards", "8"]) == 1


class TestEmptyUniverse:
    def test_verify_refuses_a_full_suite_of_zero_files(self):
        """Every shard of an empty plan is trivially green.

        Fails as: a checkout where no tracked test file is visible produces
        four green jobs and a green aggregate having executed nothing.
        """
        empty = [{**_green(0), "files": 0}, {**_green(1), "files": 0}]
        assert any("zero test files" in p for p in verify_reports(empty))

    def test_the_harness_refuses_a_full_suite_of_zero_files(self, monkeypatch):
        """Fails as: the harness plans and runs empty shards instead of exiting."""
        from tools.ci import __main__ as ci_main
        from tools.ci.selection import Selection

        monkeypatch.setattr(
            ci_main, "resolve_selection", lambda root, changed: Selection((), True, "empty")
        )
        assert ci_main.main(["plan", "--shards", "8", "--job-count", "4"]) == 2


class TestAggregateWorkflowVerdict:
    """The aggregate job IS the status reviewers read; its logic is pinned here.

    Fails as: the final step loses ``always()`` (a failed upstream job leaves
    it skipped, which GitHub treats as passing), stops requiring success of a
    lane (e.g. ``== "failure"`` lets a CANCELLED lane through), or the matrix
    verification step disappears or stops receiving the declared profile.
    """

    @staticmethod
    def _workflow() -> dict:
        import yaml

        root = Path(__file__).resolve().parents[4]
        return yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))

    def test_the_final_step_requires_every_lane_to_succeed(self):
        steps = self._workflow()["jobs"]["quality"]["steps"]
        final = steps[-1]
        assert final["if"] == "always()"
        for lane in ("prepare", "unit", "sensitive"):
            assert f'"${{{{ needs.{lane}.result }}}}" != "success"' in final["run"], lane

    def test_the_aggregate_verifies_the_declared_matrix(self):
        wf = self._workflow()
        runs = [step.get("run", "") for step in wf["jobs"]["quality"]["steps"]]
        verify = [run for run in runs if "src/tools/ci/matrix.py verify" in run]
        assert len(verify) == 1
        assert '--expect-jobs "$CI_BULK_JOBS"' in verify[0]
        assert '--expect-shards "$CI_BULK_SHARDS"' in verify[0]
        jobs = int(wf["env"]["CI_BULK_JOBS"])
        assert wf["jobs"]["unit"]["strategy"]["matrix"]["job"] == list(range(jobs))
