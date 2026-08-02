"""Resolved ordering reaches the training subprocess — and nothing else does.

Two properties matter at this boundary:

- the subprocess receives ONLY resolved values, never a proposal or an
  override, so it cannot re-derive precedence or disagree with the tuner;
- with no ordering in play, the argv is byte-for-byte what it was before
  V19 PR 2, so the default path is provably untouched.
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.sandbox_executor import StubSandbox, TidmadSandbox

PERMUTATION = [4, 6, 5, 9, 7, 8]
SAMPLE_SET = {4: [0], 5: [0], 6: [0], 7: [0], 8: [0], 9: [0]}


@pytest.fixture
def sandbox(tmp_path):
    return TidmadSandbox(run_name="ordering_propagation", workspace=str(tmp_path), file_index=6)


def _cmd_from(mock_run) -> list[str]:
    """The argv the sandbox handed to the subprocess runner."""
    assert mock_run.called, "training subprocess was never launched"
    return mock_run.call_args[0][0]


def _launch(sandbox, **ordering):
    """Capture the argv without launching anything.

    Patches ``_run_observed_subprocess`` — the single seam every GPU
    child now goes through (V20 B-C2a).

    This used to patch ``core.sandbox_executor.subprocess.run``, because
    with no runtime policy the plain branch called it directly. B-C2a
    routed that branch through the seam, and the old patch simply
    stopped intercepting: real training launched and the test hung for
    minutes rather than failing. A stub that no longer intercepts does
    not raise. Patching the seam is also the durable choice, since it is
    now the only launch point either branch can take.
    """
    with patch("core.sandbox_executor._run_observed_subprocess") as mock_run:
        mock_run.return_value = (
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            None,
        )
        try:
            sandbox.execute_training(
                exp_id="e1",
                run_name="ordering_propagation",
                model_type="wavenet",
                m_cfg={"model_type": "wavenet", "segmentation_size": 1000},
                t_cfg={"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"},
                l_cfg={},
                sample_set=SAMPLE_SET,
                **ordering,
            )
        except Exception:
            # The mocked runner returns no result; we only care about argv.
            pass
        return _cmd_from(mock_run)


def test_default_run_emits_no_ordering_flags(sandbox):
    """Pre-PR2 argv parity: the flags appear only when ordering is in use."""
    cmd = _launch(sandbox)
    assert "--order_strategy" not in cmd
    assert "--file_order_json" not in cmd


def test_explicit_shuffle_also_emits_nothing(sandbox):
    """'shuffle' IS the default, so naming it changes no argv."""
    cmd = _launch(sandbox, order_strategy="shuffle")
    assert "--order_strategy" not in cmd


def test_sequential_is_forwarded(sandbox):
    cmd = _launch(sandbox, order_strategy="sequential")
    assert "--order_strategy" in cmd
    assert cmd[cmd.index("--order_strategy") + 1] == "sequential"


def test_file_order_is_written_to_json_in_the_given_order(sandbox):
    cmd = _launch(sandbox, order_strategy="sequential", file_order=PERMUTATION)
    assert "--file_order_json" in cmd
    path = cmd[cmd.index("--file_order_json") + 1]
    assert os.path.isfile(path)
    with open(path) as f:
        assert json.load(f) == PERMUTATION, "the permutation must not be reordered"


def test_subprocess_never_sees_proposal_or_override_material(sandbox):
    """The engine consumes resolved values only; there is no flag through
    which a proposal or override could reach it."""
    cmd = _launch(sandbox, order_strategy="sequential", file_order=PERMUTATION)
    joined = " ".join(cmd)
    assert "proposed" not in joined
    assert "override" not in joined
    assert "resolution_source" not in joined


# ---- skill wrapper passthrough ----


class _RecordingSandbox:
    def __init__(self):
        self.kwargs = None

    def execute_training(self, **kwargs):
        self.kwargs = kwargs
        return {"status": "success"}


def test_wrapper_forwards_resolved_ordering():
    from agent.skills.training_skill.wrapper import run_skill

    sandbox = _RecordingSandbox()
    run_skill(
        sandbox,
        exp_id="e1",
        run_name="r",
        model_type="wavenet",
        model_config={},
        train_config={},
        loss_config={},
        order_strategy="sequential",
        file_order=PERMUTATION,
    )
    assert sandbox.kwargs["order_strategy"] == "sequential"
    assert sandbox.kwargs["file_order"] == PERMUTATION


def test_wrapper_defaults_to_shuffle_when_ordering_is_absent():
    from agent.skills.training_skill.wrapper import run_skill

    sandbox = _RecordingSandbox()
    run_skill(
        sandbox,
        exp_id="e1",
        run_name="r",
        model_type="wavenet",
        model_config={},
        train_config={},
        loss_config={},
    )
    assert sandbox.kwargs["order_strategy"] == "shuffle"
    assert sandbox.kwargs["file_order"] is None


# ---- pseudo-mode parity ----


def test_stub_accepts_the_same_ordering_signature(tmp_path):
    """Pseudo mode must not drift from production at the call boundary."""
    stub = StubSandbox(
        run_name="r", workspace=str(tmp_path), file_index=6, run_id="ordering-parity"
    )
    result = stub.execute_training(
        exp_id="e1",
        run_name="r",
        model_type="wavenet",
        m_cfg={},
        t_cfg={},
        l_cfg={},
        sample_set=SAMPLE_SET,
        order_strategy="sequential",
        file_order=PERMUTATION,
    )
    assert result["status"] == "success"
