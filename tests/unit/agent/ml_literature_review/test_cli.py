"""CLI entry point for the ml_literature_review node — issue #303.

Covers the standalone surface this issue added: the flag surface, the three
DISTINCT experiment-history ingestion refusals, the naming-convention default
and the explicit ``--experiment-history`` override exercised through the REAL
``main()`` (production entry point; only the agent is stubbed), and the empty-bottlenecks synthesis render this issue
established.

Flow-only per the repo testing standard: no real LLM, no network, no disk
outside ``tmp_path``. This file imports privates of the node under test only
(its own test suite — same as ``test_node.py``); no other node's privates are
touched (node public-boundary rule).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

import nodes.ml_literature_review as node_mod
from agent.prompt_templates.literature_review import render_synthesis_prompt
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import LiteratureReviewInput, LiteratureReviewOutput
from agent.schemas.protocols.interpreter_to_ml_literature_review import local_typed_evidence

_REPO_ROOT = Path(__file__).resolve().parents[4]
_REQUIRED_ARGS = [
    "--lit_review_config",
    "/task/literature.yaml",
    "--task_composition",
    "/task/composition.yaml",
    "--data_dir",
    "/task/data",
]


def _task_args(tmp_path: Path, description: str = "fixture task") -> list[str]:
    """Real synthetic contract, including normalized model-I/O validation."""
    import yaml

    # Retain the declared plugin ref: it participates in the existing registry
    # identity. Relocating the package root must not invent a conflicting module.
    pack = tmp_path / "examples/quickstart"
    shutil.copytree(_REPO_ROOT / "examples/quickstart", pack)
    task_config = pack / "declared/task_config.yaml"
    config = yaml.safe_load(task_config.read_text())
    config["task_description"] = description
    task_config.write_text(yaml.safe_dump(config))
    manifest = tmp_path / "composition.yaml"
    manifest.write_text(
        (_REPO_ROOT / "configs/task_composition/quickstart.yaml")
        .read_text()
        .replace("../../examples/quickstart/", "examples/quickstart/")
    )
    data = tmp_path / "data"
    data.mkdir()
    return ["--task_composition", str(manifest), "--data_dir", str(data)]


@pytest.fixture(autouse=True)
def _restore_cli_workspace_environment(monkeypatch):
    """The workspace owner writes an environment binding; isolate each CLI test."""
    import os

    for key in ("SIDERIUS_GENERATED_LIBRARY_DIR", "SIDERIUS_CHAIN_WORKSPACE"):
        if key in os.environ:
            monkeypatch.setenv(key, os.environ[key])
        else:
            monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _history(**over) -> InterpretationOutput:
    """A minimal valid InterpretationOutput (same shape as the PB-9 goldens)."""
    base = dict(
        model_types=["wavenet"],
        model_descriptions={"wavenet": "d"},
        total_experiments=3,
        key_findings=["kf1"],
        bottlenecks=["b1"],
        take_home_message="thm",
    )
    return InterpretationOutput(**{**base, **over})


# ---------------------------------------------------------------------------
# Ingestion refusals — load_experiment_history
# ---------------------------------------------------------------------------


class TestExperimentHistoryIngestion:
    def test_missing_file_refuses_with_remediation(self, tmp_path):
        """Defect only this catches: the missing-file refusal losing its
        operator remediation. Deleting the explicit exists() guard still
        raises a builtin FileNotFoundError from the read, so the exception
        TYPE alone cannot pin the contract — this asserts the message names
        the path and the upstream node to run. Fails: the remediation text
        or the path disappears from the message."""
        missing = tmp_path / "interpretation_v1.json"
        with pytest.raises(FileNotFoundError) as excinfo:
            node_mod.load_experiment_history(missing)
        assert str(missing) in str(excinfo.value)
        assert "result_interpretation_agent" in str(excinfo.value)

    def test_invalid_json_refuses_distinctly(self, tmp_path):
        """Defect only this catches: a corrupt/truncated upstream dump
        surfacing as a bare JSONDecodeError that names no file — or being
        parsed leniently. Asserts the ValueError carries the 'not valid
        JSON' marker (distinct from the schema-invalid refusal), names the
        offending PATH, and chains the JSONDecodeError. Fails: missing
        marker/path, or a lost __cause__ (JSONDecodeError IS a ValueError,
        so pytest.raises alone could not tell wrapped from unwrapped)."""
        bad = tmp_path / "interpretation_v1.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError) as excinfo:
            node_mod.load_experiment_history(bad)
        assert "not valid JSON" in str(excinfo.value)
        assert str(bad) in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, json.JSONDecodeError)

    def test_schema_invalid_refuses_distinctly(self, tmp_path):
        """Defect only this catches: syntactically-valid JSON that is NOT an
        InterpretationOutput (e.g. a proposal_{run}.json passed by mistake)
        slipping past ingestion and failing deep inside the search loop with
        an unattributed error — or being silently constructed unvalidated.
        Asserts the refusal names the SCHEMA and the PATH and chains the
        pydantic ValidationError. Fails: DID NOT RAISE (the plant used for
        the RED evidence) or the message/cause loses either identity."""
        wrong = tmp_path / "interpretation_v1.json"
        wrong.write_text(json.dumps({"model_name": "x"}), encoding="utf-8")
        with pytest.raises(ValueError) as excinfo:
            node_mod.load_experiment_history(wrong)
        assert "not a valid InterpretationOutput" in str(excinfo.value)
        assert str(wrong) in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, ValidationError)

    def test_valid_file_round_trips(self, tmp_path):
        """Defect only this catches: loader drift against the interpreter's
        persistence shape (e.g. expecting a wrapper key, or lossy field
        handling) — the 'one input shape, two sources' property the CLI
        depends on. Fails: the loaded model_dump differs from the persisted
        record's."""
        hist = _history()
        p = tmp_path / "interpretation_v1.json"
        p.write_text(hist.model_dump_json(), encoding="utf-8")
        assert node_mod.load_experiment_history(p).model_dump() == hist.model_dump()


# ---------------------------------------------------------------------------
# Flag surface — _build_arg_parser
# ---------------------------------------------------------------------------


class TestArgParser:
    def test_flag_surface_and_defaults(self):
        """Defect only this catches: silent drift of the standalone flag
        surface — a renamed flag or changed default breaks scripted
        invocation and the node-doc contract, and no schema or type checker
        sees argparse wiring. Fails: SystemExit on parse, or a
        default/dest mismatch against the documented table."""
        args = node_mod._build_arg_parser().parse_args(_REQUIRED_ARGS)
        assert args.workspace == "./siderius_workspace"
        assert args.run_name == "v1"
        assert args.experiment_history is None
        assert args.lit_review_config == "/task/literature.yaml"
        assert args.task_composition == "/task/composition.yaml"
        assert args.data_dir == "/task/data"
        assert args.provider == "gemini"
        assert args.model_id == "gemini-3.1-flash-lite-preview"

    def test_experiment_history_accepts_both_spellings(self):
        """Defect only this catches: losing either spelling of the
        upstream-record flag — the dashed form is the issue-#303 acceptance
        criterion, the underscore form is the repo's flag style, and
        argparse has no dash/underscore equivalence, so only the explicit
        alias keeps both alive. Fails: SystemExit from the dropped
        spelling."""
        parser = node_mod._build_arg_parser()
        common = _REQUIRED_ARGS
        assert (
            parser.parse_args([*common, "--experiment-history", "a.json"]).experiment_history
            == "a.json"
        )
        assert (
            parser.parse_args([*common, "--experiment_history", "b.json"]).experiment_history
            == "b.json"
        )


# ---------------------------------------------------------------------------
# main() end-to-end (stubbed agent; task loading and binding are real)
# ---------------------------------------------------------------------------

_TEST_CONFIG_YAML = """\
enabled: false
root_papers: []
dynamic_search:
  enabled: false
synthesis:
  transfer_tolerance: strict
confidence_rubric:
  omit_below: 0.55
findings_verbosity: 0
"""


def _install_stubs(monkeypatch, captured: list) -> None:
    """Replace only execution effects, retaining real task accessors and binding."""

    class _FakeAgent:
        def run(self, inp: LiteratureReviewInput) -> LiteratureReviewOutput:
            captured.append(inp)
            return LiteratureReviewOutput(
                agent_card=node_mod._AGENT_CARD,
                run_name=inp.run_name,
                started_at="2026-08-25T00:00:00Z",
                finished_at="2026-08-25T00:00:00Z",
            )

    monkeypatch.setattr(node_mod, "MLLiteratureReviewAgent", lambda *a, **k: _FakeAgent())


class TestMainEndToEnd:
    def test_main_reads_interpretation_by_naming_convention(self, monkeypatch, tmp_path):
        """Defect only this catches: the zero-flag upstream read drifting off
        the interpreter's persisted filename (interpretation_{run_name}.json
        — the same record the proposal agent's CLI reads), or main()
        assembling the input off the workflow's key mapping (the YAML's
        `synthesis:` block must land on `synthesis_config`). Runs the REAL
        main() so a bypass of load_experiment_history or the mapping breaks
        it. Fails: FileNotFoundError (wrong filename) or a captured-input
        field mismatch."""
        ws = tmp_path / "ws"
        ws.mkdir()
        hist = _history()
        (ws / "interpretation_r7.json").write_text(hist.model_dump_json(), encoding="utf-8")
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(_TEST_CONFIG_YAML, encoding="utf-8")

        captured: list[LiteratureReviewInput] = []
        _install_stubs(monkeypatch, captured)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ml_literature_review.py",
                *_task_args(tmp_path),
                "--workspace",
                str(ws),
                "--run_name",
                "r7",
                "--lit_review_config",
                str(cfg),
                "--provider",
                "openai",
                "--model_id",
                "m",
            ],
        )
        node_mod.main()

        assert len(captured) == 1
        inp = captured[0]
        assert isinstance(inp, LiteratureReviewInput)
        assert inp.interpretation_evidence == local_typed_evidence(hist)
        assert inp.run_name == "r7"
        assert inp.storage.local is not None and inp.storage.local.workspace == str(ws)
        assert inp.llm_provider == "openai"
        assert inp.llm_model_id == "m"
        assert inp.task_description == "fixture task"
        assert inp.root_papers == []
        assert inp.dynamic_search.enabled is False
        assert inp.synthesis_config.transfer_tolerance == "strict"
        assert inp.confidence_rubric.omit_below == 0.55
        assert inp.findings_verbosity == 0

    def test_main_explicit_experiment_history_wins(self, monkeypatch, tmp_path):
        """Defect only this catches: --experiment-history silently ignored in
        favour of the naming-convention file — the issue-#303 acceptance
        path (a fresh project with no workspace layout). The conventional
        file holds DECOY content; asserts the explicit file's content
        reached run(). Fails: the captured input carries the decoy's
        bottlenecks."""
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "interpretation_v1.json").write_text(
            _history(bottlenecks=["decoy"]).model_dump_json(), encoding="utf-8"
        )
        explicit = tmp_path / "custom_history.json"
        explicit.write_text(_history(bottlenecks=["real"]).model_dump_json(), encoding="utf-8")
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(_TEST_CONFIG_YAML, encoding="utf-8")

        captured: list[LiteratureReviewInput] = []
        _install_stubs(monkeypatch, captured)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "ml_literature_review.py",
                *_task_args(tmp_path),
                "--workspace",
                str(ws),
                "--run_name",
                "v1",
                "--experiment-history",
                str(explicit),
                "--lit_review_config",
                str(cfg),
            ],
        )
        node_mod.main()

        assert captured[0].interpretation_evidence.bottlenecks == ("real",)


def _cli_case(tmp_path, *, description="fixture task", metric_identity=None):
    task_args = _task_args(tmp_path, description)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    history = workspace / "interpretation_v1.json"
    history.write_text(_history(metric_identity=metric_identity).model_dump_json())
    knobs = tmp_path / "literature.yaml"
    knobs.write_text(_TEST_CONFIG_YAML)
    argv = [
        "ml_literature_review.py",
        *task_args,
        "--workspace",
        str(workspace),
        "--lit_review_config",
        str(knobs),
    ]
    return argv, workspace, history


class TestTaskBindingRefusals:
    @pytest.mark.parametrize(
        "defect",
        [
            "missing_manifest_flag",
            "missing_data_flag",
            "missing_manifest",
            "invalid_manifest",
            "missing_task_config",
            "invalid_task_config",
            "missing_data",
            "data_file",
            "invalid_knobs",
        ],
    )
    def test_bad_declaration_never_constructs_agent(self, monkeypatch, tmp_path, defect):
        """Pins real startup reachability, not schema mechanics: any bypass constructs
        the forbidden agent or leaves a node cache/output instead of refusing."""
        from execute_tools.data_paths import DatasetDirectoryUnavailable

        argv, workspace, _ = _cli_case(tmp_path)
        expected_error = (ValueError, FileNotFoundError, DatasetDirectoryUnavailable)
        if defect in {"missing_manifest_flag", "missing_data_flag"}:
            flag = "--task_composition" if defect == "missing_manifest_flag" else "--data_dir"
            index = argv.index(flag)
            del argv[index : index + 2]
            expected_error = (SystemExit,)
        elif defect == "missing_manifest":
            (tmp_path / "composition.yaml").unlink()
        elif defect == "invalid_manifest":
            (tmp_path / "composition.yaml").write_text("not_a_section: true\n")
        elif defect == "missing_task_config":
            (tmp_path / "examples/quickstart/declared/task_config.yaml").unlink()
        elif defect == "invalid_task_config":
            (tmp_path / "examples/quickstart/declared/task_config.yaml").write_text(
                "task_description: ''\n"
            )
        elif defect == "missing_data":
            (tmp_path / "data").rmdir()
        elif defect == "data_file":
            (tmp_path / "data").rmdir()
            (tmp_path / "data").write_text("not a directory")
        else:
            (tmp_path / "literature.yaml").write_text("findings_verbosity: 99\n")

        def forbidden(*args, **kwargs):
            pytest.fail("invalid declaration reached agent construction")

        monkeypatch.setattr(node_mod, "MLLiteratureReviewAgent", forbidden)
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(expected_error):
            node_mod.main()
        assert not (workspace / "cache").exists()
        assert not (workspace / "ml_literature_review_v1.json").exists()

    @pytest.mark.parametrize(
        "metric_id,direction", [("other_metric", "higher"), ("accuracy", "lower")]
    )
    def test_conflicting_history_names_both_sources(
        self, monkeypatch, tmp_path, metric_id, direction
    ):
        """Skipping reconciliation must reach the forbidden agent; both distinct
        contradictions must identify the history and requested manifest."""
        from execute_tools.evaluation_metric import MetricIdentityConflictError

        argv, workspace, history = _cli_case(
            tmp_path, metric_identity={"metric_id": metric_id, "direction": direction}
        )
        monkeypatch.setattr(
            node_mod,
            "MLLiteratureReviewAgent",
            lambda **kwargs: pytest.fail("contradictory history reached agent"),
        )
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(MetricIdentityConflictError) as exc:
            node_mod.main()
        assert str(history) in str(exc.value)
        assert str(tmp_path / "composition.yaml") in str(exc.value)
        assert not (workspace / "cache").exists()

    def test_sequential_tasks_and_exception_restore_bindings(self, monkeypatch, tmp_path):
        """A leaked task/data/metric binding survives the first run or failure;
        a stale description appears in the next run. Neither is a type error."""
        from execute_tools.data_paths import active_physical_data_root
        from execute_tools.dataset_config import resolve_dataset_profile
        from execute_tools.evaluation_metric import resolve_bound_run_metric
        from execute_tools.task_data_path import active_task_data_path
        from workflows.task_config import resolve_bound_task_config

        before = (
            resolve_bound_task_config(),
            resolve_bound_run_metric(),
            active_physical_data_root(),
            active_task_data_path(),
        )
        seen = []

        class InspectAgent:
            def run(self, inp):
                seen.append(inp.task_description)
                assert resolve_dataset_profile().partition_count == 4
                assert active_physical_data_root() is not None
                assert resolve_bound_task_config() is not None
                assert resolve_bound_run_metric().spec.id == "accuracy"
                if inp.task_description == "second task":
                    raise RuntimeError("run failed after binding")
                return LiteratureReviewOutput(
                    agent_card=node_mod._AGENT_CARD,
                    run_name=inp.run_name,
                    started_at="2026-09-13T00:00:00Z",
                    finished_at="2026-09-13T00:00:00Z",
                )

        monkeypatch.setattr(node_mod, "MLLiteratureReviewAgent", lambda **kwargs: InspectAgent())
        for index, description in enumerate(("first task", "second task", "third task")):
            case = tmp_path / str(index)
            case.mkdir()
            argv, _, _ = _cli_case(
                case,
                description=description,
                metric_identity={"metric_id": "accuracy", "direction": "higher"},
            )
            monkeypatch.setattr(sys, "argv", argv)
            if index == 1:
                with pytest.raises(RuntimeError, match="run failed after binding"):
                    node_mod.main()
            else:
                node_mod.main()
            assert (
                resolve_bound_task_config(),
                resolve_bound_run_metric(),
                active_physical_data_root(),
                active_task_data_path(),
            ) == before
        assert seen == ["first task", "second task", "third task"]


@pytest.mark.parametrize("omit_task", [False, True])
def test_cold_script_transports_task_to_real_synthesis_and_storage(tmp_path, omit_task):
    """No parent binding/import can rescue script startup. A dropped task hop
    loses the distinctive synthesis prompt; a swallowed bridge exception cannot
    pass because the child asserts the exact call, then the parent reads output."""
    argv, workspace, _ = _cli_case(tmp_path, description="Cold CLI selected synthetic task")
    if omit_task:
        index = argv.index("--task_composition")
        del argv[index : index + 2]
    script_path = _REPO_ROOT / "src/nodes/ml_literature_review/ml_literature_review.py"
    neutral = tmp_path / "neutral"
    neutral.mkdir()
    script = textwrap.dedent("""\
        import builtins
        import os
        from pathlib import Path
        import runpy
        import socket
        import sys
        import agent.llm_bridge as bridge_module

        assert "workflows.task_composition" not in sys.modules
        assert "SIDERIUS_GENERATED_LIBRARY_DIR" not in os.environ
        observed = []
        original_import = builtins.__import__
        def observe_import(name, *args, **kwargs):
            if name == "workflows.task_composition":
                workspace = Path(sys.argv[sys.argv.index("--workspace") + 1])
                assert os.environ["SIDERIUS_GENERATED_LIBRARY_DIR"] == str(workspace / "generated_library")
                observed.append("composition_after_workspace")
            return original_import(name, *args, **kwargs)
        builtins.__import__ = observe_import

        def forbidden_network(*args, **kwargs):
            raise AssertionError("cold CLI witness forbids network")
        socket.create_connection = forbidden_network
        socket.socket.connect = forbidden_network

        calls = []
        class Bridge:
            def __init__(self, **kwargs):
                pass
            def generate(self, system, user, *, label, **kwargs):
                calls.append((label, system, user))
                return {"findings": []}
        bridge_module.LLMBridge = Bridge
        sys.argv = sys.argv[1:]
        namespace = runpy.run_path(sys.argv[0], run_name="__main__")
        assert Path(namespace["__file__"]).resolve() == Path(sys.argv[0]).resolve()
        assert observed == ["composition_after_workspace"]
        assert len(calls) == 1, calls
        assert calls[0][0] == "lit_review.synthesis"
        assert "Cold CLI selected synthetic task" in calls[0][1]
        print("COLD_CLI_TASK_TRANSPORT_PASS")
    """)
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "SIDERIUS_GENERATED_LIBRARY_DIR", "SIDERIUS_CHAIN_WORKSPACE"}
        and not key.endswith("_API_KEY")
    }
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(script_path), *argv[1:]],
        cwd=neutral,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output_path = workspace / "ml_literature_review_v1.json"
    if omit_task:
        assert result.returncode == 2, result.stdout + result.stderr
        assert "--task_composition" in result.stderr
        assert not output_path.exists()
        assert not (workspace / "cache").exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "COLD_CLI_TASK_TRANSPORT_PASS" in result.stdout
        output = LiteratureReviewOutput.model_validate_json(output_path.read_text())
        assert output.run_name == "v1"
        assert output.agent_card.agent_name == "ml_literature_review"
        assert output.search_rounds_used == 0


def test_relative_knob_path_stays_checkout_anchored(monkeypatch, tmp_path):
    """A CWD-based resolution would consume the decoy YAML instead of the
    existing checkout-relative knob path; absolute external YAML is covered above."""
    argv, _, _ = _cli_case(tmp_path)
    neutral = tmp_path / "neutral"
    neutral.mkdir()
    (neutral / "literature.yaml").write_text("findings_verbosity: 1\n")
    argv[argv.index("--lit_review_config") + 1] = "literature.yaml"
    monkeypatch.chdir(neutral)
    monkeypatch.setattr(node_mod, "_SIDERIUS_ROOT", tmp_path)
    captured = []
    _install_stubs(monkeypatch, captured)
    monkeypatch.setattr(sys, "argv", argv)
    node_mod.main()
    assert captured[0].findings_verbosity == 0


# ---------------------------------------------------------------------------
# Empty-bottlenecks synthesis render (the issue-#303 cold-start property)
# ---------------------------------------------------------------------------


class TestEmptyBottlenecksSynthesisRender:
    def test_empty_bottlenecks_grounds_on_task_description(self):
        """The cold-start property issue #303 established: with zero
        bottlenecks the synthesis user prompt must NOT close with 'omit any
        paper that does not address one of the bottlenecks above' — against
        an empty list that instructs omitting EVERY paper. It renders the
        explicit '(none)' absence and redirects grounding to the task
        description. Defect only this catches: the self-defeating cold-start
        instruction returning. Fails: the legacy closing reappears, or the
        '(none)' marker / task-grounding closing disappears."""
        _system, user = render_synthesis_prompt(
            key_findings=[],
            bottlenecks=[],
            take_home_message="",
            papers=[{"paper_id": "arxiv:1", "title": "T", "year": 2020, "summary": "s"}],
            task_description="fixture task",
        )
        assert "Open bottlenecks:\n(none)" in user
        assert "does not address one of the bottlenecks above" not in user
        assert "No open bottlenecks are recorded yet" in user
        assert "task described in the system prompt" in user

    def test_whitespace_only_bottlenecks_take_the_cold_start_branch(self):
        """Defect only this catches: the branch predicate diverging from
        _bullets' whitespace cleaning — e.g. `if not bottlenecks:` renders
        '(none)' for whitespace-only entries while STILL closing with the
        per-bottleneck omission instruction, so the instruction points at a
        list the prompt does not show. The branch must key on the RENDERED
        block. Fails: the legacy closing appears next to a '(none)'
        bottleneck list. (The non-empty side needs no twin here — the PB-9
        user-prompt golden pins those bytes.)"""
        _system, user = render_synthesis_prompt(
            key_findings=[],
            bottlenecks=["   ", ""],
            take_home_message="",
            papers=[],
            task_description="fixture task",
        )
        assert "Open bottlenecks:\n(none)" in user
        assert "does not address one of the bottlenecks above" not in user
        assert "No open bottlenecks are recorded yet" in user
