"""S2 / U5 — ``run_output_<run>.json`` is published through the atomic boundary.

REACHABILITY. ``test_per_file_best.py`` pins the producer's source text;
this proves the REAL ``finalize_run_output``, driven by the bounded pseudo
iteration, actually CALLS ``publish_json_atomically`` for the run output —
the artifact every iteration manifest hashes. Fails if a future edit
reintroduces a direct ``open(output_path, "w")`` write (the call list is
then empty) or leaves a temp file behind.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration

_HERE = Path(__file__).parent
_PREFLIGHT_FIXTURE = _HERE / "fixtures" / "step00_preflight_results.json"


def test_the_run_output_is_published_through_the_atomic_boundary(tmp_path_factory):
    from _pytest.monkeypatch import MonkeyPatch

    _records = importlib.import_module("nodes.ml_hyperparameter_tune_agent.records")
    real = _records.publish_json_atomically
    calls: list[tuple[str, dict]] = []

    def spy(path, obj, **kwargs):
        calls.append((path, dict(kwargs)))
        real(path, obj, **kwargs)

    preflight = json.loads(_PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"]
    mp = MonkeyPatch()
    tmp = tmp_path_factory.mktemp("u5_run_output_publish")
    try:
        mp.setattr(_records, "publish_json_atomically", spy)
        output, _bridge, _sandbox, workspace = run_bounded_pseudo_iteration(
            tmp, mp, preflight_results=preflight
        )
    finally:
        mp.undo()

    run_output = Path(workspace) / f"run_output_{output.run_name}.json"
    assert [c for c in calls if c[0] == str(run_output)] == [(str(run_output), {"indent": 4})]
    assert run_output.is_file()
    assert list(Path(workspace).glob(".run_output_*.tmp")) == []
