"""Issue #983 S7c: generated analysis programs always run seeded, and seeds
that generated code hard-codes are recorded, never modified (Q4).

Runner draws are pinned as literals; the sandbox itself is exercised in
``test_analysis_code_sandbox.py`` where the host permits it.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import agent.data_analysis.generated_program_runner as runner
from agent.data_analysis.analysis_code_sandbox import executed_program_seeds
from agent.data_analysis.sampling_seed import program_seed
from core.generated_seed_scan import scan_seed_calls
from tests.unit.agent.data_analysis.test_analysis_code_sandbox import _persist_program

#: random.random() and np.random.rand() right after seeding with 13.
DRAWS_13 = (0.2590084917154736, 0.7777024105738202)


def test_scan_reports_hard_coded_seed_calls_without_entropy_constructors():
    """Fails if a constant reseed in generated code goes unrecorded, or an
    entropy-drawing constructor (no argument) is reported as a seed."""
    source = (
        "import random\nimport numpy as np\nimport torch\n"
        "torch.manual_seed(42)\n"
        "np.random.seed(0)\n"
        "rng = np.random.default_rng(7)\n"
        "fresh = np.random.default_rng()\n"
        "random.seed(1)\n"
        "torch.cuda.manual_seed_all(3)\n"
    )
    found = [(c.line, c.call) for c in scan_seed_calls(source, file="plugin.py")]
    assert found == [
        (4, "torch.manual_seed(42)"),
        (5, "np.random.seed(0)"),
        (6, "np.random.default_rng(7)"),
        (8, "random.seed(1)"),
        (9, "torch.cuda.manual_seed_all(3)"),
    ]
    assert scan_seed_calls("def broken(:\n", file="bad.py") == ()


@pytest.mark.parametrize(
    ("determinism", "expected"), [("deterministic", 7), ("nondeterministic", 13)]
)
def test_program_runs_under_its_declared_or_the_run_derived_seed(tmp_path, determinism, expected):
    """Fails if a deterministic program's declared seed is overridden, or a
    nondeterministic one runs without the run-derived program seed."""
    program, _identity, _source = _persist_program(
        tmp_path,
        "def analyze(inputs, parameters, output_directory):\n    return {}\n",
        keys=("seeded",),
        determinism=determinism,
    )
    assert executed_program_seeds(program, 13) == (expected, expected)
    big = 2**40 + 5
    if determinism == "nondeterministic":
        assert executed_program_seeds(program, big) == (big, 5)


def test_runner_seeds_every_program_from_its_request(tmp_path):
    """Fails if the in-sandbox runner leaves a program on entropy (the old
    runner seeded only ``deterministic`` programs)."""
    source = tmp_path / "program.py"
    source.write_text(
        "import random\nimport numpy as np\n"
        "def analyze(inputs, parameters, output_directory):\n"
        "    return {'draws': [random.random(), float(np.random.rand())]}\n"
    )
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "inputs": {},
                "parameters": {},
                "determinism": "nondeterministic",
                "seed": 13,
                "numpy_seed": 13,
                "output_directory": str(tmp_path),
            }
        )
    )
    output = tmp_path / "payload.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            runner.__file__,
            "--source",
            str(source),
            "--request",
            str(request),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert tuple(json.loads(output.read_text())["draws"]) == DRAWS_13


def test_persisted_program_records_its_seed_calls_and_keeps_its_source(tmp_path):
    """Fails if an analysis program's hard-coded seed is not recorded in the
    run store, or if recording it alters the persisted source."""
    text = "import numpy as np\nnp.random.seed(5)\ndef analyze(inputs, parameters, output_directory):\n    return {}\n"
    program, _identity, source_path = _persist_program(tmp_path, text, keys=("seeded",))
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == program.source_sha256
    record = tmp_path / "generated_analysis" / "seed_calls" / f"{program.source_sha256}.json"
    assert json.loads(record.read_text()) == [
        {"call": "np.random.seed(5)", "file": program.source_ref.logical_ref, "line": 2}
    ]


def test_scan_survives_source_too_deep_to_unparse_or_parse():
    """Red-team witness (#1116): valid source whose seed argument is a 331-term
    sum made ``ast.unparse`` raise RecursionError, which escaped into the
    validator. Fails if the scan raises instead of recording a bounded call,
    or if a source too deep even to parse is not treated as unparsable."""
    deep = "import random\nrandom.seed(" + "+".join(["1"] * 331) + ")\n"
    (call,) = scan_seed_calls(deep, file="deep.py")
    assert call.line == 2 and len(call.call) <= 200
    deeper = "import random\nrandom.seed(" + "+".join(["1"] * 10000) + ")\n"
    assert scan_seed_calls(deeper, file="deeper.py") == ()


def test_program_seeds_differ_by_program_and_attempt_and_reproduce():
    """Fails if two programs, or two attempts of one program, in one request
    share a stream (correlated bootstrap draws), or if a position does not
    reproduce on resume. Literals: run seed 1, no iteration."""
    first = program_seed(1, iteration=None, index=0)
    assert first == 283021924344702021 == program_seed(1, iteration=None, index=0)
    assert program_seed(1, iteration=None, index=1) == 4775709856641324212
    assert program_seed(1, iteration=None, index=0, attempt=2) == 2862037300665354629


def test_declared_program_seed_outside_the_numpy_range_is_refused(tmp_path):
    """Fails if a declared seed >= 2**32 is accepted (it would alias in
    ``np.random.seed``) or the refusal does not say why."""
    with pytest.raises(ValueError, match="2\\*\\*32 - 1"):
        _persist_program(
            tmp_path,
            "def analyze(inputs, parameters, output_directory):\n    return {}\n",
            keys=("seeded",),
            seed=2**32,
        )
