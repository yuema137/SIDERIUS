"""The reviewed sensitive-test manifest.

FROZEN 2026-08-24 on CP-6 evidence, after CP-8 closed and confirmed no further
environment-sensitive class existed at that time
(docs/audit/ci_parity_audit.md). Generated-analysis sandbox tests added a new,
explicit class in 2026-09: kernel namespace qualification must fail closed
when a saturated host cannot allocate the isolated process tree, while the
positive execution witness still needs one quiescent capability-qualified run.

Membership requires **semantic** sensitivity, established by reading the test.
The presence of ``time.sleep``, a polling loop or a timeout literal is NOT
sufficient and never was: a Phase-0 keyword scan flagged 107 files, and reading
them reduced that to five.

The discriminator is the DIRECTION of the assertion:

    "the event must occur WITHIN T"      host saturation can exceed T   -> sensitive
    "A happened before B", A and B on
      different schedulers               saturation can invert it       -> sensitive
    "kernel isolation is available"      host task pressure can refuse  -> sensitive
    "the event must NOT occur within T"  saturation makes it MORE true  -> bulk
    sleep only sequences, or lets a thread start                        -> bulk

The ordering row was added after a 4-vCPU reproduction turned
``test_gpu_measurement_runner.py`` RED while it passed on an unloaded 24-core
host. The original discriminator looked for a wall-clock BOUND and would never
have caught it: the assertion contains no timeout at all, only a ``<=`` between
two independently-scheduled timestamps.

``tests/unit/core/test_gpu_observer.py:233`` is the counter-example kept in mind:
it sleeps and then asserts a counter did *not* advance, so contention only helps
it pass. Quarantining it would cost parallelism and buy nothing.

A RED here under violated load assumptions is INVALID_HARNESS_EVIDENCE, not a
product regression, and the bound must never be inflated to make it pass — the
bound is the thing under test.
"""

from __future__ import annotations

from types import MappingProxyType

#: file -> why it cannot run under an uncontrolled bulk lane.
SENSITIVE_FILES: MappingProxyType[str, str] = MappingProxyType(
    {
        "tests/unit/core/test_probe_hard_timeout.py": (
            "asserts measured wall time against an upper bound — "
            "`elapsed < 10.0` (:122) and `elapsed < cap + grace + 5.0` (:144). "
            "Under saturation the hard cap it verifies can be missed."
        ),
        "tests/unit/agent/evaluate_vram_skill/test_training_alarm.py": (
            "`elapsed < 3.5`, guarding that the real wrapper's native training "
            "alarm preempts a slow probe. This timing-sensitive witness must "
            "remain isolated; its bound must not be widened for host load."
        ),
        "tests/unit/agent/evaluate_vram_skill/test_isolated_preflight.py": (
            "`elapsed < 45.0` (:120), asserting the memory bound fires well before the deadline."
        ),
        "tests/unit/core/test_gpu_measurement_runner.py": (
            "ORDERING race, not an upper bound — `test_the_watch_is_open_before_"
            "the_first_phase_begins` asserts `run.samples[0].at <= "
            "run.phases[0].started_at` (:265), i.e. that a sampler thread got a "
            "sample in before a worker finished booting. Under CPU contention "
            "the sampler is scheduled late and the ordering inverts. Found by "
            "reproducing a CI failure at a 4-vCPU budget, where it went RED "
            "while passing on an unloaded 24-core host — the CP-6 discriminator "
            "extended: a race two schedulers can lose is load-fragile even "
            "though no wall-clock BOUND appears in the assertion."
        ),
        "tests/unit/nodes/test_data_analysis_agent.py": (
            "runs positive end-to-end generated-analysis witnesses through real "
            "user/network namespaces and Bubblewrap. Under four-shard host task "
            "pressure the mandatory sandbox capability probe may correctly fail "
            "closed before execution; the same tests must run alone so PASS means "
            "the qualified isolation path executed rather than weakening refusal."
        ),
    }
)

#: Why each file is here: timing-sensitive files need a quiesced host. The
#: timing lane is deliberately explicit so the harness cannot dilute bounds.
GIT_STATE_FILES: frozenset[str] = frozenset()

TIMING_FILES: frozenset[str] = frozenset(SENSITIVE_FILES) - GIT_STATE_FILES


def sensitive_paths() -> frozenset[str]:
    """The frozen set, as the shard planner's ``sensitive`` argument."""
    return frozenset(SENSITIVE_FILES)
