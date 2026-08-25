"""CLI entry point for the ml_literature_review node — issue #303.

Covers the standalone surface this issue added: the flag surface, the three
DISTINCT experiment-history ingestion refusals, the naming-convention default
and the explicit ``--experiment-history`` override exercised through the REAL
``main()`` (production entry point; only the agent and the task-config loader
are stubbed), and the empty-bottlenecks synthesis render this issue
established.

Flow-only per the repo testing standard: no real LLM, no network, no disk
outside ``tmp_path``. This file imports privates of the node under test only
(its own test suite — same as ``test_node.py``); no other node's privates are
touched (node public-boundary rule).
"""

from __future__ import annotations

import json
import sys

import pytest
from pydantic import ValidationError

import nodes.ml_literature_review as node_mod
import workflows.task_config as task_config_mod
from agent.prompt_templates.literature_review import render_synthesis_prompt
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import LiteratureReviewInput, LiteratureReviewOutput

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
        args = node_mod._build_arg_parser().parse_args([])
        assert args.workspace == "./siderius_workspace"
        assert args.run_name == "v1"
        assert args.experiment_history is None
        assert args.lit_review_config == "configs/lit_review_config.yaml"
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
        assert parser.parse_args(["--experiment-history", "a.json"]).experiment_history == "a.json"
        assert parser.parse_args(["--experiment_history", "b.json"]).experiment_history == "b.json"


# ---------------------------------------------------------------------------
# main() end-to-end (stubbed agent + task config; everything else real)
# ---------------------------------------------------------------------------

_TEST_CONFIG_YAML = """\
root_papers: []
dynamic_search:
  enabled: false
synthesis:
  transfer_tolerance: strict
findings_verbosity: 0
"""


def _install_stubs(monkeypatch, captured: list) -> None:
    """Stub the agent (records its input, returns a minimal valid output)
    and the canonical task-config accessors main() resolves at call time."""

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
    monkeypatch.setattr(
        task_config_mod, "load_task_config", lambda path=None: {"task_description": "fixture task"}
    )
    monkeypatch.setattr(
        task_config_mod, "get_task_description", lambda cfg: cfg["task_description"]
    )


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
        assert inp.experiment_history.model_dump() == hist.model_dump()
        assert inp.run_name == "r7"
        assert inp.storage.local is not None and inp.storage.local.workspace == str(ws)
        assert inp.llm_provider == "openai"
        assert inp.llm_model_id == "m"
        assert inp.task_description == "fixture task"
        assert inp.root_papers == []
        assert inp.dynamic_search.enabled is False
        assert inp.synthesis_config.transfer_tolerance == "strict"
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

        assert captured[0].experiment_history.bottlenecks == ["real"]


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
