"""Witnesses for the Stage-3 shared compose-and-score module (contract §4).

Each test names the defect only it can catch. ``score_vector`` is stubbed at
the module boundary (``stage3_common.score_vector``), so no HDF5 or anchor
arithmetic runs; the frozen TIDMAD formula is exercised by its own suite, not
here — this file guards the COMPOSITION semantics the contract froze:

* exactly ONE scoring call over all 20 files (a per-band decomposition —
  call count > 1 — FAILS);
* a missing index is a named ``NotScoreableError``-class refusal, never a
  silent skip;
* a duplicate index is a refusal naming BOTH paths;
* a partial ``files`` range — the forbidden per-band construction
  (F-SCAND-1) — is inexpressible;
* SRI-11 scope pin: the deliberate omission of ANY aggregation in the
  stage3 modules is pinned by a census that fails the moment someone
  implements a per-band mean.
"""

from __future__ import annotations

import ast
import json
import math
import os
from pathlib import Path

import pytest

import scripts.stage3.stage3_common as stage3_common
from execute_tools.build_anchor_map import default_anchor_map_path
from execute_tools.dataset_config import NUM_FILES, SEGMENTS_PER_FILE, resolve_dataset_profile
from execute_tools.deliverable_spec import DeliverableNaming
from execute_tools.evaluation_metric import NotScoreableError, derive_tidmad_metric_spec
from scripts.stage3.stage3_common import (
    COMPOSITION_CONTRACT_ID,
    EXPECTED_S_MAX,
    compose_and_score,
)

NAMING = DeliverableNaming()

#: The stamped spec every call transports (tests play the STAMPING side
#: here — production callers reconcile persisted 09a stamps instead).
RECONCILED_SPEC = derive_tidmad_metric_spec(resolve_dataset_profile())


def _touch_deliverable(
    directory: Path,
    index: int,
    *,
    model_type: str = "wavenet",
    run_name: str = "iter_001",
    exp_id: str = "expA",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    name = NAMING.name(
        model_type=model_type, run_name=run_name, exp_id=exp_id, input_identity=index
    )
    path = directory / name
    path.write_bytes(f"h5-stub:{exp_id}:{index}".encode())
    return path


class _ScoreVectorStub:
    """Records every call; returns a fixed (file_vector, scalar) 2-tuple."""

    def __init__(self, vector: list[float | None] | None = None, scalar: float = -2.5) -> None:
        self.calls: list[dict] = []
        self.vector = [0.5] * NUM_FILES if vector is None else vector
        self.scalar = scalar

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return list(self.vector), self.scalar


@pytest.fixture
def score_stub(monkeypatch) -> _ScoreVectorStub:
    stub = _ScoreVectorStub()
    monkeypatch.setattr(stage3_common, "score_vector", stub)
    return stub


def _pool_two_dirs(tmp_path: Path) -> tuple[Path, Path, dict[int, Path]]:
    """A clean pooled set: indices 0-9 in dir_a, 10-19 in dir_b."""
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    paths: dict[int, Path] = {}
    for index in range(10):
        paths[index] = _touch_deliverable(dir_a, index, exp_id="expA")
    for index in range(10, NUM_FILES):
        paths[index] = _touch_deliverable(dir_b, index, exp_id="expB", model_type="punet")
    return dir_a, dir_b, paths


def test_one_scoring_call_over_all_20_files(tmp_path, score_stub):
    """THE one-call witness (contract §4).

    Fails when compose_and_score scores per band (call count 4 != 1), when
    any file is left out of the single call's sample set, or when the call
    departs from the reuse anchor's construction (anchor s_max ruler, full
    segments, non-legacy mode, absolute-filename resolution).
    """
    dir_a, dir_b, paths = _pool_two_dirs(tmp_path)

    file_vector, scalar = compose_and_score(
        [str(dir_a), str(dir_b)], reconciled_spec=RECONCILED_SPEC
    )

    assert len(score_stub.calls) == 1, (
        f"score_vector must be invoked EXACTLY ONCE over the full pooled set; "
        f"got {len(score_stub.calls)} calls — a per-band call count is the "
        f"forbidden construction."
    )
    call = score_stub.calls[0]
    assert set(call["sample_set"]) == set(range(NUM_FILES))
    assert all(
        call["sample_set"][index] == list(range(SEGMENTS_PER_FILE)) for index in range(NUM_FILES)
    )
    assert call["legacy_mode"] is False
    assert math.isclose(call["s_max"], EXPECTED_S_MAX, rel_tol=0.0, abs_tol=1e-6)
    committed = json.loads(Path(default_anchor_map_path()).read_text())
    assert set(call["anchor_map"]) == set(committed["anchors"])
    assert call["raw_data_dir"] == stage3_common.TIDMAD_DATA_DIR
    resolver = call["denoised_filename_fn"]
    for index in range(NUM_FILES):
        resolved = resolver(index)
        assert os.path.isabs(resolved)
        assert resolved == str(paths[index])
    assert file_vector == [0.5] * NUM_FILES
    assert scalar == -2.5


def test_missing_index_is_a_named_refusal(tmp_path, score_stub):
    """A missing file index refuses by name — never a silent skip, and the
    scorer is never invoked on the incomplete set."""
    dir_a, dir_b, _ = _pool_two_dirs(tmp_path)
    missing = dir_a / NAMING.name(
        model_type="wavenet", run_name="iter_001", exp_id="expA", input_identity=7
    )
    missing.unlink()

    with pytest.raises(NotScoreableError) as excinfo:
        compose_and_score([str(dir_a), str(dir_b)], reconciled_spec=RECONCILED_SPEC)

    result = excinfo.value.result
    assert result.verdict.contract_id == COMPOSITION_CONTRACT_ID
    assert any(
        failure.requirement == "exactly_one_deliverable_per_input" and failure.input_identity == 7
        for failure in result.verdict.failures
    )
    assert score_stub.calls == [], "the scorer must not run over an incomplete pooled set"


def test_duplicate_index_is_refused_naming_both_paths(tmp_path, score_stub):
    """A duplicated file index refuses naming BOTH offending absolute paths."""
    dir_a, dir_b, _ = _pool_two_dirs(tmp_path)
    second = _touch_deliverable(dir_b, 3, exp_id="expOther", model_type="rnn")
    first = dir_a / NAMING.name(
        model_type="wavenet", run_name="iter_001", exp_id="expA", input_identity=3
    )

    with pytest.raises(NotScoreableError) as excinfo:
        compose_and_score([str(dir_a), str(dir_b)], reconciled_spec=RECONCILED_SPEC)

    failures = [
        failure
        for failure in excinfo.value.result.verdict.failures
        if failure.requirement == "exactly_one_deliverable_per_input"
        and failure.input_identity == 3
    ]
    assert len(failures) == 1
    assert str(first) in failures[0].detail
    assert str(second) in failures[0].detail
    assert score_stub.calls == []


@pytest.mark.parametrize(
    "bad_range",
    [
        range(0, 4),
        range(4, 10),
        range(10, 15),
        range(15, 20),
        range(0, 19),
        range(1, 20),
        range(0, 20, 2),
    ],
    ids=["band0-3", "band4-9", "band10-14", "band15-19", "short", "shifted", "strided"],
)
def test_partial_files_range_is_inexpressible(tmp_path, score_stub, bad_range):
    """The forbidden per-band construction cannot be requested (F-SCAND-1):
    any non-full ``files`` range — each campaign band included — is refused
    before any directory is even scanned."""
    dir_a, dir_b, _ = _pool_two_dirs(tmp_path)

    with pytest.raises(ValueError, match=r"full-scope|F-SCAND-1"):
        compose_and_score(
            [str(dir_a), str(dir_b)], files=bad_range, reconciled_spec=RECONCILED_SPEC
        )
    assert score_stub.calls == []


def test_non_none_sample_set_is_refused(tmp_path, score_stub):
    """A partial sample set is not legal here (contract §4: typed ``None``)."""
    dir_a, dir_b, _ = _pool_two_dirs(tmp_path)

    with pytest.raises(ValueError, match="sample_set must be None"):
        compose_and_score(
            [str(dir_a), str(dir_b)], sample_set={0: [0]}, reconciled_spec=RECONCILED_SPEC
        )  # type: ignore[arg-type]
    assert score_stub.calls == []


def test_out_of_range_identity_is_refused(tmp_path, score_stub):
    """A stray deliverable outside 0..19 is a malformed pooled set — refused,
    not silently ignored."""
    dir_a, dir_b, _ = _pool_two_dirs(tmp_path)
    _touch_deliverable(dir_b, 42, exp_id="expStray")

    with pytest.raises(NotScoreableError) as excinfo:
        compose_and_score([str(dir_a), str(dir_b)], reconciled_spec=RECONCILED_SPEC)

    assert any(
        failure.requirement == "input_identity_in_range" and failure.input_identity == 42
        for failure in excinfo.value.result.verdict.failures
    )
    assert score_stub.calls == []


def test_swapped_anchor_ruler_is_refused(tmp_path, score_stub, monkeypatch):
    """An anchor artifact whose s_max is off the pinned canonical ruler is
    refused (the reuse anchor's own EXPECTED_S_MAX check, mirrored)."""
    dir_a, dir_b, _ = _pool_two_dirs(tmp_path)
    monkeypatch.setattr(
        stage3_common, "load_anchor_map", lambda path: {"s_max": 1.0, "anchors": {}}
    )

    with pytest.raises(NotScoreableError) as excinfo:
        compose_and_score([str(dir_a), str(dir_b)], reconciled_spec=RECONCILED_SPEC)

    assert any(
        failure.requirement == "canonical_anchor_ruler"
        for failure in excinfo.value.result.verdict.failures
    )
    assert score_stub.calls == []


def test_uncomputable_per_file_entry_is_refused(tmp_path, monkeypatch):
    """A ``None`` per-file entry (all segments NaN-filtered) is refused by
    name — never passed through inside a ``list[float]``."""
    dir_a, dir_b, _ = _pool_two_dirs(tmp_path)
    vector: list[float | None] = [0.5] * NUM_FILES
    vector[5] = None
    stub = _ScoreVectorStub(vector=vector)
    monkeypatch.setattr(stage3_common, "score_vector", stub)

    with pytest.raises(NotScoreableError) as excinfo:
        compose_and_score([str(dir_a), str(dir_b)], reconciled_spec=RECONCILED_SPEC)

    assert any(
        failure.requirement == "per_file_score_computable" and failure.input_identity == 5
        for failure in excinfo.value.result.verdict.failures
    )


def test_committed_anchor_smax_matches_pinned_ruler():
    """The module's pinned ruler equals the committed reference artifact's
    s_max — the same pin ``score_tidmad_official_banded.py:74`` carries.
    Fails when either the artifact or the pin moves alone."""
    committed = json.loads(Path(default_anchor_map_path()).read_text())
    assert math.isclose(float(committed["s_max"]), EXPECTED_S_MAX, rel_tol=0.0, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# SRI-11 scope pin
# ---------------------------------------------------------------------------

_FORBIDDEN_CALL_NAMES = {"mean", "fmean", "nanmean", "average"}


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def test_sri11_no_aggregation_expressible_in_stage3_modules():
    """SRI-11 scope pin: the DELIBERATE OMISSION of aggregation is a test.

    The stage3 modules compose scoring INPUTS and never aggregate — the only
    scalar in Stage 3 is ``score_vector``'s own return (F-SCAND-1: a
    per-band mean over per-file scores is the forbidden construction, and
    the reuse anchor's safety is that no band scalar exists to average).

    This census turns that scope decision into something that speaks up at
    the site of the change (SRI-11): implementing a per-band mean requires a
    division or a mean-family call, and BOTH are banned here — pathlib's
    ``/`` operator included, which is why these modules use ``os.path.join``.
    It also pins contract §4's one-wrapper rule structurally: exactly ONE
    ``score_vector`` call site exists, in ``stage3_common``, and no writer
    re-inlines it.

    How it fails: add ``sum(band)/len(band)``, ``statistics.mean(...)``,
    ``np.mean(...)`` or a second ``score_vector`` call anywhere under
    ``scripts/stage3/`` and the census goes RED naming the file and line.
    """
    stage3_dir = Path(stage3_common.__file__).resolve().parent
    modules = sorted(stage3_dir.glob("*.py"))
    names = {module.name for module in modules}
    # Census-blindness guard: the file set must actually contain the owners.
    assert {"stage3_common.py", "stage3_composed_best.py"} <= names

    score_vector_calls: dict[str, list[int]] = {}
    for module in modules:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div | ast.FloorDiv):
                pytest.fail(
                    f"{module.name}:{node.lineno} contains a division — a mean cannot be "
                    f"built without one; per-band aggregation is refused in stage3 "
                    f"(SRI-11 pin, F-SCAND-1)."
                )
            if isinstance(node, ast.Call):
                name = _call_name(node)
                if name in _FORBIDDEN_CALL_NAMES:
                    pytest.fail(
                        f"{module.name}:{node.lineno} calls {name}() — aggregation is "
                        f"refused in stage3 (SRI-11 pin, F-SCAND-1)."
                    )
                if name == "score_vector":
                    score_vector_calls.setdefault(module.name, []).append(node.lineno)

    assert list(score_vector_calls) == ["stage3_common.py"], (
        f"score_vector call sites outside stage3_common: {score_vector_calls} — "
        f"contract §4: all writers call compose_and_score, none re-inlines the scorer."
    )
    assert len(score_vector_calls["stage3_common.py"]) == 1, (
        f"stage3_common must contain EXACTLY ONE score_vector call site; "
        f"found lines {score_vector_calls['stage3_common.py']}."
    )
