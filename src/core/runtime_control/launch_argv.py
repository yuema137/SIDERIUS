"""The runtime-control transport a launch carries — C12-P B6.

WHY THIS MODULE EXISTS. ``core/sandbox_executor.py`` is a launch CONSUMER and
is held to a file budget for exactly that reason (R-11-11, pinned by
``tests/unit/guardrails/test_step11_c0_defect_baselines.py``). At the time B6
landed that file sat 4 lines under its ceiling, so the rule's prescribed
remedy applied literally: *extract the responsibility into a sibling module
instead of growing the launch consumer.* PR-12d's seam C had already done the
same thing one contract over, relocating the scope ABI into
``execute_tools/scope_artifact.py``.

The responsibility here is narrow and stated once: **given a launch that has a
scope to run from, what runtime-control flags does its child receive, and what
sidecar state must be cleared first.** Both executor methods emitted this
inline and nearly identically -- the only real difference being that training
DROPS a stale observation sidecar while inference RESUMES the one training
wrote -- so the duplication was itself an invitation to let the two legs drift.

This module deliberately does NOT own the question *whether* a launch is armed.
That is ``scope_artifact.has_scope_to_launch_from``, which answers it for both
the arming decision and the scope transport, so the two cannot disagree.
"""

from __future__ import annotations

import json
import os
from typing import Any


def has_scope_to_launch_from(sample_set: dict | None, task_scopes: object) -> bool:
    """Does this launch carry ANY scope to run from — C12-P B6.

    The PARENT-SIDE TWIN of ``train_engine_sandbox._has_scope_to_train_from``,
    which PR-12d (F-12d-27) introduced one process boundary down for exactly
    this reason. Both executor methods used ``sample_set is not None`` as an
    APPLICABILITY predicate, which asks *"did a legacy TIDMAD SampleSet
    arrive?"* when the question that needed answering is *"do I have a scope to
    run from at all?"*.

    A composed contrast run has no SampleSet **by construction** -- the tuner
    builds one only when the profile ``declares_physical_geometry``, which is
    false for Pets and DAVIS -- so everything nested under that predicate was
    silently not emitted. That included the whole of runtime control: no
    observation sidecar, therefore no runtime session; no runtime policy,
    therefore no in-subprocess admission decision; and, because the deadline
    branch ANDed on the same term, ``--runtime_watchdog`` was a COMPLETE no-op
    for both phases of every composed run.

    A LEGACY single-file launch has neither, and must stay unarmed: the child's
    own dispatch sends it to the legacy branch, which supports no runtime
    session. That is why this is a two-term ``or`` and not a blanket removal --
    an un-composed argv is unchanged in both directions.

    DECLARED HERE rather than in the launch consumer, for the reason R-11-11
    gives and PR-12d's seam C already acted on: ``core/sandbox_executor.py``
    stays a launch CONSUMER, and its file budget fires on exactly this kind of
    growth -- it had FOUR lines of headroom when this landed.

    ``task_scopes.training`` is the same term
    ``execute_tools.scope_artifact.task_scope_argv`` reads to decide whether to
    transport a scope at all. That agreement is load-bearing: a launch that is
    ARMED but carries no scope, or carries one while unarmed, would be a child
    told to measure something it was never given. Change one and you must
    change the other.
    """
    return sample_set is not None or getattr(task_scopes, "training", None) is not None


def runtime_control_argv(
    *,
    configs_dir: str,
    exp_id: str,
    observation_out: str,
    policy: Any | None,
    drop_stale_observation: bool,
) -> list[str]:
    """Flags telling a child to run under runtime control.

    Args:
        configs_dir: Where the run's per-attempt config JSON lives.
        exp_id: The attempt id, which namespaces the policy artifact.
        observation_out: Absolute path of the attempt's observation sidecar.
        policy: A validated ``RuntimeControlPolicy``, or ``None`` when the run
            declares none. ``None`` emits no policy flag rather than an empty
            one: "flag present but meaningless" fails closed in the child and
            must not be produced by an absent declaration.
        drop_stale_observation: RT2-B, the TRAINING leg. Remove any sidecar
            left by a previous attempt with this ``exp_id`` so that a crash
            before launch cannot resurface old evidence as current. The
            INFERENCE leg passes ``False`` -- RT2-D resumes the observation the
            training subprocess wrote, and deleting it there would discard the
            training components of the very record being assembled.

    Returns:
        The flags to extend the child's argv with. Never empty: a caller that
        has decided not to arm this launch must not call this at all, so that
        an un-composed, un-armed argv stays byte-identical to its pre-B6 form.
    """
    if drop_stale_observation and os.path.isfile(observation_out):
        os.remove(observation_out)
    argv = ["--runtime_observation_out", observation_out]
    if policy is not None:
        policy_path = os.path.abspath(os.path.join(configs_dir, f"runtime_policy_{exp_id}.json"))
        with open(policy_path, "w") as handle:
            json.dump(policy.model_dump(), handle)
        argv += ["--runtime_policy_json", policy_path]
    return argv
