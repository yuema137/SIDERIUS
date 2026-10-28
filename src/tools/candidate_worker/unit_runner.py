"""Run one graph node invocation in its own supervised process (B3-3).

Serial dispatch still runs exactly one unit at a time. The unit child shares
the worker's session and process group (a plain supervised call), so the
outer sandbox timeout and terminal signals reach it exactly as they reached
the in-process dispatch. Its environment comes from the single subprocess
environment owner without a device selector, i.e. the worker's GPUs.
"""

import subprocess
import sys
from pathlib import Path

from core.durable_io import publish_bytes_write_once
from core.runtime_control.observed_subprocess import (
    replay_process_lifecycle,
    supervise_subprocess,
)
from core.subprocess_env import subprocess_env

from .graph_evidence import read_graph_control
from .unit_child import SAFE_PATH_ADDED_ENV, SAFE_PATH_ENV
from .unit_models import (
    OUTPUT_TYPES,
    NodeInvocation,
    NodeOutput,
    NodeUnitResult,
    unit_paths,
)
from .unit_transport import decode_transport, encode_transport

UNIT_MODULE = "tools.candidate_worker.unit_child"


class NodeUnitRaised(Exception):
    """The unit's native phase raised; its traceback is already in the worker log."""


def unit_command(invocation_path: str) -> list[str]:
    return [sys.executable, "-m", UNIT_MODULE, invocation_path]


def unit_env(*, cuda_visible_devices: str | None = None) -> dict[str, str]:
    """The unit child's environment; a placement adds only its device selector."""
    env = subprocess_env(cuda_visible_devices=cuda_visible_devices)
    if SAFE_PATH_ENV not in env:
        env[SAFE_PATH_ENV] = env[SAFE_PATH_ADDED_ENV] = "1"
    return env


def spawn_unit(invocation_path: str) -> None:
    """Supervise the unit child; a nonzero exit raises `CalledProcessError`."""
    sys.stdout.flush()
    sys.stderr.flush()
    env = unit_env()
    try:
        observed = supervise_subprocess(
            unit_command(invocation_path),
            env=env,
            preexec_fn=None,
            capture_stdout=False,
            label="graph unit",
        )
    except subprocess.CalledProcessError as error:
        sys.stderr.write(error.stderr or "")
        raise
    if observed.completed is not None:  # always, without a deadline
        sys.stderr.write(observed.completed.stderr or "")


def publish_invocation(invocation: NodeInvocation) -> tuple[Path, Path]:
    """Publish the write-once invocation; return it and its result path."""
    path, result_path = unit_paths(
        invocation.initial, invocation.node_id, iteration=invocation.iteration
    )
    path.parent.mkdir(parents=True)
    publish_bytes_write_once(str(path), encode_transport(invocation))
    return path, result_path


def run_unit(invocation: NodeInvocation) -> NodeUnitResult:
    """Publish the invocation, run its child and return the verified result."""
    path, result_path = publish_invocation(invocation)
    spawn_unit(str(path))
    return collect_result(invocation, result_path)


def collect_result(invocation: NodeInvocation, result_path: Path) -> NodeUnitResult:
    """Read the unit's write-once result, replay its cleanup evidence, check identity."""
    result = decode_transport(NodeUnitResult, read_graph_control(result_path))
    # Cleanup evidence first: a later refusal must not hide an uncertain child.
    for lifecycle in result.lifecycles:
        replay_process_lifecycle(lifecycle)
    if (result.node_id, result.phase) != (invocation.node_id, invocation.unit.phase):
        raise ValueError("unit result identity disagrees with its invocation")
    return result


def unit_output(invocation: NodeInvocation) -> tuple[NodeOutput, str]:
    """The in-process phase return value, or the exception class it propagated."""
    return result_output(invocation, run_unit(invocation))


def result_output(invocation: NodeInvocation, result: NodeUnitResult) -> tuple[NodeOutput, str]:
    """Re-raise what the unit's phase raised, or decode the output it returned."""
    if result.outcome == "exited":
        raise SystemExit(result.exit_code)
    if result.outcome == "interrupted":
        raise KeyboardInterrupt
    if result.outcome == "raised":
        raise NodeUnitRaised(invocation.node_id)
    if result.output is None or result.record_path is None:
        raise ValueError("returned unit result lacks its output")
    kind = OUTPUT_TYPES[result.phase]
    return decode_transport(kind, result.output.encode()), result.record_path
