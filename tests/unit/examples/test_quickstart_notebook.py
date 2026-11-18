"""Execute the quickstart notebook's code cells and check what its text promises.

`examples/quickstart/quickstart.ipynb` is the first thing a new user runs.
Every code cell is offline (no network, no GPU, no API key); sections 13-15
show their commands in Markdown only. Token checks in
``test_quickstart_pack.py`` cannot notice a cell that no longer runs, or one
whose output no longer matches the "Expected:" text after it, when the
framework API underneath changes. This module runs the cells in order, in a
temporary workspace, and asserts those documented facts.

Every test names the defect only it catches (CLAUDE.md test rule).
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import socket
import sys
from pathlib import Path

import pytest

from execute_tools.task_registration_scope import run_registration_scope

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK = REPO_ROOT / "examples" / "quickstart"
NOTEBOOK = PACK / "quickstart.ipynb"


def _line(text: str) -> str:
    """A pattern matching one whole output line exactly."""
    return "^" + re.escape(text) + "$"


#: The facts each code cell's following "Expected:" text states, as patterns
#: searched line by line in the cell's stdout. A fenced ```text block in that
#: text is checked verbatim on top of these (see ``_expected_text_block``).
#: The keys must equal the notebook's code-cell ids, so a new code cell has to
#: be classified here (and be offline) before this test passes again.
EXPECTED: dict[str, tuple[str, ...]] = {
    "qs02": (_line(f"checkout : {REPO_ROOT}"),),
    "qs04": (
        *(rf"^   shard_000{i}\.csv \d+ bytes$" for i in range(4)),
        _line("sample_id,x0,x1,x2,x3,label"),
    ),
    "qs06": (
        r"\Atask_data_path ",
        r"^task_health +\{\"none\": true\}$",
        r"^model_plugins [^\n]*\n\Z",
    ),
    "qs08": (),
    "qs10": (
        _line("training rows  : 128 from shards [0, 1]"),
        _line("evaluation rows: 64 from shard [2]"),
        r"^refused        : .*\[3\]",
    ),
    "qs12": (
        _line("score: accuracy | direction: higher"),
        _line("all correct : MetricResult 1.0"),
        _line("all wrong   : MetricResult 0.0"),
        r"^no file     : NotScoreableResult \| deliverable not found",
    ),
    "qs14": (
        _line("model type : quickstart_reference_mlp"),
        _line("parameters : 114"),
        _line("forward    : (8, 4) -> (8, 2)"),
    ),
    "qs16": (
        _line(
            "prediction file: quickstart_predictions_quickstart_reference_mlp_first_run_exp0_0000.json"
        ),
        _line("score          : MetricResult 1.0"),
    ),
    "qs18": (),
    "qs20": (
        r"^default\.json +\['gpt-5\.6-luna'\]$",
        r"^openai-moderate-v1\.json +\['gpt-5\.6-luna', 'gpt-6-astra'\]$",
    ),
    "qs22": tuple(
        _line(f"  {name}")
        for name in (
            "data/",
            "llm.json",
            "metric_probe.json",
            "predictions/",
            "runs/",
            "task.yaml",
            "workflow.py",
        )
    ),
    "qs24": (
        r"^run folder    : .*/runs/[0-9a-f-]{36}$",
        _line(f"task manifest : {REPO_ROOT / 'configs' / 'task_composition' / 'quickstart.yaml'}"),
        _line("advice        : Prefer a small interpretable baseline"),
        _line("written so far: nothing"),
    ),
    "qs26": (r"^No finished run yet",),
}


def _cells() -> list[dict]:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]


def _expected_text_block(cells: list[dict], index: int) -> list[str]:
    """Lines of the ```text block in the "Expected" text after cell ``index``.

    Only the text before the next section heading counts: the same Markdown
    cell can continue into a later section whose example output is not this
    cell's expected result.
    """
    following = cells[index + 1] if index + 1 < len(cells) else None
    if following is None or following["cell_type"] != "markdown":
        return []
    text = "".join(following["source"]).split("\n## ", 1)[0]
    if not text.startswith("Expected"):
        return []
    block = re.search(r"```text\n(.*?)```", text, re.S)
    return block.group(1).splitlines() if block else []


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse internet connections and remove the provider key for the test."""
    real_connect = socket.socket.connect

    def connect(self: socket.socket, address: object) -> None:
        if self.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError(f"quickstart notebook cell opened a network connection: {address}")
        real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_every_code_cell_runs_offline_and_prints_its_expected_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, offline: None
) -> None:
    """Defects caught: a notebook cell that raises against the current
    framework API (a renamed import, a changed request field, a refusal the
    text does not mention); output that contradicts the cell's "Expected:"
    text (row counts, score values, parameter count, file names, fenced
    expected blocks); a cell that needs the network or an API key; and a new
    code cell added without being classified here. Each cell's failure names
    its id."""
    cells = _cells()
    code = [(i, c) for i, c in enumerate(cells) if c["cell_type"] == "code"]
    assert [c["id"] for _, c in code] == list(EXPECTED), (
        "quickstart code cells changed; classify each new cell in EXPECTED "
        "(it must run offline) and state its expected facts"
    )

    monkeypatch.chdir(PACK)
    monkeypatch.setenv("SIDERIUS_QUICKSTART_WORKSPACE", str(tmp_path / "workspace"))
    plugin_dir = (PACK / "plugins").resolve()
    modules_before = set(sys.modules)
    namespace: dict[str, object] = {"__name__": "quickstart_notebook"}
    try:
        with run_registration_scope():
            for index, cell in code:
                cell_id = cell["id"]
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    exec(compile("".join(cell["source"]), f"<{cell_id}>", "exec"), namespace)
                stdout = out.getvalue()
                for pattern in EXPECTED[cell_id]:
                    assert re.search(pattern, stdout, re.M), (
                        f"{cell_id} output does not show {pattern!r}:\n{stdout}"
                    )
                lines = set(stdout.splitlines())
                for expected in _expected_text_block(cells, index):
                    assert expected in lines, (
                        f"{cell_id} output lacks the documented line {expected!r}:\n{stdout}"
                    )
    finally:
        # The notebook loads task plugins by path into sys.modules (cell qs04);
        # drop exactly those so later tests import their own copies.
        for name in set(sys.modules) - modules_before:
            origin = getattr(sys.modules[name], "__file__", None)
            if origin and Path(origin).resolve().parent == plugin_dir:
                del sys.modules[name]
