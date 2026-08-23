"""Step 06 — Checkpoint 0: the two-route scoring parity oracle.

Design: ``docs/design/generic_framework_upgrade/step_06_metric_interface.md``
§1.1, §11 (Checkpoint 0), §19 C0.

**What is pinned, and why it was never pinned before.** SIDERIUS has two live
entry points into the frozen TIDMAD scorer:

* route (i) — in-process: the tuner calls ``TidmadSandbox.score_vector``
  (``core/sandbox_executor.py:1858``), which validates the scope and delegates
  to ``execute_tools.scoring_utils.score_vector``;
* route (ii) — subprocess: ``TidmadSandbox.execute_scoring`` (``:1899``) spawns
  ``execute_tools/denoising_score_single.py`` and merges its ``--output_json``.

Step 06 routes BOTH through the metric handle. A parity baseline captured
*after* that migration proves nothing about it, so this module captures — on
unmodified production code — the **existing TIDMAD result and its key/output
shape** on each route, as HARDCODED LITERALS, and asserts the two routes are
equal to each other. It is deliberately worded as "the existing TIDMAD result",
not as ``(file_vector, scalar)``: a future scalar-only metric is not bound by
this oracle's shape (design §11, revision 3).

**Fixture geometry — a bounded deviation from the design's precedent.** The
design named the 05c Checkpoint-C 4,096-sample geometry as the precedent. That
geometry cannot be *scored*: ``scoring_utils.get_one_sec_psd:143`` slices
``SEGMENT_LENGTH`` samples from the MODULE constant (10,000,000), not from the
profile, and a 4,096-sample file reshapes to ``(0, 10_000_000)`` and raises.
The NUM-6 monkeypatch (``test_step00_numeric_baselines.py:171``) cannot reach
the subprocess route. So the fixture is FULL-LENGTH — one 10 M-sample segment,
one file, both channels — which the unpatched scorer handles in about a second
per route and which is therefore honest on both routes with the same bytes.

**Hermetic subprocess route.** ``execute_scoring``'s argv carries neither
``--raw_data_dir`` nor ``--anchor_map``; the child defaults the raw directory
to ``TIDMAD_DATA_DIR`` (a machine yaml value) and the anchor map to the
committed ``reference_data/segment_anchors.json``. To run the REAL argv with
zero machine data, the run-bound profile declares ``segments_per_file=1`` and
an ABSOLUTE ``validation_file_pattern`` under ``tmp_path``:
``_write_dataset_profile_config`` (``:1237``) transports that profile, and the
child's ``os.path.join(TIDMAD_DATA_DIR, absolute_name)`` resolves to the tmp
raw file — the same ``os.path.join`` property the tuner's
``_build_denoised_filename`` (``ml_hyperparameter_tune_agent.py:1085-1088``)
documents and relies on for the denoised side. ``s_max`` comes from the
committed anchor artifact on both routes (the child's default; the parent
loads the same file), so the two routes see identical inputs.

**Not re-captured here** (already pinned): the frozen-formula numeric pins
(``test_step00_numeric_baselines.py``, ``test_scoring_helpers.py``,
``test_phase67_scoring_precision.py``); the ``per_file_best`` key set and
``metric_id`` (``test_per_file_best.py:719``, NUM-8); the ``StubSandbox``
2-tuple / length-9 pseudo contract (``test_stub_sandbox.py:332-360``).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core.sandbox_executor import TidmadSandbox
from execute_tools.array2h5 import create_abra_file
from execute_tools.build_anchor_map import default_anchor_map_path, load_anchor_map
from execute_tools.dataset_config import (
    NUM_FILES,
    TIDMAD_PROFILE,
    DatasetProfile,
    bind_dataset_profile,
    tidmad_topology,
)
from execute_tools.deliverable_spec import derive_tidmad_deliverable_spec

REPO_ROOT = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# Fixture identifiers — distinguishable so an ordering or substitution defect
# is visible in the argv golden (05c C0 pattern).
# ---------------------------------------------------------------------------
EXP_ID = "c0exp"
RUN_NAME = "c0run"
MODEL_TYPE = "wavenet"
FILE_INDEX = 0

# The scorer's own segment length (``scoring_utils.SEGMENT_LENGTH``), stated as
# a literal here on purpose: this module pins what production DOES today, and
# a fixture that silently followed a later change to the constant would stop
# being an oracle for the values below.
SEGMENT_SAMPLES = 10_000_000

# Route (i) / route (ii) hardcoded literals — captured 2026-08-15 at
# 530f574c on unmodified production code, from the fixture below
# (``_signal(seed=10)`` raw, ``_signal(seed=20)`` denoised CH1). Never
# re-derived by calling the code under test.
EXPECTED_SCALAR = 5.174659969078518
EXPECTED_FILE0 = 5434.0608313142075
EXPECTED_VECTOR_LENGTH = 20  # ``[None] * NUM_FILES`` — a TIDMAD-topology fact
EXPECTED_OUTPUT_JSON_KEYS = ["denoising_score", "file_vector"]

# The two normalizations of the argv golden (05c C0 pattern): the interpreter
# path and the pytest tmp workspace are the only ephemeral tokens.
PYTHON = "<PYTHON>"
WORKSPACE = "<WS>"


def _signal(seed: int) -> np.ndarray:
    """A deterministic int8 signal: a sinusoid plus seeded Gaussian noise.

    Sinusoid so the PSD has a real peak (``get_snr`` finds it and the
    ``noise <= 1e-10`` guard does not trip); seeded noise so the raw and the
    denoised sides differ and the value is reproducible bit-for-bit.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(SEGMENT_SAMPLES)
    sine = 20.0 * np.sin(2 * np.pi * t / 64.0)
    return np.clip(sine + rng.normal(0, 3.0, SEGMENT_SAMPLES), -127, 127).astype(np.int8)


def _bound_profile(raw_pattern: str) -> DatasetProfile:
    """TIDMAD's declaration with only two facts changed for the fixture.

    ``segments_per_file=1`` makes the child's ``sample_set`` exactly
    ``{FILE_INDEX: [0]}`` (``denoising_score_single.py:190``); the absolute
    ``validation_file_pattern`` is what makes the child's raw read hermetic.
    Channel identity and encoding are TIDMAD's, so the derived deliverable
    spec is the shipped default.
    """
    return TIDMAD_PROFILE.model_copy(
        update={
            "dataset": tidmad_topology(TIDMAD_PROFILE).dataset.model_copy(
                update={"segments_per_file": 1, "validation_file_pattern": raw_pattern}
            )
        }
    )


@pytest.fixture(scope="module")
def oracle_fixture(tmp_path_factory):
    """One raw file + one deliverable, written ONCE for the module.

    Both are written by the REAL writer ``create_abra_file`` (the production
    deliverable path, ``inference_single.py:824-830`` / ``:983-989``) through the
    derived TIDMAD storage, so layout, chunking and the instrument attrs the
    scorer reads (``scoring_utils.py:159-164``) are exactly what production
    writes. The raw side is written the same way: TIDMAD raw files share the
    layout, and this keeps the fixture free of a second hand-rolled layout.
    """
    root = tmp_path_factory.mktemp("step06_c0")
    raw_dir = root / "raw"
    workspace = root / "ws"
    raw_dir.mkdir()
    workspace.mkdir()

    raw_pattern = str(raw_dir / "raw_validation_{file_index:04d}.h5")
    profile = _bound_profile(raw_pattern)
    spec = derive_tidmad_deliverable_spec(profile)

    raw_signal = _signal(seed=10)
    create_abra_file(
        raw_pattern.format(file_index=FILE_INDEX),
        raw_signal,
        raw_signal,
        indexed=False,
        storage=spec.storage,
    )
    deliverable_name = spec.naming.name(
        model_type=MODEL_TYPE, run_name=RUN_NAME, exp_id=EXP_ID, file_index=FILE_INDEX
    )
    create_abra_file(
        str(workspace / deliverable_name),
        _signal(seed=20),
        raw_signal,
        indexed=False,
        storage=spec.storage,
    )
    return {
        "profile": profile,
        "workspace": workspace,
        "deliverable_path": str(workspace / deliverable_name),
    }


def _anchor_inputs() -> tuple[dict, float]:
    data = load_anchor_map(default_anchor_map_path())
    return data["anchors"], float(data["s_max"])


def _route_i(fx) -> tuple[list, float]:
    """Route (i): the tuner's live in-process call, verbatim in shape
    (``ml_hyperparameter_tune_agent.py:5321-5326``: an absolute denoised path
    from the naming authority, anchors and ``s_max`` from the anchor map)."""
    anchors, s_max = _anchor_inputs()
    with bind_dataset_profile(fx["profile"]):
        sandbox = TidmadSandbox(
            run_name=RUN_NAME, workspace=str(fx["workspace"]), file_index=FILE_INDEX
        )
        return sandbox.score_vector(
            sample_set={FILE_INDEX: [0]},
            anchor_map=anchors,
            s_max=s_max,
            denoised_filename_fn=lambda _fi: fx["deliverable_path"],
        )


def _route_ii(fx, monkeypatch) -> dict:
    """Route (ii): the REAL ``execute_scoring`` subprocess, unmodified argv."""
    monkeypatch.chdir(REPO_ROOT)  # the argv names the script by a repo-relative path
    with bind_dataset_profile(fx["profile"]):
        sandbox = TidmadSandbox(
            run_name=RUN_NAME, workspace=str(fx["workspace"]), file_index=FILE_INDEX
        )
        return sandbox.execute_scoring(EXP_ID, RUN_NAME, MODEL_TYPE, {}, {}, {})


# ---------------------------------------------------------------------------
# 1. Route (i) — the existing TIDMAD result and shape, in-process
# ---------------------------------------------------------------------------


def test_c0_route_i_in_process_result_and_shape(oracle_fixture):
    """Guards ``TidmadSandbox.score_vector`` (``sandbox_executor.py:1858-1897``)
    → ``scoring_utils.score_vector`` (``:491-687``): the existing TIDMAD result
    is a per-file vector of the topology's length with the scored file's
    linear value and ``None`` elsewhere, plus one log-space scalar."""
    file_vector, scalar = _route_i(oracle_fixture)
    assert scalar == EXPECTED_SCALAR
    assert len(file_vector) == EXPECTED_VECTOR_LENGTH
    assert file_vector[FILE_INDEX] == EXPECTED_FILE0
    assert all(v is None for i, v in enumerate(file_vector) if i != FILE_INDEX)


# ---------------------------------------------------------------------------
# 2. Route (ii) — the existing TIDMAD result and shape, REAL subprocess
# ---------------------------------------------------------------------------


@pytest.mark.allow_real_subprocess  # the REAL scoring child is the point (design §19 C0 §4)
def test_c0_route_ii_real_subprocess_result_and_output_keys(oracle_fixture, monkeypatch):
    """Guards ``execute_scoring`` (``:1899-1970``) + ``denoising_score_single.py``
    (``:186-227``): the child merges exactly the two keys below into
    ``--output_json`` and the parent returns them under ``results``."""
    result = _route_ii(oracle_fixture, monkeypatch)
    assert result["status"] == "success", result
    results = result["results"]
    assert sorted(results) == EXPECTED_OUTPUT_JSON_KEYS
    assert results["denoising_score"] == EXPECTED_SCALAR
    assert len(results["file_vector"]) == EXPECTED_VECTOR_LENGTH
    assert results["file_vector"][FILE_INDEX] == EXPECTED_FILE0
    assert all(v is None for i, v in enumerate(results["file_vector"]) if i != FILE_INDEX)


# ---------------------------------------------------------------------------
# 3. The two routes agree with EACH OTHER (never asserted before this module)
# ---------------------------------------------------------------------------


@pytest.mark.allow_real_subprocess
def test_c0_the_two_routes_agree_exactly(oracle_fixture, monkeypatch):
    """Same arithmetic, same inputs → exact float equality on scalar and every
    per-file value. A divergence here is a FINDING to record, not to fix in
    C0 (design §19 C0 §6)."""
    file_vector, scalar = _route_i(oracle_fixture)
    child = _route_ii(oracle_fixture, monkeypatch)["results"]
    assert child["denoising_score"] == scalar
    assert child["file_vector"] == file_vector


# ---------------------------------------------------------------------------
# 4. The ordered ``execute_scoring`` argv (05c §4.2 pattern; NOT pinned before)
# ---------------------------------------------------------------------------


def _normalize(cmd: list[str], workspace: str) -> list[str]:
    root = os.path.abspath(workspace)
    # Step 11 C7 (F-11-7): the three child scripts are now named by ABSOLUTE
    # path, anchored at the repository root rather than at the caller's cwd —
    # the launch used to work only because every launcher happened to chdir
    # to the repository first. The path is normalized back to its
    # repo-relative form here, for two reasons:
    #
    #   * a golden must never embed a machine-specific absolute path
    #     (the repository-portability rule), and
    #   * this comparison exists to pin the ARGUMENT LIST — its flags, its
    #     values and its ORDER — not the anchoring mechanism, which
    #     `tests/unit/core/test_step11_c7_spawn_hygiene.py` owns and proves
    #     absolute, existing and cwd-independent.
    #
    # Nothing else about these goldens moved.
    from core.sandbox_executor import SIDERIUS_ROOT

    siderius_root = os.path.abspath(SIDERIUS_ROOT) + os.sep
    normalized = []
    for tok in cmd:
        if tok == sys.executable:
            normalized.append(PYTHON)
            continue
        if tok.startswith(siderius_root) and tok.endswith(".py"):
            normalized.append(tok[len(siderius_root) :])
            continue
        normalized.append(tok.replace(root, WORKSPACE))
    return normalized


@patch("core.sandbox_executor.subprocess.run")
def test_c0_execute_scoring_argv_ordered_golden(mock_run, tmp_path):
    """The COMPLETE ordered scoring argv (``sandbox_executor.py:1919-1939``).

    ``test_sandbox_executor.py:456-483`` asserts only ``stdout``/``stderr``
    kwargs; nothing pins the token list. C3 must leave it unchanged (design §9,
    §19 C3: no new argv, or the Stage-A claim is downgraded in writing) — this
    golden is what forces that conversation.
    """
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = ""
    mock.stderr = ""
    mock_run.return_value = mock
    sandbox = TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path), file_index=FILE_INDEX)
    # The child would have merged into this JSON; with subprocess mocked the
    # pre-created ``{}`` is read back and the call must still return success.
    result = sandbox.execute_scoring(EXP_ID, RUN_NAME, MODEL_TYPE, {}, {}, {})
    assert result == {"status": "success", "results": {}}

    (cmd,), _ = mock_run.call_args
    assert _normalize(cmd, str(tmp_path)) == [
        "<PYTHON>",
        "execute_tools/denoising_score_single.py",
        "--mode",
        "agent",
        "-m",
        "wavenet",
        "--dataset_profile_json",
        "<WS>/configs/c0run/dataset_profile_c0exp.json",
        "--exp_id",
        "c0exp",
        "--run_name",
        "c0run",
        "--output_json",
        "<WS>/records/c0run/score_results_wavenet_c0exp.json",
        "--data_dir",
        "<WS>",
        "--file_index",
        "0",
    ]
    # The transported profile is what the child derives its instance from
    # (05c §3.2a Option A); assert it was materialised, not merely named.
    transported = json.loads(
        (tmp_path / "configs" / RUN_NAME / "dataset_profile_c0exp.json").read_text()
    )
    assert transported == TIDMAD_PROFILE.to_wire()
