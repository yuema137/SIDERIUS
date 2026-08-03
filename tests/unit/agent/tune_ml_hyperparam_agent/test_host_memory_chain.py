"""A host-memory kill, carried end to end into the tuner's decision.

The 81-test host-memory apparatus was correct at every layer and terminated
in a consumer that ignored it (#156). The repair added
`PREFLIGHT_CONSUMER_ACTIONS`, but the tests for it feed
`_raise_if_preflight_blocks` LITERAL dicts -- `{"status": "host_memory"}` --
which is the same shape of gap one level along: both sides green, the seam
untested. A rename in `preflight_adapter` would satisfy the adapter suite
and the consumer suite independently.

So this module starts from a real worker that really outgrows its RSS
allowance and is really terminated by the parent, and follows what the
supervisor produced all the way to the tuner's verdict:

    a worker allocating 64 MiB at a time, capped at 256 MiB
      -> run_isolated_preflight          MEASURED_HOST_MEMORY_EXCEEDED
      -> adapt_result                    ("host_memory", no `feasible` key)
      -> _raise_if_preflight_blocks      InconclusivePreflight(kind=...)
      -> _classify_attempt_failure       "host_memory_preflight"

Nothing here is hand-built except the worker's own allocation loop.

WHY THE LANE MATTERS. The machine ran out of HOST memory. That says
nothing about whether the candidate fits on the GPU, and the candidate
never ran. Any shrink advice derived from it is the V19 failure: the
campaign downsized to toy models because a resource event that was not
about the model was read as one.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

# The package rebinds `sys.modules` so this name IS the inner module (see
# nodes/ml_hyperparameter_tune_agent/__init__.py); the dotted submodule path
# is therefore not an attribute and cannot be imported.
import nodes.ml_hyperparameter_tune_agent as tuner
from agent.skills.evaluate_vram_skill.isolated_probe import (
    IsolatedProbeSpec,
    run_isolated_preflight,
)
from agent.skills.evaluate_vram_skill.preflight_adapter import adapt_result
from agent.skills.evaluate_vram_skill.probe_budgets import InconclusivePreflight

MIB = 1024**2

#: Allocates faster than the monitor's sampling interval so the run stays
#: short, and never exits on its own -- the parent must be what stops it.
GROWS_PAST_ITS_ALLOWANCE = """
import time
blocks = []
while True:
    blocks.append(bytearray(64 * 1024 * 1024))
    time.sleep(0.01)
"""

#: Phrasings that ADVISE shrinking the candidate. Mirrors
#: test_refusal_lane_distinctness.py: a bare word ban would trip on a
#: PROHIBITION that legitimately contains the same words.
SHRINK_ADVICE = (
    "try smaller",
    "exceeds gpu memory",
    "reduce batch_size or model size",
    "reduce model capacity",
    "model too large",
)


@pytest.fixture(scope="module")
def adapted(tmp_path_factory) -> dict:
    """Run the real chain ONCE; every test below reads the same result.

    Module-scoped because it spawns a subprocess and waits for the parent's
    memory monitor to fire -- a few seconds, not something to repeat per
    assertion.
    """
    tmp_path = tmp_path_factory.mktemp("host_memory_chain")
    script = tmp_path / "growing_worker.py"
    script.write_text(GROWS_PAST_ITS_ALLOWANCE, encoding="utf-8")

    probe = run_isolated_preflight(
        IsolatedProbeSpec(
            label="synthetic",
            model_type="fake_candidate",
            vram_budget_gb=12.0,
            result_path=str(tmp_path / "result.json"),
            worker_memory_limit_bytes=256 * MIB,
        ),
        deadline_seconds=60.0,
        command=[sys.executable, str(script)],
    )

    assert probe.outcome == "MEASURED_HOST_MEMORY_EXCEEDED", (
        "the worker did not reach the host-memory bound, so the rest of this "
        f"module would be testing the wrong chain (got {probe.outcome!r})"
    )
    return adapt_result(probe.model_dump())


class TestWhatTheAdapterHandsTheTuner:
    def test_it_arrives_as_host_memory_with_no_capacity_verdict(self, adapted):
        """`feasible` must be ABSENT, not present-and-null. A missing key
        read through `.get("feasible", True)` is exactly how #156 started
        training after a host-memory kill."""
        assert adapted["status"] == "host_memory"
        assert "feasible" not in adapted

    def test_the_host_memory_evidence_survives_the_hop(self, adapted):
        """The reason has to be legible later; "something went wrong" is not
        a fact anyone can act on or audit."""
        blob = f"{adapted.get('verdict', '')} {adapted.get('message', '')}".lower()
        assert "gib" in blob
        assert "allowance" in blob or "rss" in blob or "terminated" in blob


class TestWhatTheTunerDoesWithIt:
    def test_the_attempt_stops_instead_of_receiving_an_action(self, adapted):
        """Control must not continue past the guard. Before #156 it did --
        `_raise_if_preflight_blocks`'s predecessor returned nothing and the
        attempt walked on to launch training."""
        with pytest.raises(InconclusivePreflight):
            tuner._raise_if_preflight_blocks(adapted)

    def test_it_is_recorded_as_host_memory_and_not_as_a_timeout(self, adapted):
        """Three outcomes block identically and mean different things. A
        host-memory kill filed as a measurement timeout is how a machine
        problem becomes a conclusion about the model."""
        with pytest.raises(InconclusivePreflight) as exc:
            tuner._raise_if_preflight_blocks(adapted)
        assert exc.value.kind == "host_memory"
        assert tuner._classify_attempt_failure(exc.value, None) == "host_memory_preflight"

    def test_it_carries_no_shrink_advice_and_no_candidate_blame(self, adapted):
        """The lane rule. Nothing was measured about the candidate, and the
        candidate never ran, so nothing may be said about its size."""
        with pytest.raises(InconclusivePreflight) as exc:
            tuner._raise_if_preflight_blocks(adapted)

        blob = f"{exc.value} {exc.value.record}".lower()
        for advice in SHRINK_ADVICE:
            assert advice not in blob, f"host-memory refusal leaked shrink advice: {advice!r}"

    def test_the_adapter_output_itself_suggests_nothing(self, adapted):
        """The suppression has to hold at the adapter too -- a suggestion
        forwarded here would reach the planner by another route."""
        suggestion = str(adapted.get("suggestion", "")).lower()
        for advice in SHRINK_ADVICE:
            assert advice not in suggestion


class TestHowTheAttemptIsAccounted:
    """Budget behaviour, read off the record the tuner's loop actually
    builds for a raised exception.

    Asserted through the AST rather than by running a full agent: the
    `attempt_failure` literal is constructed inline inside `run()`'s
    `except`, which cannot be called in isolation. Reading the literal is
    honest about what is being checked -- that the ONE place these records
    are built sets both flags -- without pretending an end-to-end run
    happened.
    """

    @staticmethod
    def _attempt_failure_record_flags() -> dict[str, object]:
        tree = ast.parse(Path(tuner.__file__).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = {
                k.value: v
                for k, v in zip(node.keys, node.values, strict=True)
                if isinstance(k, ast.Constant)
            }
            if keys.get("record_type") is None:
                continue
            record_type = keys["record_type"]
            if isinstance(record_type, ast.Constant) and record_type.value == "attempt_failure":
                return {
                    name: value.value
                    for name, value in keys.items()
                    if isinstance(value, ast.Constant)
                }
        raise AssertionError("no attempt_failure record literal found in the tuner")

    def test_a_blocked_preflight_consumes_an_attempt(self):
        """Otherwise a machine that stays busy could refuse forever inside
        one round without ever exhausting the budget."""
        assert self._attempt_failure_record_flags()["counts_toward_attempt_budget"] is True

    def test_it_does_not_complete_a_scientific_round(self):
        """Nothing was measured, so nothing was learned. Counting it would
        spend the experiment budget on an environment problem."""
        assert self._attempt_failure_record_flags()["counts_toward_completed_rounds"] is False
