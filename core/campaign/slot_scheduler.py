"""The V20 campaign queue policy — slot-driven, never band-barriered.

V19 advanced by WAVES: a later wave started only after *both* chains of
the current band reached a terminal state. V20 deliberately replaces that
(operator, 2026-08-06) with one global FIFO whose only invariant is
``active <= max_active``. Chains from adjacent bands may overlap in
wall-clock time — that is the point of the change.

The band barrier is the easy thing to implement by accident, and it is
indistinguishable from the correct scheduler until a campaign has been
running for hours. So the policy lives here as a pure function of
(queue, running set, terminal events) with no clock, no subprocess and no
filesystem, and the process-management layer consumes it.

**`max_active` bounds CHAINS, not GPU training phases.** Two chains may be
alive while only one is permitted to hold the card: since M5, a valid
measurement that finds insufficient headroom refuses the phase, and that
refusal is correct. Nothing here may be widened to force two candidates
onto the GPU at once.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field


class CampaignJob(BaseModel):
    """One independent V20 chain: its own workspace, its own incumbent.

    A job is never compared with another job. Each band is a different
    data scope, and a score from one scope may not update another's
    incumbent; `loss` and `arch` are separate experiments within a band.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_name: str
    band: str
    chain_type: str = Field(pattern="^(loss|arch)$")

    @property
    def workspace_suffix(self) -> str:
        return self.run_name


class SlotScheduler:
    """Hands out launch slots; holds no opinion about how a job is run.

    Args:
        jobs: the frozen launch order. Position IS the policy — within a
            band, `loss` precedes `arch`. This is launch-order priority
            only and confers no runtime advantage once a chain is alive.
        max_active: the concurrency ceiling. Never exceeded.
    """

    def __init__(self, jobs: Iterable[CampaignJob], *, max_active: int = 2) -> None:
        if max_active < 1:
            raise ValueError(f"max_active must be >= 1, got {max_active}")
        self._pending: deque[CampaignJob] = deque(jobs)
        self._max_active = max_active
        self._running: dict[str, CampaignJob] = {}
        self._launched: list[str] = []
        self._finished: list[str] = []

    @property
    def max_active(self) -> int:
        return self._max_active

    @property
    def running(self) -> tuple[str, ...]:
        return tuple(self._running)

    @property
    def launch_order(self) -> tuple[str, ...]:
        """Every job handed out, in the order it was handed out."""
        return tuple(self._launched)

    @property
    def pending(self) -> tuple[str, ...]:
        return tuple(j.run_name for j in self._pending)

    @property
    def done(self) -> bool:
        return not self._pending and not self._running

    def claim_slots(self) -> list[CampaignJob]:
        """Fill every free slot from the FIFO head, and return what to start.

        Called once at the beginning and again after each `release`. It is
        deliberately a *list*: on the first call it hands out `max_active`
        jobs, which is how the campaign opens with both band 15-19 chains.

        A job is handed out exactly once — it moves from `pending` to
        `running` here and can never be re-queued, so a scheduler restart
        cannot double-launch a chain that is already alive.
        """
        started: list[CampaignJob] = []
        while self._pending and len(self._running) < self._max_active:
            job = self._pending.popleft()
            self._running[job.run_name] = job
            self._launched.append(job.run_name)
            started.append(job)
        return started

    def release(self, run_name: str) -> None:
        """Mark one chain terminal, freeing exactly one slot.

        Only a genuine terminal state may call this. Silence on stdout, a
        finished child process, or an idle GPU are not terminal states —
        the caller owns that distinction, and getting it wrong here would
        launch a ninth chain against a card already holding two.

        Raises:
            KeyError: `run_name` is not running. A release for something
                that never started, or a double release, is a caller bug
                that would corrupt the slot count silently.
        """
        if run_name not in self._running:
            raise KeyError(
                f"{run_name!r} is not running; a release for an unstarted or "
                f"already-released chain would free a slot that does not exist"
            )
        del self._running[run_name]
        self._finished.append(run_name)


def v20_campaign_jobs(campaign_id: str = "v20") -> tuple[CampaignJob, ...]:
    """The eight V20 chains, in frozen launch order.

    Bands are the authoritative roster the V19 queue runner defines
    (`v19_queue_runner.sh` ROSTER / `file_order_for_scope`), descending.
    Within each band `loss` is queued before `arch`.

    Band tags are zero-padded to match the V19 naming convention exactly
    (`04_09`, `00_03`), so run names remain sortable and greppable
    alongside the historical campaigns.
    """
    bands = [("15-19", "15_19"), ("10-14", "10_14"), ("4-9", "04_09"), ("0-3", "00_03")]
    return tuple(
        CampaignJob(run_name=f"{campaign_id}_{chain}_{tag}", band=band, chain_type=chain)
        for band, tag in bands
        for chain in ("loss", "arch")
    )
