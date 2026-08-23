"""F-12a-G2 — a COMPLETED resource probe is never discarded for being slow.

Gate-exposed during Step 12 / PR-12a's G-12a-2. Design:
``pr_12a_composed_path_closure.md`` §8.20.

The defect only this module catches
-----------------------------------
``resolve_inference_batch`` used to time each candidate and, AFTER
``probe_activation_footprint`` had already RETURNED, raise
``BatchSearchTimeout`` if the elapsed wall time exceeded
``single_candidate_seconds`` — throwing away a finished measurement.

It protected against nothing: a genuinely hung probe never reaches that line,
so it could not be the hang guard it resembled. And because the probe traces a
CPU-instantiated model, its duration moves with host CPU load — so the same
candidate passed or failed depending on how busy the machine was. That is the
exact property ``probe_budgets``' own docstring cites as proof that wall time
was never a capacity signal, recurring one level below where it was first
fixed.

Observed live: a 191.7 s completed probe on a 24-core host at load ~10 was
discarded against a 120 s budget calibrated on the same machine uncontended,
and the tuner burned attempt after attempt on it.

What is deliberately NOT changed, and is pinned here so a later "cleanup"
cannot take it: the ``batch_search_seconds`` backstop. It is evaluated BEFORE
starting another candidate, so it bounds FUTURE work instead of discarding
finished work — a different thing that remains correct.
"""

from __future__ import annotations

import torch
from torch import nn

from agent.skills.evaluate_vram_skill import batch_resolver
from agent.skills.evaluate_vram_skill.batch_resolver import (
    BatchSearchTimeout,
    resolve_inference_batch,
)
from agent.skills.evaluate_vram_skill.probe_budgets import ProbeBudgets

_T = 400
_CAP = 8 * 1024**3


class _Tiny(nn.Module):
    """Cheap real module: the probe path is exercised, not stubbed."""

    def __init__(self) -> None:
        super().__init__()
        self.emb = nn.Embedding(256, 4)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.emb(x).permute(0, 2, 1)


def _slow_probe(monkeypatch, seconds: float) -> list[float]:
    """Make every candidate probe *appear* to take ``seconds``.

    The clock is faked rather than the probe slowed, so the test is fast and
    deterministic — and it isolates the one variable that matters: elapsed
    wall time. `time.monotonic` is patched inside the resolver's namespace.
    """
    ticks = [0.0]
    calls: list[float] = []

    def fake_monotonic() -> float:
        ticks[0] += seconds
        calls.append(ticks[0])
        return ticks[0]

    monkeypatch.setattr(batch_resolver.time, "monotonic", fake_monotonic)
    return calls


class TestACompletedProbeSurvivesASlowHost:
    def test_a_slow_but_finished_candidate_still_returns_a_batch(self, monkeypatch, capsys):
        """Falsifier 1 — the headline property.

        Fails when: the post-hoc rejection is restored. Then this raises
        ``BatchSearchTimeout`` instead of returning a measured batch.
        """
        _slow_probe(monkeypatch, seconds=1000.0)  # far beyond any budget

        resolved = resolve_inference_batch(
            _Tiny(),
            _T,
            _CAP,
            candidate_batches=(2, 1),
            budgets=ProbeBudgets(single_candidate_seconds=1.0, batch_search_seconds=10_000.0),
        )
        assert resolved in (2, 1)

    def test_the_elapsed_time_is_still_reported(self, monkeypatch, capsys):
        """Falsifier 2 — the duration must not be silently swallowed.

        Accepting the measurement is right; hiding that the host was slow
        would remove the calibration signal the budget still legitimately
        owns.
        """
        _slow_probe(monkeypatch, seconds=1000.0)
        resolve_inference_batch(
            _Tiny(),
            _T,
            _CAP,
            candidate_batches=(2, 1),
            budgets=ProbeBudgets(single_candidate_seconds=1.0, batch_search_seconds=10_000.0),
        )
        out = capsys.readouterr().out
        assert "SLOW PROBE" in out
        assert "F-12a-G2" in out

    def test_host_wall_time_cannot_change_the_capacity_answer(self, monkeypatch):
        """Falsifier 4 — the property the whole finding is about.

        The SAME model, cap and candidates resolve identically whether the
        host is fast or slow. Before the fix these two calls disagreed, which
        is what made a busy machine look like a capacity failure.
        """
        budgets = ProbeBudgets(single_candidate_seconds=1.0, batch_search_seconds=10_000.0)

        _slow_probe(monkeypatch, seconds=0.001)
        fast = resolve_inference_batch(_Tiny(), _T, _CAP, candidate_batches=(2, 1), budgets=budgets)

        _slow_probe(monkeypatch, seconds=1000.0)
        slow = resolve_inference_batch(_Tiny(), _T, _CAP, candidate_batches=(2, 1), budgets=budgets)

        assert fast == slow


class TestTheLegitimateTimeoutSemanticsAreUntouched:
    def test_the_search_backstop_still_raises(self, monkeypatch):
        """Falsifier 5 — narrowness of the correction.

        ``batch_search_seconds`` is checked at the TOP of the loop, before
        another candidate is started, so it bounds future work rather than
        discarding a finished measurement. It must still fire.

        Fails when: the correction was applied too broadly and removed this
        one too.
        """
        _slow_probe(monkeypatch, seconds=1000.0)
        try:
            resolve_inference_batch(
                _Tiny(),
                _T,
                _CAP,
                candidate_batches=(64, 32, 16, 8, 4, 2, 1),
                budgets=ProbeBudgets(single_candidate_seconds=1.0, batch_search_seconds=1.0),
            )
        except BatchSearchTimeout as exc:
            assert exc.record.operation == "batch_search"
            assert exc.record.disposition == "inconclusive"
        else:  # pragma: no cover - the raise is the expected path
            raise AssertionError("the batch_search backstop no longer fires")

    def test_a_real_memory_failure_still_steps_down(self, monkeypatch):
        """Falsifier 3 — a MEASURED failure keeps its meaning.

        A candidate that cannot be probed for memory reasons is a verdict on
        that BATCH, and the descending search must continue to a smaller one.
        Only measured results may reject; that is unchanged.
        """
        seen: list[int] = []
        real = batch_resolver.probe_activation_footprint

        def flaky(*args, **kwargs):
            batch = kwargs["input_sample"].shape[0]
            seen.append(batch)
            if batch > 1:
                raise MemoryError("simulated OOM at this batch")
            return real(*args, **kwargs)

        monkeypatch.setattr(batch_resolver, "probe_activation_footprint", flaky)
        resolved = resolve_inference_batch(_Tiny(), _T, _CAP, candidate_batches=(4, 2, 1))
        assert resolved == 1
        assert seen == [4, 2, 1]


def test_the_calibration_default_is_the_recorded_host_figure():
    """The 120 -> 200 update, pinned with its reason.

    Hardcoded rather than read back from the model, so this compares against
    the recorded decision instead of against itself. 200 s is the observed
    191.7 s plus margin; the search backstop was deliberately NOT changed.
    """
    budgets = ProbeBudgets()
    assert budgets.single_candidate_seconds == 200.0
    assert budgets.batch_search_seconds == 600.0
