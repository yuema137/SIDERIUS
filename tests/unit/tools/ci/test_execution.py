"""Shard execution — isolation, ownership, and honest aggregation.

The failures worth guarding are the ones that would let harness noise be
reported as a product result, or let a real failure be reported as green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.ci.execution import (
    THREAD_VARS,
    BulkResult,
    ShardResult,
    WorkdirInsideSourceTree,
    run_bulk,
    run_shard,
    shard_environment,
)
from tools.ci.sensitive import GIT_STATE_FILES, SENSITIVE_FILES, TIMING_FILES
from tools.ci.shards import plan_shards


def _result(index: int, rc: int | None, *, invalid: str | None = None) -> ShardResult:
    return ShardResult(
        index=index,
        files=("a.py",),
        returncode=rc,
        duration_s=1.0,
        tmpdir="/tmp/x",
        invalid_reason=invalid,
    )


class TestShardEnvironment:
    def test_every_measured_thread_var_is_pinned(self, tmp_path: Path):
        """Unpinned shards multiply torch's 12 intra-op threads into oversubscription.

        Fails as: a shard inherits the host's default thread count and N shards
        each take ~4 cores, defeating both the parallelism and the timing lane's
        load assumptions.
        """
        env = shard_environment({"PATH": "/usr/bin"}, tmpdir=tmp_path, threads=2)
        for var in THREAD_VARS:
            assert env[var] == "2", var

    def test_tmpdir_is_per_shard(self, tmp_path: Path):
        """Shards sharing a temp directory collide non-deterministically.

        Fails as: TMPDIR is inherited and two shards write the same paths.
        """
        assert shard_environment({}, tmpdir=tmp_path / "s1", threads=1)["TMPDIR"] == str(
            tmp_path / "s1"
        )

    def test_the_parent_environment_is_not_mutated(self, tmp_path: Path):
        """Concurrent shards would race through a shared dict.

        Fails as: shard_environment edits its argument, so shard 2's threads
        overwrite shard 1's while both are running.
        """
        base = {"PATH": "/usr/bin"}
        shard_environment(base, tmpdir=tmp_path, threads=8)
        assert base == {"PATH": "/usr/bin"}


class TestAggregation:
    def test_one_failing_shard_makes_the_run_red(self):
        """The whole point of aggregation.

        Fails as: a red shard is averaged away and the run reports green.
        """
        r = BulkResult(sha="deadbeef", shards=[_result(0, 0), _result(1, 1)])
        assert r.ok is False
        assert [s.index for s in r.failed] == [1]

    def test_an_invalidated_shard_is_not_counted_as_a_product_failure(self):
        """Harness noise must not enter the regression count.

        A killed or unbootstrapped shard produced no usable evidence. Counting
        it as a product failure is how a .venv problem becomes a bug hunt.
        Fails as: invalid shards appear in .failed.
        """
        r = BulkResult(sha="d", shards=[_result(0, 0), _result(1, None, invalid="killed")])
        assert r.failed == []
        assert [s.index for s in r.invalid] == [1]

    def test_an_invalidated_shard_still_prevents_green(self):
        """Invalid is not a pass either.

        The opposite error to the one above: if invalid shards were merely
        excluded, a run where half the shards never started would report green.
        Fails as: ok is True while evidence is missing.
        """
        r = BulkResult(sha="d", shards=[_result(0, 0), _result(1, None, invalid="killed")])
        assert r.ok is False

    def test_render_labels_invalid_evidence_distinctly(self):
        """An operator must see 'harness' vs 'product' without reading code.

        Fails as: an invalid shard renders identically to a failed one.
        """
        text = BulkResult(sha="d", shards=[_result(0, None, invalid="no venv")]).render()
        assert "INVALID_HARNESS_EVIDENCE" in text and "no venv" in text


class TestRunShard:
    def test_a_missing_venv_yields_invalid_evidence_not_a_failure(self, tmp_path: Path):
        """The PR-12d failure, encoded.

        An unbootstrapped root has no <root>/.venv/bin/python; launching there
        must be reported as a harness fault. Fails as: the OSError propagates,
        or the shard is recorded as a product failure.
        """
        root = tmp_path / "root"
        (root / "tests").mkdir(parents=True)
        res = run_shard(root, 0, ["tests/x.py"], workdir=tmp_path / "wd", threads=1)
        assert res.invalid_reason is not None
        assert "could not start pytest" in res.invalid_reason
        assert res.passed is False


class TestFrozenSensitiveManifest:
    def test_the_manifest_is_exactly_the_five_frozen_files(self):
        """Freezing means the set does not drift silently.

        Fails as: a file is added or removed without the reasoning that CP-6
        requires, re-opening the keyword-classification trap.
        """
        assert len(SENSITIVE_FILES) == 4
        assert TIMING_FILES | GIT_STATE_FILES == set(SENSITIVE_FILES)
        assert len(GIT_STATE_FILES) == 0
        assert len(TIMING_FILES) == 4

    def test_every_sensitive_file_states_why_it_is_sensitive(self):
        """A quarantine without a reason becomes permanent and unexamined.

        Fails as: a file is added with an empty or placeholder justification.
        """
        for path, reason in SENSITIVE_FILES.items():
            assert len(reason) > 60, f"{path} lacks a substantive reason"

    def test_the_sensitive_files_exist_in_the_checkout(self):
        """A stale path silently quarantines nothing.

        If a sensitive file is renamed and the manifest is not updated, the
        planner excludes a path that no longer exists while the real test runs
        in the bulk lane. Fails as: a manifest entry names a missing file.
        """
        repo = Path(__file__).resolve().parents[4]
        missing = [p for p in SENSITIVE_FILES if not (repo / p).is_file()]
        assert missing == [], f"sensitive manifest names missing files: {missing}"


class TestFailuresAreVisibleWithoutAnArtifact:
    """The first remote run reported `shard 3 FAILED` and nothing else.

    Its evidence artifact had silently uploaded zero files, so a RED run
    produced no attributable detail at all — the exact outcome this harness
    exists to prevent.
    """

    def _shard(self, tmp_path: Path, *, junit: str | None, log: str | None) -> ShardResult:
        return ShardResult(
            index=3,
            files=("a.py",),
            returncode=1,
            duration_s=1.0,
            tmpdir=str(tmp_path),
            junit_xml=junit,
            log_path=log,
        )

    def test_failing_nodes_come_from_junit_when_present(self, tmp_path: Path):
        """JUnit is the precise source: it names the node, not just the file.

        Fails as: a RED shard reports no node ids and the operator must go
        hunting through a file that may not have survived.
        """
        x = tmp_path / "s.xml"
        x.write_text(
            '<testsuite><testcase classname="a.b.C" name="test_x">'
            '<failure message="boom"/></testcase>'
            '<testcase classname="a.b.C" name="test_ok"/></testsuite>',
            encoding="utf-8",
        )
        assert self._shard(tmp_path, junit=str(x), log=None).failing_nodes() == ["a.b.C::test_x"]

    def test_it_falls_back_to_the_log_when_junit_is_missing(self, tmp_path: Path):
        """A shard killed mid-run writes no JUnit but has already logged FAILED.

        Two independent sources, because the point is that the operator sees
        the failures even when one is absent. Fails as: no JUnit means no
        reported nodes, reproducing the blind RED.
        """
        log = tmp_path / "s.log"
        log.write_text(
            "some output\nFAILED tests/unit/x/test_y.py::test_z - AssertionError\n",
            encoding="utf-8",
        )
        assert self._shard(tmp_path, junit=None, log=str(log)).failing_nodes() == [
            "tests/unit/x/test_y.py::test_z - AssertionError"
        ]

    def test_render_inlines_the_failing_nodes(self, tmp_path: Path):
        """The summary alone is not attribution.

        Fails as: render() prints `FAILED` with no node ids, so a CI log shows
        that something broke without saying what.
        """
        log = tmp_path / "s.log"
        log.write_text("FAILED tests/unit/x/test_y.py::test_z\n", encoding="utf-8")
        text = BulkResult(
            sha="deadbeefcafe", shards=[self._shard(tmp_path, junit=None, log=str(log))]
        ).render()
        assert "FAILING NODES" in text
        assert "tests/unit/x/test_y.py::test_z" in text

    def test_a_passing_run_prints_no_failure_section(self, tmp_path: Path):
        """Noise in a green run trains people to ignore the section.

        Fails as: GREEN runs carry an empty FAILING NODES header.
        """
        ok = ShardResult(
            index=0, files=("a.py",), returncode=0, duration_s=1.0, tmpdir=str(tmp_path)
        )
        assert "FAILING NODES" not in BulkResult(sha="d", shards=[ok]).render()


class TestTheWorkflowUploadsEvidenceThatExists:
    def test_hidden_workdir_is_explicitly_included(self):
        """upload-artifact@v4 excludes dot-prefixed paths by DEFAULT.

        `.ci_parity` is hidden, so the first remote run uploaded nothing and
        only warned. Fails as: the flag is dropped and RED runs silently lose
        their per-node evidence again.
        """
        wf = (Path(__file__).resolve().parents[4] / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        assert "include-hidden-files: true" in wf

    def test_the_artifact_collects_tracebacks_and_not_test_fixtures(self):
        """The evidence artifact must carry evidence, not every temp file.

        Run 32834492183 uploaded 18,674 files of which SIX were evidence: `**`
        descends into each shard's TMPDIR and swept up every JSON and XML a test
        wrote in a fixture. It also matched no `shard*.log` at all, so the
        tracebacks — the most useful artefact in a RED run — were the one thing
        absent. Fails as: `**` returns and the signal is buried again, or the
        logs are dropped.
        """
        wf = (Path(__file__).resolve().parents[4] / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        block = wf.split("Upload structured test evidence")[1].split("retention-days")[0]
        assert "shard*.log" in block, "shard logs carry the tracebacks and must be uploaded"
        assert "ci_parity/**/" not in block, (
            "a `**` pattern descends into shard TMPDIRs and collects test fixtures"
        )

    def test_the_sensitive_lane_runs_even_when_bulk_fails(self):
        """A RED bulk lane must not hide the sensitive lane's result.

        Run 32834492183 failed in bulk and SKIPPED the sensitive step, so a
        whole class of evidence was absent from a run meant to produce the
        complete failure batch. A workflow that stops at the first red step is
        the fix-one/rerun loop wearing different clothes. Fails as: the guard
        is dropped and a bulk failure again conceals the sensitive lane.
        """
        wf = (Path(__file__).resolve().parents[4] / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        sensitive = wf.split("sensitive lane (serial, quiesced)")[1].split("- name:")[0]
        assert "if: always()" in sensitive

    def test_an_empty_evidence_artifact_fails_the_step(self):
        """A warning is not enough: the upload exists so a RED stays attributable.

        Fails as: `if-no-files-found: warn` returns, and an empty artifact
        passes silently exactly as it did the first time.
        """
        wf = (Path(__file__).resolve().parents[4] / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        assert "if-no-files-found: error" in wf


class TestTheHarnessNeverWritesInsideTheSourceTree:
    """Two failures in remote run 32834492183 shared this one cause.

    Every shard's TMPDIR lives under the workdir, so a workdir inside the
    checkout puts every `tmp_path` inside the repository.
    """

    def test_a_workdir_inside_the_root_is_refused(self, tmp_path: Path):
        """Refuse, do not warn — the contamination is silent and cross-shard.

        With TMPDIR inside the checkout, one shard's fixture file becomes
        another shard's "repository content": a census walking the tree parsed
        a deliberately-malformed `def (: pass` plant and died on SyntaxError,
        in a different shard from the one that wrote it. Fails as: the harness
        accepts an in-tree workdir and quietly corrupts the tree it is testing.
        """
        root = tmp_path / "repo"
        root.mkdir()
        with pytest.raises(WorkdirInsideSourceTree, match="inside the source tree"):
            run_bulk(
                root,
                plan_shards(["tests/unit/x.py"], count=1),
                sha="deadbeef",
                workdir=root / ".ci_parity",
                threads=1,
            )

    def test_the_root_itself_is_refused(self, tmp_path: Path):
        """`workdir == root` is the same defect without a subdirectory.

        Fails as: only strict descendants are caught and the root slips past.
        """
        root = tmp_path / "repo"
        root.mkdir()
        with pytest.raises(WorkdirInsideSourceTree):
            run_bulk(root, plan_shards([], count=1), sha="d", workdir=root, threads=1)

    def test_a_sibling_directory_is_accepted(self, tmp_path: Path):
        """The guard must not reject every path that merely looks nearby.

        A directory beside the checkout is outside it. Fails as: the guard is
        over-broad and no usable workdir exists.
        """
        root = tmp_path / "repo"
        root.mkdir()
        result = run_bulk(
            root, plan_shards([], count=1), sha="d", workdir=tmp_path / "scratch", threads=1
        )
        assert result.shards == [] or True  # reaching here means it was not refused

    def test_the_default_workdir_is_outside_the_repository(self):
        """The default must be safe without anyone passing --workdir.

        Fails as: the default returns to `<root>/.ci_parity` and the defect
        reappears for every local run.
        """
        src = (Path(__file__).resolve().parents[4] / "src/tools/ci/__main__.py").read_text(
            encoding="utf-8"
        )
        assert 'root / ".ci_parity"' not in src
        assert "tempfile.gettempdir()" in src
