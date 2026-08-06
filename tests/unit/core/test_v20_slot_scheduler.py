"""The V20 queue must be slot-driven, not band-barriered.

V19 advanced by waves: a later band started only after BOTH chains of the
current band finished. V20 replaces that with one global FIFO capped at
two active chains. The two designs are indistinguishable for the first
two jobs and diverge only at the third — which is why the barrier is the
thing you implement by accident and discover hours into a campaign.

Every test here is deterministic: no clock, no subprocess, no GPU. The
scheduler is a pure function of (queue, running set, terminal events).
"""

from __future__ import annotations

import pytest

from core.campaign.slot_scheduler import CampaignJob, SlotScheduler, v20_campaign_jobs


@pytest.fixture
def jobs():
    return v20_campaign_jobs()


@pytest.fixture
def sched(jobs):
    return SlotScheduler(jobs, max_active=2)


class TestTheFrozenRoster:
    def test_there_are_eight_chains(self, jobs):
        assert len(jobs) == 8

    def test_the_bands_are_the_audited_roster_descending(self, jobs):
        # Hardcoded, not read back from the module: these are the bands
        # v19_queue_runner.sh defines, and a silent change to them would
        # run V20 on a different dataset decomposition than V19.
        assert [j.band for j in jobs] == [
            "15-19",
            "15-19",
            "10-14",
            "10-14",
            "4-9",
            "4-9",
            "0-3",
            "0-3",
        ]

    def test_loss_is_queued_before_arch_in_every_band(self, jobs):
        for i in range(0, 8, 2):
            assert jobs[i].chain_type == "loss"
            assert jobs[i + 1].chain_type == "arch"
            assert jobs[i].band == jobs[i + 1].band

    def test_run_names_follow_the_v19_zero_padded_convention(self, jobs):
        assert [j.run_name for j in jobs] == [
            "v20_loss_15_19",
            "v20_arch_15_19",
            "v20_loss_10_14",
            "v20_arch_10_14",
            "v20_loss_04_09",
            "v20_arch_04_09",
            "v20_loss_00_03",
            "v20_arch_00_03",
        ]

    def test_every_run_name_is_unique(self, jobs):
        names = [j.run_name for j in jobs]
        assert len(set(names)) == len(names)

    def test_the_chain_type_is_constrained(self):
        with pytest.raises(ValueError):
            CampaignJob(run_name="x", band="15-19", chain_type="architecture")


class TestTheCampaignOpens:
    def test_exactly_two_chains_start_and_they_are_band_15_19(self, sched):
        started = sched.claim_slots()
        assert [j.run_name for j in started] == ["v20_loss_15_19", "v20_arch_15_19"]

    def test_a_second_claim_without_a_release_starts_nothing(self, sched):
        sched.claim_slots()
        assert sched.claim_slots() == []
        assert len(sched.running) == 2


class TestItIsNotABandBarrier:
    """The decisive behaviour. A band barrier passes every test above."""

    def test_one_completion_starts_the_next_band_while_its_partner_runs(self, sched):
        sched.claim_slots()
        sched.release("v20_loss_15_19")
        started = sched.claim_slots()

        assert [j.run_name for j in started] == ["v20_loss_10_14"], (
            "a free slot must be filled from the FIFO immediately — waiting "
            "for arch_15_19 would be V19's band barrier"
        )
        # ...and the partner is still running, i.e. two BANDS overlap.
        assert "v20_arch_15_19" in sched.running
        assert {
            j.band
            for j in [
                CampaignJob(run_name="v20_arch_15_19", band="15-19", chain_type="arch"),
                started[0],
            ]
        } == {"15-19", "10-14"}

    def test_the_next_free_slot_takes_arch_of_that_band(self, sched):
        sched.claim_slots()
        sched.release("v20_loss_15_19")
        sched.claim_slots()
        sched.release("v20_arch_15_19")
        started = sched.claim_slots()
        assert [j.run_name for j in started] == ["v20_arch_10_14"]

    def test_the_full_order_under_strictly_sequential_completion(self, sched):
        # Always release the oldest running chain. A band barrier produces
        # the same first two and then diverges.
        order: list[str] = []
        started = sched.claim_slots()
        order += [j.run_name for j in started]
        while not sched.done:
            sched.release(sched.running[0])
            order += [j.run_name for j in sched.claim_slots()]
        assert order == [
            "v20_loss_15_19",
            "v20_arch_15_19",
            "v20_loss_10_14",
            "v20_arch_10_14",
            "v20_loss_04_09",
            "v20_arch_04_09",
            "v20_loss_00_03",
            "v20_arch_00_03",
        ]

    def test_order_survives_out_of_order_completion(self, sched):
        # Real chains do not finish in launch order. The FIFO must still
        # hand out jobs in queue order regardless of WHICH slot freed.
        sched.claim_slots()
        sched.release("v20_arch_15_19")  # the second one finishes first
        assert [j.run_name for j in sched.claim_slots()] == ["v20_loss_10_14"]
        sched.release("v20_loss_15_19")
        assert [j.run_name for j in sched.claim_slots()] == ["v20_arch_10_14"]


class TestTheConcurrencyCeiling:
    def test_never_exceeds_two_across_a_full_randomised_campaign(self, jobs):
        # Deterministic pseudo-random completion order, seeded — no clock.
        import random

        rng = random.Random(20260806)
        sched = SlotScheduler(jobs, max_active=2)
        sched.claim_slots()
        seen_max = len(sched.running)
        while not sched.done:
            assert len(sched.running) <= 2
            sched.release(rng.choice(list(sched.running)))
            sched.claim_slots()
            seen_max = max(seen_max, len(sched.running))
        assert seen_max == 2, "the campaign should actually reach the ceiling"

    def test_every_job_launches_exactly_once(self, jobs):
        sched = SlotScheduler(jobs, max_active=2)
        sched.claim_slots()
        while not sched.done:
            sched.release(sched.running[0])
            sched.claim_slots()
        launched = sched.launch_order
        assert len(launched) == 8
        assert len(set(launched)) == 8

    def test_a_ceiling_below_one_is_refused(self, jobs):
        with pytest.raises(ValueError):
            SlotScheduler(jobs, max_active=0)


class TestOnlyATerminalStateFreesASlot:
    def test_releasing_something_that_never_started_is_an_error(self, sched):
        sched.claim_slots()
        with pytest.raises(KeyError):
            sched.release("v20_loss_04_09")

    def test_a_double_release_is_an_error(self, sched):
        # Silently tolerating this frees a slot that does not exist, and a
        # ninth chain lands on a card already holding two.
        sched.claim_slots()
        sched.release("v20_loss_15_19")
        with pytest.raises(KeyError):
            sched.release("v20_loss_15_19")

    def test_a_released_job_is_never_relaunched(self, sched):
        sched.claim_slots()
        sched.release("v20_loss_15_19")
        for _ in range(3):
            sched.claim_slots()
        assert sched.launch_order.count("v20_loss_15_19") == 1
