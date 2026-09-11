"""Step 12 / PR-12e — the frozen static-report CLI and its renderers.

Design: ``pr_12e_out_of_tree_graduation.md`` §V.2 (the entrypoint contract),
§V.5 (a mature example must not require the dashboard), §V.15 (the contract
that had to freeze before workstreams D and R implemented).

The flags are FROZEN and published in three example pack READMEs, so they are
asserted here rather than left to the argparse definition: a rename is a
silent break of three documents and of workstream D's read-only consumption.

Fixtures are the same REAL Gate-2 chain workspace the projection tests use;
see that module's docstring for provenance.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from execute_tools.run_report import RUN_OUTPUT_GLOB, build_report
from tools.run_report.cli import (
    EXIT_NO_ARTIFACT,
    EXIT_OK,
    REPORT_JSON,
    build_parser,
    main,
)
from tools.run_report.figures import render_figures
from tools.run_report.html import render_html

CHAIN_WORKSPACE = (
    Path(__file__).resolve().parents[2] / "unit/execute_tools/step12_pr12e_fixtures/chain_workspace"
)


class TestTheFrozenCommandContract:
    """§V.2/§V.15 — these strings are published in three READMEs."""

    def test_the_flags_are_exactly_the_frozen_set(self):
        """MUTATION TARGET: rename ``--run-output`` to ``--run_output``.

        Three example packs publish
        ``python -m tools.run_report --workspace <dir> --out <dir>``. A flag
        rename breaks all three documents and workstream D's consumption at
        once, and argparse's error would be the first anyone hears of it.
        """
        options = {
            option
            for action in build_parser()._actions
            for option in action.option_strings
            if option.startswith("--")
        }
        assert {"--workspace", "--run-output", "--out"} <= options

    def test_the_two_sources_are_mutually_exclusive_and_one_is_required(self):
        """A report with no declared source would have to guess a directory."""
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--out", "x"])
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--workspace", "a", "--run-output", "b", "--out", "x"])

    def test_out_is_required(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--workspace", "a"])

    def test_the_module_is_executable_as_python_m(self):
        """MUTATION TARGET: delete ``tools/run_report/__main__.py``.

        The published command is ``python -m tools.run_report``. Without a
        ``__main__``, that exact string fails while every import-level test
        still passes.
        """
        assert (
            Path(__file__).resolve().parents[2].parent / "src/tools/run_report/__main__.py"
        ).is_file()


class TestItProducesTheDeclaredArtifacts:
    def test_a_workspace_run_writes_html_figures_and_json_and_exits_zero(self, tmp_path):
        """The whole contract, end to end, from the real Gate-2 artifacts."""
        assert main(["--workspace", str(CHAIN_WORKSPACE), "--out", str(tmp_path)]) == EXIT_OK
        assert (tmp_path / "index.html").is_file()
        assert (tmp_path / REPORT_JSON).is_file()
        assert list(tmp_path.glob("*.png")), "no figure was written"

    def test_report_json_is_the_projection_and_is_machine_readable(self, tmp_path):
        """MUTATION TARGET: write the HTML only.

        §V.5's "one projection, multiple presentation consumers" is only true
        if the data has a non-HTML form. A downstream consumer — the packs,
        the dashboard, a future tool — must not have to scrape a page.
        """
        main(["--workspace", str(CHAIN_WORKSPACE), "--out", str(tmp_path)])
        payload = json.loads((tmp_path / REPORT_JSON).read_text())
        assert payload["schema_version"]
        assert len(payload["runs"]) == 3
        assert payload["trajectory"]["metric"]["direction"] == "higher"
        assert [p["run_name"] for p in payload["trajectory"]["points"]] == [
            "iter_001",
            "iter_002",
            "iter_003",
        ]
        assert payload["lock"]["resolved_data_scope"] == [4, 5, 6, 7, 8, 9]

    def test_the_single_artifact_mode_works(self, tmp_path):
        source = sorted(CHAIN_WORKSPACE.rglob(RUN_OUTPUT_GLOB))[0]
        assert main(["--run-output", str(source), "--out", str(tmp_path)]) == EXIT_OK
        payload = json.loads((tmp_path / REPORT_JSON).read_text())
        assert len(payload["runs"]) == 1
        assert payload["workspace"] is None
        assert payload["lock"] is None, (
            "a lock belongs to a WORKSPACE; claiming one for a hand-picked "
            "artifact would attribute an identity the file does not carry"
        )

    def test_the_html_references_only_files_it_wrote(self, tmp_path):
        """MUTATION TARGET: reference a CDN or an absolute path.

        §V.5 requires the static report to be portable — a directory a user
        can copy anywhere and open. Any external reference breaks that
        silently, and only offline.
        """
        main(["--workspace", str(CHAIN_WORKSPACE), "--out", str(tmp_path)])
        html = (tmp_path / "index.html").read_text()
        assert "http://" not in html
        assert "https://" not in html
        assert "<script" not in html
        written = {p.name for p in tmp_path.iterdir()}
        import re

        for src in re.findall(r'<img src="([^"]+)"', html):
            assert src in written, f"index.html references {src!r}, which was not written"


class TestNamedFailureRatherThanAnEmptyPage:
    def test_an_empty_directory_exits_non_zero_with_a_named_error(self, tmp_path, capsys):
        """MUTATION TARGET: return EXIT_OK and write an empty page.

        The packs publish this command. A user who points it at the wrong
        directory must be told, not handed a blank report they will read as
        "the run produced nothing".
        """
        out = tmp_path / "out"
        assert main(["--workspace", str(tmp_path), "--out", str(out)]) == EXIT_NO_ARTIFACT
        assert EXIT_NO_ARTIFACT != 0
        captured = capsys.readouterr()
        assert "no_run_output_found" in captured.err
        assert not out.exists(), "a failed run must not leave a half-written report directory"

    def test_a_corrupt_only_directory_names_the_offending_file(self, tmp_path, capsys):
        (tmp_path / "run_output_x.json").write_text("{")
        assert (
            main(["--workspace", str(tmp_path), "--out", str(tmp_path / "o")]) == EXIT_NO_ARTIFACT
        )
        err = capsys.readouterr().err
        assert "no_run_output_consumable" in err
        assert "run_output_x.json" in err


class TestTheRenderersStateWhatTheyCannotShow:
    """A missing chart must be an explained absence, not a blank."""

    def test_a_refused_corpus_draws_no_trajectory_and_says_why(self, tmp_path):
        """MUTATION TARGET: draw the curve anyway when direction is unknown.

        A best-so-far curve with no declared direction is confidently wrong
        half the time. The renderer's honest output is no chart plus the
        refusal, which is what §V.14h's "decline by name" means for a figure.
        """
        source = sorted(CHAIN_WORKSPACE.rglob(RUN_OUTPUT_GLOB))[0]
        doc = json.loads(source.read_text())
        doc["metric_spec"] = None
        for record in doc["all_records"]:
            record["metric_result"] = None
        path = tmp_path / "run_output_nodir.json"
        path.write_text(json.dumps(doc))

        report = build_report(run_outputs=[path])
        figures = render_figures(report, tmp_path / "fig")
        assert figures["primary_metric_trajectory"] == []
        html = render_html(report, figures)
        assert "metric direction unavailable" in html
        assert "No trajectory chart is drawn" in html

    def test_the_objective_is_labelled_by_its_typed_kind_not_loss(self, tmp_path):
        """MUTATION TARGET: label the objective axis "loss".

        §V.4 rule 1. The real fixture's objective is ``ce``; a DAVIS training
        MAE and a terminal MSE must not share the word either.
        """
        report = build_report(workspace=CHAIN_WORKSPACE)
        figures = render_figures(report, tmp_path)
        assert figures["objective_history"], "no objective figure was drawn"
        html = render_html(report, figures)
        assert "<code>ce</code>" in html
        assert 'not "loss"' in html

    def test_the_html_states_the_class_b_gaps(self, tmp_path):
        """A view's silence about a missing series must be a stated decision."""
        report = build_report(workspace=CHAIN_WORKSPACE)
        html = render_html(report, render_figures(report, tmp_path))
        assert "does not show" in html
        assert "per-step" in html
        assert "chain-iteration" in html

    def test_a_declared_but_unevaluated_secondary_still_gets_a_panel(self, tmp_path):
        """MUTATION TARGET: skip a secondary with no values.

        "Declared and never evaluated" is a NAMED absence, and it is exactly
        the silence the scored/refused/unavailable vocabulary exists to break.
        No real artifact on this machine has an evaluated secondary, so this
        is also the honest state of the current corpus.
        """
        source = sorted(CHAIN_WORKSPACE.rglob(RUN_OUTPUT_GLOB))[0]
        doc = json.loads(source.read_text())
        declarations = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "unit/execute_tools/step12_pr12e_fixtures/real_pets_metric_declarations.json"
            ).read_text()
        )
        doc["secondary_metric_specs"] = declarations["secondary_metric_specs"]
        path = tmp_path / "run_output_sec.json"
        path.write_text(json.dumps(doc))

        report = build_report(run_outputs=[path])
        assert [m.metric_id for m in report.runs[0].secondary_metrics] == [
            "macro_f1",
            "log_loss",
        ]
        assert [v.status for v in report.runs[0].attempts[0].secondaries] == [
            "unavailable",
            "unavailable",
        ]
        figures = render_figures(report, tmp_path / "fig")
        assert figures["secondary_metrics"], "a declared secondary drew no panel"
        html = render_html(report, figures)
        assert "log_loss" in html
        assert "lower is better" in html, (
            "log_loss is lower-is-better while the run's primary is higher; "
            "the panel must state the SECONDARY's own direction"
        )

    def test_a_run_declaring_no_secondary_renders_no_secondary_bytes(self, tmp_path):
        """MUTATION TARGET: emit an empty secondary panel unconditionally.

        Step 10 P2b froze this: a run that declares none writes no key,
        renders zero bytes and fabricates no absence rows. An empty chart
        would report a silence as a measurement.
        """
        report = build_report(workspace=CHAIN_WORKSPACE)
        figures = render_figures(report, tmp_path)
        assert figures["secondary_metrics"] == []
        html = render_html(report, figures)
        assert "declares no secondary metric" in html

    def test_the_html_escapes_values_it_did_not_author(self, tmp_path):
        """MUTATION TARGET: interpolate record fields without escaping.

        ``exp_id``, ``model_type`` and ``failure_reason`` originate upstream —
        including from LLM-proposed model names — and land in a page a user
        opens in a browser.
        """
        source = sorted(CHAIN_WORKSPACE.rglob(RUN_OUTPUT_GLOB))[0]
        doc = json.loads(source.read_text())
        doc["model_type"] = "<script>alert(1)</script>"
        doc["all_records"][0]["failure_reason"] = "<img src=x onerror=alert(1)>"
        path = tmp_path / "run_output_xss.json"
        path.write_text(json.dumps(doc))
        report = build_report(run_outputs=[path])
        html = render_html(report, {})
        assert "<script>alert(1)</script>" not in html
        assert "<img src=x onerror=alert(1)>" not in html
        assert "&lt;script&gt;" in html


class TestTheRendererOwnsNoSemantics:
    """§V.5 — the view must never become a semantic authority."""

    def test_no_production_package_imports_the_renderer(self):
        """MUTATION TARGET: import ``tools.run_report`` from ``execute_tools``.

        ``tools/`` is deliberately not a production directory. If a production
        module ever imports the renderer, a rendering change can reach the
        training, scoring or chain path — and the separation §V.5 relies on
        becomes a convention instead of a structure.
        """
        repo_root = Path(__file__).resolve().parents[3]
        offenders: list[str] = []
        for package in (
            "src/agent",
            "src/core",
            "src/execute_tools",
            "src/nodes",
            "src/workflows",
            "src/dashboard",
        ):
            for path in (repo_root / package).rglob("*.py"):
                if "tools.run_report" in path.read_text(encoding="utf-8"):
                    offenders.append(str(path.relative_to(repo_root)))
        assert offenders == [], f"production code imports the static renderer: {offenders}"

    def test_a_diverged_epoch_reaches_the_FIGURE_as_a_gap_not_a_missing_point(self):
        """The presentation half of the F-12e-G2 information-preservation rule.

        The projection preserves a ``None`` epoch (pinned by
        ``test_a_diverged_epoch_survives_as_a_GAP_not_a_shortened_curve``);
        this pins that the FIGURE boundary preserves it too, because that is
        where the temptation to "clean up" the series actually lives —
        matplotlib's stub rejects ``None``, so the obvious fixes are a filter
        or a cast.

        Defect this catches, and how it fails: someone satisfies the stub with
        ``[v for v in series if v is not None]``. The curve then SHORTENS, so a
        run that diverged at epoch 3 of 5 renders as a healthy 4-point curve
        and the length assertion below fails. A ``cast`` leaves a runtime
        ``None`` that matplotlib coerces silently — the NaN assertion pins the
        explicit conversion instead, so the intent lives in the code rather
        than in a third-party implementation detail.
        """
        import math

        from tools.run_report.figures import _gapped

        out = _gapped([1.0, 0.8, None, 0.5, 0.4])
        # Length preserved -- a filtering comprehension would give 4.
        assert len(out) == 5
        # The gap sits at the epoch that diverged.
        assert math.isnan(out[2])
        # Surviving epochs keep their values AND their positions.
        assert out == pytest.approx([1.0, 0.8, out[2], 0.5, 0.4], nan_ok=True)
