"""Step 12 / PR-12d — D4a: the scoring child's behaviour-preserving restructure.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §M / `D4a`.

``execute_tools/denoising_score_single.py`` carried **42 module-level
statements**, including the unconditional ``tidmad_topology(...)``, the
anchor-map load and the TIDMAD-shaped metric call. There was nothing to branch
around: making the child generic required first giving those statements a
function to live in. **D4a is that move and NOTHING else** — D4b makes the
semantic change, so the two are reviewable apart.

The evidence is a PRE/POST differential oracle over the child's *observable*
surfaces, recorded from the REAL child process across an argv matrix before
the restructure and re-run after it. Every case is hermetic — no real TIDMAD
data — which is why it can live in the unit suite.

Two ephemeral tokens are scrubbed and only those: the ``logging`` wall-clock
timestamp, and the pytest temporary directory. Scrubbing anything else would
be scrubbing the thing under test.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import ClassVar

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CHILD = REPO_ROOT / "execute_tools" / "denoising_score_single.py"

_TIMESTAMP = re.compile(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2} [AP]M")

#: The PRE capture, recorded from the child at `56fad584` — the commit BEFORE
#: the restructure — and pinned here as a golden. Regenerating it from the
#: post-restructure child would compare the code to itself, which is the
#: self-referential shape CLAUDE.md forbids; these are the bytes the OLD child
#: actually produced.
GOLDEN = REPO_ROOT / "tests" / "fixtures" / "step12_pr12d" / "d4a_scoring_child_surfaces.json"


def _drop_machine_config_warning(text: str) -> str:
    """Remove the "no local ``tidmad_data_config.yaml``" import warning.

    Step 12 / PR-12d, F-12d-35. A machine without a local
    ``tidmad_data_config.yaml`` emits a ``UserWarning`` (plus its source line)
    when ``execute_tools.data_paths`` is imported, and it lands in the child's
    stderr. Every developer box here has that file; CI does not — so this
    parity test compared 22 lines of genuine child output on one machine and
    24 on another, and reported it as "the behavioural surface moved".

    Scrubbed rather than baked into the golden, because it is a fact about the
    HOST, not about the child whose surfaces this test pins. Baking it in
    would invert the defect: the test would then pass only where the config is
    ABSENT.
    """
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    skip_continuation = False
    for line in lines:
        if "UserWarning: tidmad_data_config.yaml not found" in line:
            skip_continuation = True
            continue
        if skip_continuation and line.startswith("  "):
            skip_continuation = False
            continue
        skip_continuation = False
        kept.append(line)
    return "".join(kept)


def _scrub(text: str, tmp: str) -> str:
    text = text.replace(tmp, "<TMP>").replace(str(REPO_ROOT), "<ROOT>")
    text = text.replace("denoising_score_single.py", "<PROG>")
    text = _drop_machine_config_warning(text)
    return _TIMESTAMP.sub("<TS>", text)


def _run(args: list[str], *, cwd: str | None = None) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, str(CHILD), *args],
        capture_output=True,
        text=True,
        cwd=cwd or str(REPO_ROOT),
        env=env,
        timeout=180,
    )
    return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def _capture(tmp: str) -> dict:
    """Every observable surface, across the argv matrix D4a must preserve."""

    def case(args, cwd=None):
        payload = _run(args, cwd=cwd)
        for key in ("stdout", "stderr"):
            payload[key] = _scrub(payload[key], tmp)
        return payload

    common = ["--data_dir", tmp, "--raw_data_dir", tmp, "--file_index", "6"]
    cases = {
        "help": case(["--help"]),
        "help_from_other_cwd": case(["--help"], cwd=tmp),
        "unknown_flag": case(["--not_a_flag"]),
        "missing_deliverable_fix_mode": case(
            ["--mode", "fix", *common, "--denoising_model", "punet"]
        ),
        "deprecated_flags": case(["--mode", "fix", *common, "--coarse", "--weak"]),
    }
    out_json = pathlib.Path(tmp) / "out.json"
    out_json.write_text("{}", encoding="utf-8")
    cases["refusal_writes_output_json"] = case(
        ["--mode", "fix", *common, "--output_json", str(out_json)]
    )
    cases["refusal_output_json_content"] = json.loads(
        _scrub(out_json.read_text(encoding="utf-8"), tmp)
    )
    return cases


# ======================================================================
# The PRE/POST differential oracle
# ======================================================================


@pytest.mark.allow_real_subprocess  # the REAL child is the point
class TestBehaviouralParity:
    """Deep-equal on EVERY surface, against bytes the pre-restructure child produced."""

    #: The argv surface is the ONE thing D4b deliberately extends: it adds the
    #: four scope flags the other two children already accept. Every
    #: BEHAVIOURAL surface stays pinned to the pre-restructure bytes.
    #: ``unknown_flag`` is an argv surface too — argparse prints the usage
    #: line, which lists the options, to stderr.
    ARGV_SURFACES: ClassVar[tuple[str, ...]] = (
        "help",
        "help_from_other_cwd",
        "unknown_flag",
    )
    #: Only TWO of the four flags D4b adds are visible: the training-leg pair
    #: is `argparse.SUPPRESS`ed, because this child accepts it (the parent
    #: emits both legs from one acquisition) and consumes only the eval leg.
    D4B_ADDED_FLAGS: ClassVar[tuple[str, ...]] = (
        "--task_eval_scope_ref",
        "--task_eval_scope_digest",
    )

    def test_every_behavioural_surface_matches_the_pre_restructure_bytes(self, tmp_path):
        """The parity claim D4a made, still asserted verbatim.

        Exit codes, stdout, stderr and the merged ``--output_json`` payload —
        including the structured refusal — must be byte-identical to what the
        PRE-restructure child produced.
        """
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        observed = _capture(str(tmp_path))
        assert sorted(observed) == sorted(expected), "the surface SET changed"
        for surface in sorted(expected):
            if surface in self.ARGV_SURFACES:
                continue
            assert observed[surface] == expected[surface], f"surface {surface!r} moved"

    def test_the_argv_surface_grew_by_exactly_the_flags_D4b_declared(self, tmp_path):
        """The one surface that legitimately moved, and by exactly how much.

        D4a's oracle pinned the argv surface because D4a claimed to change
        nothing. D4b then ADDS four flags on purpose — the scope transport
        §D.C names for the scoring spawn site. Rather than re-recording the
        golden and losing the evidence, the delta itself is asserted: every
        pre-existing option survives, and the only additions are the four
        declared ones.
        """
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        observed = _capture(str(tmp_path))
        for surface in self.ARGV_SURFACES:
            # `--help` writes the options to stdout; argparse's own refusal
            # writes the usage line to stderr. Compare whichever carries them.
            stream = "stderr" if surface == "unknown_flag" else "stdout"
            before = set(re.findall(r"--[a-z_]+", expected[surface][stream]))
            after = set(re.findall(r"--[a-z_]+", observed[surface][stream]))
            assert before - after == set(), f"{surface}: options were REMOVED: {before - after}"
            assert after - before == set(self.D4B_ADDED_FLAGS), (
                f"{surface}: unexpected argv delta {sorted(after - before)}"
            )
            assert observed[surface]["returncode"] == expected[surface]["returncode"]

    def test_the_golden_is_not_vacuous(self):
        """A golden that recorded nothing would satisfy the oracle trivially."""
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        assert len(expected) == 7
        assert expected["help"]["returncode"] == 0
        assert len(expected["help"]["stdout"]) > 1000, "the whole argv surface"
        assert expected["unknown_flag"]["returncode"] == 2, "argparse's own refusal"
        assert expected["missing_deliverable_fix_mode"]["returncode"] == 1
        assert "Deliverable not scoreable" in expected["missing_deliverable_fix_mode"]["stderr"]
        assert expected["refusal_output_json_content"]["denoising_score"] is None
        assert expected["refusal_output_json_content"]["not_scoreable"]["metric_id"] == (
            "tidmad_denoising_score"
        )


# ======================================================================
# The structural claim D4a makes
# ======================================================================


class TestStructureOnly:
    """The module-level execution is gone; nothing else moved."""

    def test_the_child_is_now_importable_without_running(self):
        """The clearest statement of what changed.

        Before D4a, importing this module executed ``parser.parse_args()`` and
        the whole scoring path. It could not be imported, could not be called
        twice, and had no place to put a branch.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location("_d4a_probe", CHILD)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # must NOT parse argv or score anything
        assert callable(module.build_parser)
        assert callable(module.main)

    def test_the_entry_point_is_independently_callable(self):
        """``main(argv)`` takes its argv, so a caller need not patch sys.argv."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("_d4a_probe2", CHILD)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        signature = ast.unparse(
            next(
                node
                for node in ast.walk(ast.parse(CHILD.read_text(encoding="utf-8")))
                if isinstance(node, ast.FunctionDef) and node.name == "main"
            ).args
        )
        assert "argv" in signature

    def test_module_level_execution_dropped_materially(self):
        tree = ast.parse(CHILD.read_text(encoding="utf-8"))
        executable = [
            node
            for node in tree.body
            if not isinstance(
                node,
                (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            )
        ]
        assert len(executable) <= 5, [ast.unparse(n)[:60] for n in executable]
        kinds = {type(node).__name__ for node in executable}
        assert kinds <= {"Expr", "If"}, (
            f"only the docstring, the logging config and the __main__ guard may "
            f"remain at module level; found {kinds}"
        )

    def test_D4a_changed_NO_semantics(self):
        """The commit boundary, asserted rather than asserted-in-prose.

        The three things D4b will change must all still be exactly as they
        were: the unguarded TIDMAD SampleSet, the unconditional anchor-map
        load, and the TIDMAD-shaped metric call. D4a that "also fixed
        something" is rejected and split.
        """
        source = CHILD.read_text(encoding="utf-8")
        assert "anchor_data = load_anchor_map(args.anchor_map)" in source
        assert 's_max = float(anchor_data["s_max"])' in source
        assert "tidmad_topology(dataset_profile).dataset.segments_per_file" in source
        for kwarg in ("data_dir=", "sample_set=", "anchor_map=", "s_max=", "raw_data_dir="):
            assert kwarg in source
