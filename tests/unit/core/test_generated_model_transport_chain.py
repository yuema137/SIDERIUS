"""V21 PR C4 — the generated-model transport chain, hop by hop.

This is PR C's **primary hard-acceptance layer** and the mechanical
enforcement of Binding Principle 2:

    Parent-process reachability is NEVER evidence of subprocess
    reachability.

The chain a never-before-seen generated model must survive:

    generated plugin
      -> plugin directory
      -> worker spec (carries plugin_dir)
      -> subprocess environment (SIDERIUS_PLUGIN_DIRS + PYTHONPATH)
      -> child startup
      -> child import
      -> registry reconstruction
      -> output/config lookup
      -> measurement executor's config validation

``tests/unit/core/test_measurement_worker_plugin_transport.py`` already
covers the #184 hop (the worker being spawned with no ``env=``). This
module differs in three ways that matter:

* it asserts **every** hop, with a deletion matrix — removing any single
  hop must fail, which is the property that makes the chain a contract
  rather than a happy path;
* it runs **both output contracts**, because PR A's whole lesson was that a
  classifier-only proof hides regressor defects. Three consumers were
  found broken while every deterministic checkpoint was green;
* it asserts the post-C1 behaviour that a **missing** transport now fails
  **closed** rather than resolving to a default contract.

Every assertion is a value produced by a genuinely separate interpreter.
An in-process approximation cannot express any of this: the parent's
registry already holds the plugin, so calling the worker's functions
directly passes while the campaign dies. That is exactly how V20 attempt 3
lost all 15 formal promotions.

Portability: plugins are written to ``tmp_path``. Nothing reads
``agent_generated/models``, which is gitignored and empty on CI.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Names are unique to this module so a leaked registry entry from another
# test can never satisfy an assertion here.
_CLASSIFIER = "c4_novel_classifier_transport"
_REGRESSOR = "c4_novel_regressor_transport"


def _plugin_source(model_type: str, output_type: str) -> str:
    """A minimal but genuinely valid agent-generated plugin."""
    class_stem = "".join(part.title() for part in model_type.split("_"))
    if output_type == "classifier":
        head = "self.head = nn.Conv1d(8, 256, 1)"
        forward = "return self.head(self.emb(x).transpose(1, 2))"
    else:
        head = "self.head = nn.Conv1d(8, 1, 1)"
        forward = "return self.head(self.emb(x).transpose(1, 2)).squeeze(1)"

    return textwrap.dedent(f'''
        """Never-before-seen {output_type} plugin, written by the C4 fixture."""

        import torch.nn as nn
        from pydantic import BaseModel

        PLUGIN_MODEL_TYPE = "{model_type}"
        PLUGIN_OUTPUT_TYPE = "{output_type}"


        class {class_stem}Config(BaseModel):
            model_type: str = "{model_type}"
            segmentation_size: int = 64


        class {class_stem}Model(nn.Module):
            def __init__(self, config):
                super().__init__()
                self.emb = nn.Embedding(256, 8)
                {head}

            def forward(self, x):
                {forward}


        PLUGIN_CONFIG_CLASS = {class_stem}Config
        PLUGIN_MODEL_CLASS = {class_stem}Model
    ''')


@pytest.fixture
def plugin_dir(tmp_path: Path) -> Path:
    """A run-scoped directory holding one novel plugin of each contract."""
    d = tmp_path / "run_scoped_plugins"
    d.mkdir()
    (d / f"{_CLASSIFIER}.py").write_text(_plugin_source(_CLASSIFIER, "classifier"))
    (d / f"{_REGRESSOR}.py").write_text(_plugin_source(_REGRESSOR, "regressor"))
    return d


# ---------------------------------------------------------------------------
# The child probe — runs the REAL worker function in a REAL subprocess
# ---------------------------------------------------------------------------

_CHILD_PROBE = textwrap.dedent(
    """
    import contextlib, io, json, os, sys

    model_type = sys.argv[1]
    out = {}
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            # The variable the transport is supposed to deliver. Recorded so a
            # failure distinguishes "env never arrived" from "env arrived but
            # the consumer ignored it" -- #184 vs #185.
            out["plugin_dirs_env"] = os.environ.get("SIDERIUS_PLUGIN_DIRS")

            from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
            from core.runtime_control.gpu_measurement_worker_main import (
                validate_candidate_configs,
            )

            spec = GpuMeasurementSpec.model_validate(json.loads(sys.argv[2]))

            # THE hop that decided V20: the executor's own config validation.
            out["rejection"] = validate_candidate_configs(spec)

            # Registry reconstruction, observed rather than assumed.
            from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
            out["config_registered"] = model_type in PLUGIN_CONFIG_REGISTRY

            # The output contract must survive the boundary too. After C1 an
            # unresolvable contract raises instead of defaulting.
            from ml_models.plugin_loader import (
                UnknownOutputContractError,
                get_output_type,
            )
            try:
                out["output_type"] = get_output_type(model_type)
            except UnknownOutputContractError:
                out["output_type"] = "RAISED-UNKNOWN"
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        out["error"] = f"{type(exc).__name__}: {exc}"
    print("C4RESULT " + json.dumps(out))
    """
)


def _spec_payload(model_type: str, plugin_dir: Path | None, tmp_path: Path) -> str:
    """Build a **real** ``GpuMeasurementSpec`` payload for ``model_type``.

    Constructed through the actual model so a schema change breaks this
    fixture loudly instead of letting it drift into asserting on a shape
    production no longer uses.
    """
    from core.runtime_control.gpu_measurement_identity import build_planned_identity
    from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
    from core.runtime_control.gpu_requirement import CandidateMeasurementRequest

    spec = GpuMeasurementSpec(
        label="c4-transport-chain",
        request=CandidateMeasurementRequest(
            model_type=model_type,
            planned_identity=build_planned_identity(
                model_type=model_type, model_config={}, train_config={}
            ),
            request_id="req-c4trans",
            device_uuid="GPU-c30b6678-ff2a-f8b4-d378-af9681c6ceef",
            phase="training",
            deadline_seconds=120.0,
        ),
        model_config_payload={"segmentation_size": 64},
        train_config={"batch_size": 2, "optimizer_type": "adamw"},
        loss_config={"loss_type": "focal"},
        device="cpu",
        data_dir=None,
        training_steps=2,
        inference_batches=2,
        result_path=str(tmp_path / "c4_result.json"),
        journal_path=str(tmp_path / "c4_phases.ndjson"),
        worker_memory_limit_bytes=8 * 1024**3,
        plugin_dir=str(plugin_dir) if plugin_dir else None,
    )
    return spec.model_dump_json()


def _run_child(
    model_type: str,
    *,
    plugin_dir: Path | None,
    env_plugin_dir: Path | None,
    tmp_path: Path,
    pythonpath: bool = True,
) -> dict:
    """Spawn a real child and return its parsed probe result.

    ``plugin_dir`` is the hop carried by the SPEC; ``env_plugin_dir`` is the
    hop carried by the ENVIRONMENT. They are separate parameters precisely
    so a test can delete one and keep the other.
    """
    env = {k: v for k, v in os.environ.items() if k != "SIDERIUS_PLUGIN_DIRS"}
    if env_plugin_dir is not None:
        env["SIDERIUS_PLUGIN_DIRS"] = str(env_plugin_dir)
    if pythonpath:
        env["PYTHONPATH"] = str(REPO_ROOT)
    else:
        env.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _CHILD_PROBE,
            model_type,
            _spec_payload(model_type, plugin_dir, tmp_path),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=300,
    )
    for line in completed.stdout.splitlines():
        if line.startswith("C4RESULT "):
            return json.loads(line[len("C4RESULT ") :])
    raise AssertionError(
        "child produced no C4RESULT line\n"
        f"returncode: {completed.returncode}\n"
        f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
    )


# ---------------------------------------------------------------------------
# 1. The chain works, for BOTH contracts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model_type", "expected_contract"),
    [
        pytest.param(_CLASSIFIER, "classifier", id="novel_classifier"),
        pytest.param(_REGRESSOR, "regressor", id="novel_regressor"),
    ],
)
def test_a_novel_plugin_survives_the_whole_chain(
    plugin_dir, tmp_path, model_type, expected_contract
):
    """End to end, in a real child, for a model that has never existed.

    The regressor case is not decoration. PR A shipped three consumers
    still assuming the classifier contract while every deterministic
    checkpoint was green, and two of the three were found only by running
    real Gates.
    """
    got = _run_child(
        model_type, plugin_dir=plugin_dir, env_plugin_dir=plugin_dir, tmp_path=tmp_path
    )

    assert got.get("error") is None, got
    assert got["plugin_dirs_env"] == str(plugin_dir)
    assert got["config_registered"] is True
    assert got["output_type"] == expected_contract
    assert got["rejection"] is None, (
        f"the measurement executor rejected a valid generated model: {got['rejection']!r} "
        "— this is the V20 CONFIG_REJECTED shape"
    )


# ---------------------------------------------------------------------------
# 2. Hop-deletion matrix — removing any hop must fail
# ---------------------------------------------------------------------------


def test_hop_deleted_environment_variable_never_reaches_the_child(plugin_dir, tmp_path):
    """Delete the #184 hop: the child is spawned without the env var.

    This is the defect that aborted V20 attempt 2. The worker was spawned
    with no ``env=`` and inherited a parent environment that does not carry
    ``SIDERIUS_PLUGIN_DIRS``, because that variable is built per-sandbox for
    the sandbox's own children.
    """
    got = _run_child(_CLASSIFIER, plugin_dir=plugin_dir, env_plugin_dir=None, tmp_path=tmp_path)

    assert got["plugin_dirs_env"] is None
    assert got["config_registered"] is False
    assert got["rejection"] is not None, (
        "the executor accepted a model it could not possibly resolve — the "
        "fixture is not exercising the real validation path"
    )
    assert "no config class registered" in got["rejection"]


def test_hop_deleted_plugin_directory_is_empty(tmp_path):
    """Delete the source hop: the transport is intact but there is no plugin.

    Distinguishes "the pipe is broken" from "nothing was put in the pipe".
    Both must fail closed, and they must be distinguishable in the message.
    """
    empty = tmp_path / "empty_plugins"
    empty.mkdir()
    got = _run_child(_CLASSIFIER, plugin_dir=empty, env_plugin_dir=empty, tmp_path=tmp_path)

    assert got["plugin_dirs_env"] == str(empty)
    assert got["config_registered"] is False
    assert got["rejection"] is not None


def test_hop_deleted_output_contract_fails_closed_not_defaulted(tmp_path):
    """C1 and C4 compose across the process boundary.

    Before C1 an unresolvable model returned ``"classifier"`` in the child
    just as in the parent, so a regressor whose plugin failed to load was
    silently measured, trained and scored as a classifier. The child must
    now raise instead.

    Fails if: the silent default is restored anywhere — including in a
    subprocess, which is the one place a parent-only test cannot see.
    """
    empty = tmp_path / "no_plugins"
    empty.mkdir()
    got = _run_child(_REGRESSOR, plugin_dir=empty, env_plugin_dir=empty, tmp_path=tmp_path)

    assert got["output_type"] == "RAISED-UNKNOWN", (
        "an unregistered model resolved to a contract inside the child — the "
        "C1 silent default has returned across the process boundary"
    )


def test_the_child_cannot_be_satisfied_by_the_parents_registry(plugin_dir, tmp_path):
    """The property that makes every other assertion in this module mean
    something.

    The parent process running these tests has imported ``models_sandbox``
    and holds a populated registry. If any of that leaked into the child,
    the deletion cases above would pass for the wrong reason and the whole
    matrix would be theatre.

    Proven by construction: the parent registers this module's model names
    in its OWN registry, then spawns a child with the transport deleted. The
    child must still fail — its registry is genuinely its own.
    """
    import ml_models.models_format_sandbox as mfs
    from ml_models.models_format_sandbox import PUNetConfig

    # Contaminate the PARENT as hard as possible.
    mfs.PLUGIN_CONFIG_REGISTRY[_CLASSIFIER] = PUNetConfig
    try:
        assert _CLASSIFIER in mfs.PLUGIN_CONFIG_REGISTRY  # parent is dirty
        got = _run_child(_CLASSIFIER, plugin_dir=None, env_plugin_dir=None, tmp_path=tmp_path)
        assert got["config_registered"] is False, (
            "the child resolved a model that exists only in the PARENT's "
            "registry — process isolation is not real and no transport claim "
            "in this module can be trusted"
        )
    finally:
        mfs.PLUGIN_CONFIG_REGISTRY.pop(_CLASSIFIER, None)
