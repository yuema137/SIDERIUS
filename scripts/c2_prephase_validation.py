"""V20 PR C2 Gate 2 Lite harness. VALIDATION ONLY — never a second implementation.

Drives the **real** isolated worker, the **real** process-tree sampler, the
**real** classifier, the **real** PR B admission gate and the **real** O-7
boundary. Nothing here stubs, mocks or reimplements any of them: a
validation that replaces the thing it is validating proves only that the
replacement works (`bg_admission_validation.py`'s words, and the reason PR B
needed its own harness).

WHY IT EXISTS. Static validation before the gate found no runnable entry
point for the complete pre-phase boundary:

* `python -m core.runtime_control.gpu_measurement_worker_main` runs the
  worker ALONE — no parent sampling, so no driver-visible peak and no
  coverage, which is the allocator half only and never the authority;
* `run_prephase_measurement` + `decide_prephase_admission` are library
  functions whose only production caller is the tuner;
* `scripts/run_comparison.py` exposes no CLI for the ceiling, the deadline
  or the sampling interval that cases 2, 4 and 11 need.

So the gate had no commands. This is that entry point, and it is
deliberately **thin**:

```text
validated CLI inputs
  -> production spec construction (the same models the tuner builds)
  -> run_prephase_measurement      (production worker + sampler)
  -> decide_prephase_admission     (production classifier + PR B + O-7)
  -> attach_measured_requirements  (production delivery)
  -> artifact manifest
```

WHAT IT MUST NEVER DO, and what a test proves it does not: implement a
second worker, sampler, classifier or admission policy; manufacture a
`MeasuredGpuRequirement` or a `measured_requirements` entry by hand; bypass
the production boundary; rewrite a typed outcome; subtract probe overhead;
turn synthetic fault injection into capacity authority; or make an LLM call.

REGISTRY SAFETY. C2 writes to no calibration registry at all — there is not
one reference to `CalibrationRegistry`, `runtime_calibration` or
`SIDERIUS_CALIBRATION_DIR` in any C2 module. The harness additionally
redirects `SIDERIUS_CALIBRATION_DIR` at a temporary root and records the
live tree's state before and after, so "unchanged" is evidence rather than
an argument.

HOW A FORMAL ARM ENDS (D-C2-20). Not after a step count, a duration or a
percentage — those describe one card. The parent watches the driver-visible
cumulative peak and stops the arm when it has provably settled ON THIS
MACHINE:

```text
--formal_stable_steps 500     completed steps the peak must hold
--formal_min_samples 3        readings required after the last increase
--formal_max_steps 5000       SAFETY backstop -> INCONCLUSIVE, never a pass
--formal_max_phase_seconds N  SAFETY backstop -> INCONCLUSIVE, never a pass
--formal_poll_seconds 0.5     how often the parent evaluates
```

The first two are counts of REAL WORK and therefore portable: a faster card
reaches them sooner. The backstops are not portable and each Gate sets its
own. The channel itself — where events are written, where the signal
appears, which run and candidate they belong to — is derived per arm and
handed to the trainer through `SIDERIUS_C2_FORMAL_STABILITY`, never through
a flag, and is restored immediately after the training call so one arm's
channel cannot follow the next.

DATA SELECTION, two legal forms. Either `--formal_train_portion` /
`--formal_eval_portion` (a slice), or `--formal_train_files` +
`--formal_train_psd_per_file` / `--formal_eval_files` +
`--formal_eval_psd_per_file` (explicit integers). A bound must name BOTH of
its numbers; half a bound is refused rather than silently completed from a
portion. Under live stability the training selection is a CEILING on
available work — if an arm ends because it exhausted its data before the
peak settled, `stability.succeeded` is false and the arm is INCONCLUSIVE.

EXTERNAL ACTIVITY (D-C2-19, D-C2-21). An idle GPU is NOT required for any
case, and neither is a still one. A neighbour's presence is context, and so
is its oscillation; both are recorded as headroom evidence.

Two facts are kept apart, because conflating them refused all three of
attempt 20's Case 12 pairs while every arm measured an identical 1476 MiB:

```text
environment_shift_observed   descriptive -- did the surroundings move?
pair_comparable              the verdict -- could that have changed the claim?
```

Each arm is summarized from ITS OWN series (`summarize_formal_arm` ->
`ArmEnvironment`) and the two are then compared. The arms' samples are never
pooled: one min/max across both cannot tell a wobble inside an arm -- which
affects both alike -- from a shift between them, which is the only thing
that breaks a paired comparison.

Refusal is effect-based, with no MiB tolerance anywhere. A pair is
invalidated only when external activity could have changed attribution,
sampling completeness, OOM or timeout causality, current capacity, the
candidate peak, or the admission verdict -- and then only that pair reruns
under a new immutable sub-attempt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import threading
import time
import uuid as _uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.runtime_control.environment_stability import (  # noqa: E402
    assess_pair_comparability,
)
from core.runtime_control.formal_stability import (  # noqa: E402
    DEFAULT_MAX_COMPLETED_STEPS,
    DEFAULT_MIN_SAMPLES_AFTER_LAST_PEAK,
    DEFAULT_STABLE_STEPS_AFTER_LAST_PEAK,
    STABILITY_ENV_VAR,
    FormalStabilityChannel,
)
from core.runtime_control.formal_stability_controller import (  # noqa: E402
    FormalStabilityController,
    FormalStabilityWatcher,
)

#: Cases this harness executes on a real GPU. 13-15 are deliberately absent:
#: O-7 accounting is proved deterministically at the exact head, and burning
#: a GPU run to restate it would add no distinct evidence. 16 is proved by a
#: successful case's artifact plus the exact-head ordering tests.
REAL_CASES: dict[str, str] = {
    "c1": "successful measurement (training)",
    "c2": "measured peak above the configured cap",
    "c3": "telemetry unavailable — driver query cannot be taken",
    "c4": "hard timeout — deadline below the measured setup time",
    "c5": "measured CUDA OOM",
    "c6": "worker crash / infrastructure failure",
    "c7": "phase separation — inference measured independently",
    "c8": "parent and child both resident in the candidate tree",
    "c9": "ours/other split with an unrelated CUDA process present",
    "c10": "allocator vs driver-visible, from a completed measurement",
    "c11": "sampling completeness — interval wider than the phase",
    "c12a": "perturbation: does a preceding probe change a formal execution",
    "c12b": "representativeness: probe peak vs formal-execution peak",
    "c12char": "characterization: one production-order arm, peak vs elapsed time",
    "c12inf": "repeatability: formal inference alone, reusing a trained model",
}

#: Single-arm characterization: probe -> formal training -> formal inference,
#: with the memory series retained. NOT a Gate case and never a Gate pass.
#:
#: It exists because attempt 5's artifacts contain no formal peak at all, so
#: the peak-saturation question -- when does the formal training peak appear,
#: and does anything later exceed it -- cannot be answered from anything
#: preserved. Running the no-probe arm as well would double the cost and add
#: no distinct evidence to THAT question; it belongs to the Case 12
#: perturbation comparison.
SINGLE_ARM_CASES: frozenset[str] = frozenset({"c12char"})

#: Formal INFERENCE alone, reusing an already-trained model. Repeatability
#: characterization only, never a Gate case.
#:
#: It exists so the probe-versus-formal inference comparison can be repeated
#: in minutes instead of re-running 870 s of training that the 5.88 s
#: saturation result already showed contributes nothing after the first few
#: seconds.
INFERENCE_ONLY_CASES: frozenset[str] = frozenset({"c12inf"})

#: Cases requiring a bounded PRODUCTION formal execution as the comparison
#: arm. Approved as harness-only control paths (operator, 2026-08-03): they
#: call `TidmadSandbox.execute_training` -- the same boundary
#: `agent.skills.training_skill.wrapper.run_skill` calls -- and nothing about
#: the ordinary production path changes.
FORMAL_COMPARISON_CASES: frozenset[str] = frozenset({"c12a", "c12b"})

#: Cases this harness deliberately REFUSES to run, and why.
#:
#: c12a and c12b both need a *bounded formal execution* to compare the probe
#: against -- 12a needs one with and one without a preceding probe, 12b needs
#: one to compare peaks with. Two things are missing and neither may be
#: invented here:
#:
#:   1. the bounded formal parameters (portion, steps, epochs) that define
#:      what "a bounded formal execution" is for this gate. Choosing them
#:      would decide the answer: a shorter formal run peaks lower and would
#:      make the probe look representative by construction.
#:   2. an execution path that runs a formal phase WITHOUT a preceding
#:      probe. There is deliberately no production flag for that (the
#:      operator ruled out an off-by-default switch), so the "without" arm
#:      has to be a harness-only mode driving the production training skill
#:      directly -- which is a design choice, not an implementation detail.
#:
#: Refusing loudly is the point. Running a plain measurement under these
#: labels would report a perturbation case that measured no perturbation.
BLOCKED_CASES: dict[str, str] = {}

#: Cases whose evidence comes from the exact head rather than a GPU run.
#: Named here so the matrix cannot silently omit them.
TEST_EVIDENCE_CASES: dict[str, str] = {
    "c13": "tests/unit/agent/tune_ml_hyperparam_agent/test_prephase_measurement_reachability.py"
    "::TestTheDispositionDrivesTheAttempt::test_each_stop_is_filed_under_its_lane",
    "c14": "tests/unit/core/test_prephase_admission.py"
    "::TestOSevenHoldsForEveryStop::test_the_frozen_accounting",
    "c15": "tests/unit/core/test_prephase_admission.py"
    "::TestOSevenHoldsForEveryStop::test_a_measured_oom_records_insufficiency_without_issuing_advice",
    "c16": "tests/unit/agent/tune_ml_hyperparam_agent/test_prephase_measurement_reachability.py"
    "::TestTheCallSiteExists::test_it_runs_before_training_starts",
}

#: Cases that reach their outcome through controlled injection rather than a
#: genuine device condition. They are labelled in the manifest and can never
#: establish capacity authority -- which the authority contract enforces
#: independently, since none of them yields COMPLETED_MEASUREMENT.
SYNTHETIC_CASES: frozenset[str] = frozenset({"c3", "c6"})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Every Gate-relevant value is an explicit input.

    No dataset path, device UUID or ceiling is defaulted in code: those
    belong in the approved Gate packet, where an operator can read them,
    and a code default would let a gate run against something other than
    what was approved.
    """
    p = argparse.ArgumentParser(description="V20 PR C2 Gate 2 Lite validation harness")
    p.add_argument("--case", required=True, choices=sorted(REAL_CASES))
    p.add_argument("--device_uuid", required=True, help="the card this gate is approved for")
    p.add_argument("--model_type", required=True)
    p.add_argument("--model_config", required=True, help="JSON object or a path to one")
    p.add_argument("--train_config", required=True, help="JSON object or a path to one")
    p.add_argument("--loss_config", required=True, help="JSON object or a path to one")
    p.add_argument("--data_dir", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--artifact_dir", required=True)
    p.add_argument("--ceiling_gib", type=float, required=True)
    p.add_argument("--deadline_seconds", type=float, required=True)
    p.add_argument("--sampling_interval_seconds", type=float, required=True)
    p.add_argument("--training_steps", type=int, required=True)
    p.add_argument("--inference_batches", type=int, required=True)
    p.add_argument(
        "--phase",
        default="training",
        choices=["training", "inference"],
        help="the phase measured; c7 runs inference",
    )
    # --- c12 formal-comparison arm only -------------------------------
    # Required for c12a/c12b and unused otherwise. NOT defaulted: choosing
    # them would decide the answer, because a shorter formal run peaks
    # lower and would make the probe look representative by construction.
    p.add_argument(
        "--formal_train_portion",
        type=float,
        default=None,
        help="data slice for the formal TRAINING sample set",
    )
    p.add_argument(
        "--formal_eval_portion",
        type=float,
        default=None,
        help="data slice for the formal INFERENCE (evaluation) sample set",
    )
    p.add_argument("--formal_seed", type=int, default=None)
    # EXPLICIT INTEGER WORKLOAD BOUNDS (validation-only, harness-only).
    #
    # A percentage cannot say how many steps will run: `--formal_train_portion
    # 0.01` produced a 863.8 s / ~107,000-step arm, and the peak had stopped
    # moving after 5.883 s. These name the workload directly, so the shortened
    # Case 12 is derived from measured per-unit cost and stated as integers
    # rather than inferred from a slice.
    #
    # Nothing here reaches production: no production CLI is added, no formal
    # default changes, and the sample sets are still built by the production
    # `build_sample_set` under a real `DataScope` -- so DataScope enforcement
    # is unchanged and the realized counts are verified, not assumed.
    p.add_argument(
        "--formal_train_files",
        type=int,
        default=None,
        help="explicit file count for the formal TRAINING sample set",
    )
    p.add_argument(
        "--formal_train_psd_per_file",
        type=int,
        default=None,
        help="explicit PSD segments per file for the formal TRAINING sample set",
    )
    p.add_argument(
        "--formal_eval_files",
        type=int,
        default=None,
        help="explicit file count for the formal INFERENCE sample set",
    )
    p.add_argument(
        "--formal_eval_psd_per_file",
        type=int,
        default=None,
        help="explicit PSD segments per file for the formal INFERENCE sample set",
    )
    # ---- Live-stability control (validation only) ----------------------
    # The formal training arm stops when the driver-visible peak has
    # demonstrably settled ON THIS MACHINE. These flags do not define the
    # workload and they are not acceptance criteria: the first two are the
    # stability margin, the last two are SAFETY BACKSTOPS whose only outcome
    # is INCONCLUSIVE. Each Gate sets its own caps for the card it runs on;
    # nothing here travels between machines.
    #
    # The CHANNEL itself -- where events are written, where the signal
    # appears, which run and candidate they belong to -- is deliberately NOT
    # configurable. It is derived from the arm and handed to the trainer
    # through the environment, so it cannot be half-configured.
    p.add_argument(
        "--formal_stable_steps",
        type=int,
        default=DEFAULT_STABLE_STEPS_AFTER_LAST_PEAK,
        help="completed optimizer steps the peak must hold after its last increase",
    )
    p.add_argument(
        "--formal_min_samples",
        type=int,
        default=DEFAULT_MIN_SAMPLES_AFTER_LAST_PEAK,
        help="driver readings required after the last peak increase",
    )
    p.add_argument(
        "--formal_max_steps",
        type=int,
        default=DEFAULT_MAX_COMPLETED_STEPS,
        help="SAFETY backstop: completed steps after which the arm is INCONCLUSIVE",
    )
    p.add_argument(
        "--formal_max_phase_seconds",
        type=float,
        default=None,
        help="SAFETY backstop: wall-clock cap per formal training phase, never a pass",
    )
    p.add_argument(
        "--formal_poll_seconds",
        type=float,
        default=0.5,
        help="how often the parent evaluates stability while training blocks",
    )
    # c12inf only: the workspace whose cached_models/ already holds a
    # trained checkpoint, so inference can be repeated without retraining.
    p.add_argument("--reuse_workspace", default=None)
    p.add_argument("--reuse_run_name", default=None)
    p.add_argument("--reuse_exp_id", default=None)
    p.add_argument(
        "--gate_attempt",
        type=int,
        required=True,
        help="Gate attempt number; part of the immutable artifact identity",
    )
    p.add_argument(
        "--prior_cases_wall_seconds",
        type=float,
        default=0.0,
        help="measured wall time of cases 1-11, for the Case 12 projection",
    )
    p.add_argument(
        "--max_total_wall_seconds",
        type=float,
        default=5400.0,
        help="Lite-A wall budget; Case 12 stops after pair 1 if projected past it",
    )
    p.add_argument(
        "--injection_shim",
        default=None,
        help="path to a synthetic-injection shim, recorded and hashed as provenance",
    )
    p.add_argument(
        "--dry_run",
        action="store_true",
        help=(
            "validate parsing, paths, candidate registration, device visibility "
            "and artifact writability, then exit. Launches no worker and is "
            "NEVER Gate evidence — the recorded commands run without it."
        ),
    )
    args = p.parse_args(argv)
    if args.case in FORMAL_COMPARISON_CASES | SINGLE_ARM_CASES | INFERENCE_ONLY_CASES:
        # A formal arm's data selection must be stated, never defaulted: a
        # shorter formal run peaks lower, so choosing it here would decide
        # the answer the case exists to measure.
        #
        # TWO legal ways to state it, and this check accepts BOTH. It
        # previously demanded the portions unconditionally, which made the
        # explicit-integer bound added alongside them unusable -- the
        # committed Lite-A packet's own c12 command would have been rejected
        # by argparse before any GPU work. `resolve_formal_sample_set`
        # enforces that a bound names BOTH its file count and its per-file
        # segment count, so only the seed and the choice itself are checked
        # here.
        def _stated(portion: str, files: str, per_file: str) -> bool:
            return getattr(args, portion) is not None or (
                getattr(args, files) is not None and getattr(args, per_file) is not None
            )

        unstated = []
        if not _stated("formal_train_portion", "formal_train_files", "formal_train_psd_per_file"):
            unstated.append(
                "the TRAINING selection (--formal_train_portion, or both "
                "--formal_train_files and --formal_train_psd_per_file)"
            )
        if not _stated("formal_eval_portion", "formal_eval_files", "formal_eval_psd_per_file"):
            unstated.append(
                "the INFERENCE selection (--formal_eval_portion, or both "
                "--formal_eval_files and --formal_eval_psd_per_file)"
            )
        if args.formal_seed is None:
            unstated.append("--formal_seed")
        if unstated:
            p.error(
                f"case {args.case} runs a bounded PRODUCTION formal execution and "
                f"requires {'; '.join(unstated)}. These are not defaulted: a "
                "shorter formal run peaks lower, so choosing them here would "
                "decide the answer the case exists to measure."
            )
    return args


def load_json_arg(raw: str) -> dict[str, Any]:
    """A JSON object, or a path to a file containing one."""
    candidate = Path(raw)
    if candidate.exists():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(raw)


def git_state() -> dict[str, Any]:
    """The exact SHA and whether the tree was clean.

    A gate run from a dirty tree is not evidence about a SHA, so the state
    is recorded rather than assumed.
    """

    def _git(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30
            ).stdout.strip()
        except Exception:
            return ""

    status = _git("status", "--porcelain")
    return {"sha": _git("rev-parse", "HEAD"), "dirty": bool(status), "status": status[:2000]}


def environment_facts(device_uuid: str) -> dict[str, Any]:
    """Hardware and toolchain, read live. Never inferred from a config."""
    facts: dict[str, Any] = {
        "hostname": platform.node(),
        "python": sys.version.split()[0],
        "requested_device_uuid": device_uuid,
    }
    try:
        import torch

        facts["torch"] = torch.__version__
        facts["cuda"] = torch.version.cuda
        facts["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            facts["gpu_name"] = props.name
            facts["gpu_total_mib"] = int(props.total_memory // (1024 * 1024))
            raw = getattr(props, "uuid", None)
            facts["observed_device_uuid"] = None if raw is None else f"GPU-{raw}"
    except Exception as exc:  # pragma: no cover - toolchain guard
        facts["torch_error"] = repr(exc)
    try:
        facts["nvidia_smi"] = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except Exception:
        facts["nvidia_smi"] = None
    return facts


def build_spec(
    args: argparse.Namespace, *, workspace: Path, request_id: str, label: str | None = None
):
    """The production spec, from the production builders.

    `build_planned_identity` and `CandidateMeasurementRequest` are the same
    objects the tuner constructs; nothing about the identity is assembled
    here by hand.
    """
    from core.runtime_control.gpu_measurement_identity import (
        build_planned_identity,
        resolve_inference_batch,
    )
    from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
    from core.runtime_control.gpu_requirement import CandidateMeasurementRequest

    model_config = load_json_arg(args.model_config)
    train_config = load_json_arg(args.train_config)
    # Resolved by the PARENT from the canonical production source, never
    # entered by an operator: it is a registered per-architecture constant.
    _inference_batch = resolve_inference_batch(args.model_type)
    return GpuMeasurementSpec(
        label=f"c2-lite-{label or args.case}",
        request=CandidateMeasurementRequest(
            model_type=args.model_type,
            planned_identity=build_planned_identity(
                model_type=args.model_type,
                model_config=model_config,
                train_config=train_config,
                inference_batch_size=_inference_batch,
            ),
            request_id=request_id,
            device_uuid=args.device_uuid,
            phase=args.phase,
            deadline_seconds=args.deadline_seconds,
            sampling_interval_seconds=args.sampling_interval_seconds,
        ),
        model_config_payload=model_config,
        train_config=train_config,
        loss_config=load_json_arg(args.loss_config),
        data_dir=args.data_dir,
        result_path=str(workspace / f"{label or args.case}_result.json"),
        journal_path=str(workspace / f"{label or args.case}_phases.ndjson"),
        sampler_ready_path=str(workspace / f"{label or args.case}_sampler_ready"),
        phase_complete_path=str(workspace / f"{label or args.case}_phase_complete"),
        worker_memory_limit_bytes=_worker_memory_limit_bytes(),
        training_steps=args.training_steps,
        inference_batches=args.inference_batches,
        inference_batch_size=_inference_batch,
    )


def _worker_memory_limit_bytes() -> int:
    from agent.skills.evaluate_vram_skill.isolated_probe import (
        default_worker_memory_limit_bytes,
    )

    return default_worker_memory_limit_bytes()


def injection_provenance(args: argparse.Namespace) -> dict[str, Any] | None:
    """How a synthetic case reached its outcome, recorded with the result.

    A synthetic result is only interpretable alongside what was injected --
    and Gate attempt 4 proved an injection can silently fail to happen at
    all, producing a perfectly ordinary measurement under a fault label.
    """
    if args.case not in SYNTHETIC_CASES:
        return None
    record: dict[str, Any] = {
        "case": args.case,
        "method": (
            "harness-injected worker command"
            if args.case == "c6"
            else "operator-supplied executable shim on PATH"
        ),
        "harness_command": injected_command(args.case),
        "shim_path": args.injection_shim,
    }
    if args.injection_shim:
        shim = Path(args.injection_shim)
        try:
            content = shim.read_bytes()
            record["shim_sha256"] = hashlib.sha256(content).hexdigest()
            record["shim_content"] = content.decode("utf-8", "replace")[:500]
            record["shim_executable"] = os.access(shim, os.X_OK)
        except OSError as exc:
            record["shim_error"] = f"{type(exc).__name__}: {exc}"
    return record


def injected_command(case: str) -> list[str] | None:
    """Controlled fault injection, through the seam that already exists.

    `run_prephase_measurement(command=...)` is the injection point its own
    docstring documents for deterministic fake workers. Using it is how c6
    reaches a crash without pretending a real candidate crashed. The
    manifest labels the case synthetic, and it cannot acquire capacity
    authority regardless: a crashed worker never yields
    `COMPLETED_MEASUREMENT`.
    """
    if case != "c6":
        return None
    return [sys.executable, "-c", "import sys; sys.exit(3)"]


def run_case(args: argparse.Namespace) -> dict[str, Any]:
    """Dispatch one case. c12 needs a formal comparison arm; the rest do not."""
    if args.case in BLOCKED_CASES:
        return {
            "case": args.case,
            "description": REAL_CASES[args.case],
            "status": "BLOCKED_PENDING_OPERATOR_INPUT",
            "gate_verdict": "INCONCLUSIVE",
            "reason": BLOCKED_CASES[args.case],
        }
    if args.case in INFERENCE_ONLY_CASES:
        return {
            "case": args.case,
            "description": REAL_CASES[args.case],
            "gate_evidence": False,
            "formal_inference_only": run_formal_inference_only(args),
        }
    if args.case in SINGLE_ARM_CASES:
        return {
            "case": args.case,
            "description": REAL_CASES[args.case],
            "gate_evidence": False,
            "characterization": run_single_arm_characterization(args),
        }
    if args.case in FORMAL_COMPARISON_CASES:
        return {
            "case": args.case,
            "description": REAL_CASES[args.case],
            "comparison": run_formal_comparison(args),
        }
    return run_case_measurement(args, label=args.case)


def run_case_measurement(args: argparse.Namespace, *, label: str) -> dict[str, Any]:
    """Execute one case through the production boundary and record it.

    The three calls below are the production path. The tuner's
    `_handle_prephase_gpu_measurement` calls exactly these, in this order,
    and a structural test asserts so.
    """
    from core.runtime_control.gpu_accounting import DeviceIdentity
    from core.runtime_control.gpu_accounting import sample as sample_device
    from core.runtime_control.gpu_measurement_runner import run_prephase_measurement
    from core.runtime_control.prephase_admission import (
        attach_measured_requirements,
        decide_prephase_admission,
    )

    workspace = Path(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    request_id = _uuid.uuid4().hex
    spec = build_spec(args, workspace=workspace, request_id=request_id, label=label)
    device = DeviceIdentity(uuid=args.device_uuid, physical_index=0)

    started = time.time()
    run = run_prephase_measurement(spec, device=device, command=injected_command(args.case))
    snapshot, sampling_error = _pre_spawn_snapshot(sample_device, device)
    outcome = decide_prephase_admission(
        run,
        snapshot=snapshot,
        mode="formal",
        vram_cap_mib=int(args.ceiling_gib * 1024),
        ceiling_gib=args.ceiling_gib,
        run_name=f"c2-lite-{args.case}",
        sampling_error=sampling_error,
    )
    delivered = attach_measured_requirements(_HarnessSandbox(), outcome)
    ended = time.time()

    return {
        "case": args.case,
        "label": label,
        "description": REAL_CASES[args.case],
        "synthetic_injection": args.case in SYNTHETIC_CASES,
        "injection_provenance": injection_provenance(args),
        "started_at": started,
        "ended_at": ended,
        "wall_seconds": round(ended - started, 3),
        "measurement": json.loads(run.model_dump_json()),
        "requirement": json.loads(outcome.requirement.model_dump_json()),
        "authoritative": outcome.requirement.authoritative,
        "authority_refusal": outcome.requirement.authority_refusal,
        "pr_b_admission": (
            json.loads(outcome.admission.model_dump_json())
            if outcome.admission is not None
            else None
        ),
        "disposition": outcome.disposition,
        "detail": outcome.detail,
        "requirement_delivered_to_pr_b": delivered,
        # O-7, serialized for EVERY case including the stops, so the
        # accounting is observed rather than assumed from the disposition.
        "o7": {
            "attempt_consumed": outcome.attempt_consumed,
            "records_completed_round": outcome.records_completed_round,
            "carries_candidate_blame": outcome.carries_candidate_blame,
            "permits_shrink_advice": outcome.permits_shrink_advice,
            "permits_same_attempt_retry": outcome.permits_same_attempt_retry,
            "may_launch_formal_phase": outcome.may_launch_formal_phase,
        },
    }


def visible_gpu_processes() -> list[dict[str, Any]]:
    """Every compute process on the card, for contamination detection.

    A pair is only evidence if nothing unrelated was on the device. This is
    recorded before and after each arm rather than assumed.
    """
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_gpu_memory,gpu_uuid",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
    except Exception as exc:
        return [{"error": f"{type(exc).__name__}: {exc}"}]
    rows: list[dict[str, Any]] = []
    for line in out.splitlines():
        parts = [c.strip() for c in line.split(",")]
        if len(parts) == 3 and parts[0].isdigit():
            rows.append({"pid": int(parts[0]), "used_mib": parts[1], "gpu_uuid": parts[2]})
    return rows


class BackgroundTreeSampler:
    """Poll the candidate tree while a BLOCKING production boundary runs.

    `execute_training` and `execute_inference` do not return until the
    subprocess is done, so the poll loop the prephase runner owns has no
    equivalent here. A thread supplies one.

    Validation-only, and deliberately thin: it drives the SAME
    `GpuTreeSampler` the production runner uses, so the ownership rule
    (ancestry from a root PID), the gap-is-not-a-zero rule and the window
    reduction are all the production ones. It adds a clock, nothing else.

    The root PID is this process: during a formal arm the training or
    inference subprocess is our descendant, so ancestry from here is
    exactly the candidate tree.
    """

    def __init__(self, device: Any, interval_seconds: float) -> None:
        from core.runtime_control.gpu_measurement_sampler import GpuTreeSampler

        self._sampler = GpuTreeSampler(os.getpid(), device, interval_seconds=interval_seconds)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._sampler.poll()
            self._stop.wait(0.02)

    def __enter__(self) -> BackgroundTreeSampler:
        self._thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._stop.set()
        self._thread.join(timeout=10.0)
        self._sampler.poll(force=True)
        self._sampler.stop()

    @property
    def samples(self) -> tuple[Any, ...]:
        """The whole timestamped series, for continuous environment
        assessment. Endpoints alone cannot see a neighbour that starts and
        exits between them."""
        return self._sampler.samples

    def window(self, started_at: float, ended_at: float) -> dict[str, Any]:
        """One phase's driver-visible account. Training and inference get
        their own; they are never combined into a cumulative peak."""
        w = self._sampler.measure_window(started_at, ended_at)
        return {
            "started_at": started_at,
            "ended_at": ended_at,
            "driver_tree_peak_mib": w.driver_tree_peak_mib,
            "driver_source": "gpu_accounting.sample(nvidia-smi):own_tree_mib",
            "samples_taken": w.coverage.samples_taken,
            "samples_missed": w.coverage.samples_missed,
            "covered_whole_phase": w.coverage.covered_whole_phase,
            "sampling_complete": w.coverage.complete,
            "max_gap_seconds": w.coverage.max_gap_seconds,
            "own_pids": list(w.own_pids),
            "max_concurrent_own_processes": w.max_concurrent_own_processes,
            "peak_sample": (json.loads(w.peak_sample.model_dump_json()) if w.peak_sample else None),
        }

    @property
    def raw_samples(self) -> list[dict[str, Any]]:
        """The full timestamped series, retained so a peak-versus-time curve
        can be reconstructed -- which is exactly what attempt 5 could not
        do."""
        return [json.loads(s.model_dump_json()) for s in self._sampler.samples]


#: Model segments per PSD segment at the paper's 40,000-sample
#: segmentation: 10,000,000 / 40,000. With `batch_size=1` this is also the
#: number of TRAINING STEPS one PSD segment contributes per epoch, which is
#: what turns a file/segment count into a step count.
_MODEL_SEGMENTS_PER_PSD = 250


def resolve_formal_sample_set(
    *,
    portion: float | None,
    files: int | None,
    psd_per_file: int | None,
    seed: int | None,
):
    """A formal sample set from either a portion or an explicit bound.

    The explicit path still goes through the production `build_sample_set`
    under a real `DataScope`, so DataScope enforcement is byte-identical to
    every other run -- only the *selection* is stated as integers instead of
    as a slice.

    **The realized counts are verified, not assumed.** `trial_portion` is a
    fraction of `segments_per_file` and rounding could yield one segment more
    or fewer than asked for; a Case 12 that silently ran a different workload
    than the one derived from the saturation evidence would invalidate the
    margin it exists to provide. A mismatch raises here, before any GPU work.
    """
    from execute_tools.dataset_config import TIDMAD, DataScope
    from execute_tools.sample_set_builder import build_sample_set

    if files is None and psd_per_file is None:
        if portion is None:
            raise ValueError("a formal sample set needs either a portion or an explicit bound")
        return build_sample_set(
            is_trial=True, trial_strategy="snapshot", trial_portion=portion, seed=seed
        )

    if files is None or psd_per_file is None:
        raise ValueError(
            "an explicit formal bound needs BOTH a file count and a per-file PSD "
            "segment count; one alone does not determine the workload"
        )
    if files < 1 or files > TIDMAD.num_files:
        raise ValueError(f"file count {files} outside 1..{TIDMAD.num_files}")
    if psd_per_file < 1 or psd_per_file > TIDMAD.segments_per_file:
        raise ValueError(
            f"PSD segments per file {psd_per_file} outside 1..{TIDMAD.segments_per_file}"
        )

    sample_set = build_sample_set(
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=psd_per_file / TIDMAD.segments_per_file,
        seed=seed,
        scope=DataScope(file_indices=list(range(files))),
    )
    realized_files = len(sample_set)
    realized_per_file = {len(v) for v in sample_set.values()}
    if realized_files != files or realized_per_file != {psd_per_file}:
        raise ValueError(
            f"the explicit bound was not realized: asked for {files} files x "
            f"{psd_per_file} PSD segments, built {realized_files} files x "
            f"{sorted(realized_per_file)}"
        )
    return sample_set


def describe_workload_bound(args: argparse.Namespace) -> dict[str, Any]:
    """The integer workload this run will execute, for the artifact.

    Recorded so an acceptance reader can check the executed workload against
    the saturation evidence it was derived from, without re-deriving it.
    """
    if args.formal_train_files is None or args.formal_train_psd_per_file is None:
        return {"bounded": False, "source": "portion"}
    steps = args.formal_train_files * args.formal_train_psd_per_file * _MODEL_SEGMENTS_PER_PSD
    batches = None
    if args.formal_eval_files is not None and args.formal_eval_psd_per_file is not None:
        segments = args.formal_eval_files * args.formal_eval_psd_per_file * _MODEL_SEGMENTS_PER_PSD
        from core.inference_defaults import inference_batch_for

        batches = math.ceil(segments / max(1, inference_batch_for(args.model_type)))
    return {
        "bounded": True,
        "source": "explicit_integer_bound",
        "train_files": args.formal_train_files,
        "train_psd_per_file": args.formal_train_psd_per_file,
        "training_steps_per_epoch": steps,
        "eval_files": args.formal_eval_files,
        "eval_psd_per_file": args.formal_eval_psd_per_file,
        "inference_batches": batches,
        "model_segments_per_psd": _MODEL_SEGMENTS_PER_PSD,
        # The measured per-unit costs the bound was derived from (c12char at
        # d48c7b34). Carried so the projection is auditable, never used to
        # scale or correct a measured peak.
        "derived_from": {
            "training_ms_per_step": 8.076210448052734,
            "training_peak_saturated_s": 5.883,
            "inference_s_per_file_2psd": 0.705,
            "inference_peak_saturated_s": 1.342,
        },
    }


def run_formal_execution(args: argparse.Namespace, *, label: str) -> dict[str, Any]:
    """One bounded run of the PRODUCTION formal-execution boundary.

    Calls `TidmadSandbox.execute_training`, which is exactly what
    `agent.skills.training_skill.wrapper.run_skill` calls -- the boundary PR
    B's admission gate protects and the tuner launches. The harness supplies
    inputs; it runs none of the training itself.

    The driver-visible peak comes from the production `GpuPhaseObserver`
    carried on the returned status, not from a second sampler. Reading it
    from anywhere else would compare a probe against a measurement taken by
    different instruments.
    """
    from core.sandbox_executor import TidmadSandbox

    workspace = Path(args.workspace) / f"formal_{label}"
    workspace.mkdir(parents=True, exist_ok=True)
    run_name = f"c2-lite-{args.case}-{label}"
    exp_id = f"c2lite_{args.case}_{label}"
    sandbox = TidmadSandbox(
        run_name=run_name,
        workspace=str(workspace),
        progress_bar=False,
        device_identity=_device_identity(args.device_uuid),
    )
    model_cfg = load_json_arg(args.model_config)
    loss_cfg = load_json_arg(args.loss_config)

    # Two sample sets, exactly as production carries `sample_set` and
    # `eval_sample_set`. The portions are the operator's slices; the
    # per-epoch `train_portion` is 1.0 so the slice is not reduced twice --
    # a hidden second reduction would make the formal run smaller than the
    # approved 1% and quietly favour the probe.
    train_set = resolve_formal_sample_set(
        portion=args.formal_train_portion,
        files=args.formal_train_files,
        psd_per_file=args.formal_train_psd_per_file,
        seed=args.formal_seed,
    )
    eval_set = resolve_formal_sample_set(
        portion=args.formal_eval_portion,
        files=args.formal_eval_files,
        psd_per_file=args.formal_eval_psd_per_file,
        seed=args.formal_seed,
    )

    device = _device_identity(args.device_uuid)

    # The live-stability channel for THIS arm. `run_id` and `candidate_id`
    # are both arm-specific: Case 12 runs six formal arms under one Gate, and
    # an arm that counted a sibling's steps would reach the stability
    # threshold without having executed it.
    channel = FormalStabilityChannel(
        events_path=str(workspace / "stability_events.ndjson"),
        stop_path=str(workspace / "stability_stop"),
        run_id=f"{args.case}-{label}",
        candidate_id=exp_id,
        stable_steps_after_last_peak=args.formal_stable_steps,
        min_samples_after_last_peak=args.formal_min_samples,
        max_completed_steps=args.formal_max_steps,
        max_phase_seconds=args.formal_max_phase_seconds,
    )

    started = time.time()
    with BackgroundTreeSampler(device, args.sampling_interval_seconds) as watcher:
        # The controller reads the SAME series the window measurement reduces.
        # A second sampler would give the stop rule and the reported peak two
        # different views of one phase.
        controller = FormalStabilityController(channel, samples=lambda: watcher.samples)
        training_started = time.time()
        # `_subprocess_env` copies `os.environ`, so setting it here is what
        # reaches the training subprocess. Scoped to the training call and
        # restored immediately: the inference subprocess has no use for it,
        # and a variable left set would follow every later arm.
        previous_channel = os.environ.get(STABILITY_ENV_VAR)
        os.environ[STABILITY_ENV_VAR] = channel.model_dump_json()
        try:
            # The watcher spans the BLOCKING boundary. `execute_training`
            # does not return until the subprocess is done, so polling after
            # it returns would be watching nothing.
            with FormalStabilityWatcher(controller, interval_seconds=args.formal_poll_seconds):
                training = sandbox.execute_training(
                    exp_id=exp_id,
                    run_name=run_name,
                    model_type=args.model_type,
                    m_cfg=model_cfg,
                    t_cfg=load_json_arg(args.train_config),
                    l_cfg=loss_cfg,
                    sample_set=train_set,
                    train_portion=1.0,
                    train_base_seed=args.formal_seed,
                )
        finally:
            if previous_channel is None:
                os.environ.pop(STABILITY_ENV_VAR, None)
            else:
                os.environ[STABILITY_ENV_VAR] = previous_channel
        stability = controller.completion()
        trained_at = time.time()
        # 12b compares the probe's INFERENCE peak against a formal
        # inference peak. Running only training would answer half the
        # question and look complete.
        inference_started = time.time()
        inference = sandbox.execute_inference(
            exp_id=exp_id,
            run_name=run_name,
            model_type=args.model_type,
            m_cfg=model_cfg,
            l_cfg=loss_cfg,
            sample_set=eval_set,
        )
        ended = time.time()
    training_window = watcher.window(training_started, trained_at)
    inference_window = watcher.window(inference_started, ended)
    return {
        "arm": label,
        "boundaries": [
            "TidmadSandbox.execute_training",
            "TidmadSandbox.execute_inference",
        ],
        "started_at": started,
        "ended_at": ended,
        "training_wall_seconds": round(trained_at - started, 3),
        "inference_wall_seconds": round(ended - trained_at, 3),
        "wall_seconds": round(ended - started, 3),
        "training_status": _jsonable(training),
        "inference_status": _jsonable(inference),
        # WHY the training phase ended, and whether its peak may be quoted.
        # Without this the artifact cannot distinguish a phase that stopped
        # because the peak settled from one that merely ran out of data --
        # they look identical in every other field.
        "stability": json.loads(stability.model_dump_json()),
        # Separate per phase. A cumulative peak over training + inference
        # would answer neither phase's question -- the same conflation that
        # made `probe_production.py` unusable as a producer.
        "training_memory": training_window,
        "inference_memory": inference_window,
        # The raw timestamped series, and the ONLY copy. Environment
        # assessment reads this. An earlier `environment_samples` key held
        # the same series as Pydantic objects, which the manifest writer's
        # `default=str` turned into repr strings -- recorded, but not
        # machine-readable, so a replay could not re-derive the assessment
        # from the artifact.
        "raw_samples": watcher.raw_samples,
        "gpu_processes_after": visible_gpu_processes(),
    }


def _device_identity(uuid_str: str):
    from core.runtime_control.gpu_accounting import DeviceIdentity

    return DeviceIdentity(uuid=uuid_str, physical_index=0)


def _jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return str(value)


def summarize_formal_arm(arm: str, formal: dict[str, Any], *, device_total_mib: int | None = None):
    """One formal-arm record -> one `ArmEnvironment`.

    The ONLY translation, so a replay from an immutable artifact and a live
    Gate arm reach the assessor through the same code. Two constructions of
    this mapping would drift, and a drifted replay proves nothing about the
    run it claims to reproduce.

    The peak is TRAINING's: that is the phase the stability rule governs and
    the quantity Case 12 compares. Inference is carried separately and is
    identical across arms by its own measurement.
    """
    from core.runtime_control.environment_stability import summarize_arm

    train = formal.get("training_memory") or {}
    infer = formal.get("inference_memory") or {}
    status = formal.get("training_status") or {}
    verification = status.get("runtime_verification") or {}
    admission = (verification.get("admission") or {}).get("decision")

    # THE REALIZED identity, from inside each arm's own training subprocess:
    # `calibration_context` is built from the model that was actually
    # constructed (family, parameter count, precision, optimizer, batch,
    # segment size). Two arms that ran different candidates differ here.
    #
    # It is deliberately NOT rebuilt from `args`: those are identical for
    # both arms by construction, so a check against them could never fail
    # and would be decoration. An earlier version of this adapter read
    # `formal["realized_identity"]` and `stability["candidate_id"]` --
    # NEITHER of which exists on a formal-arm record -- so every live pair
    # was blocked for "no identity" while the replay passed on a hand-fed
    # value. That is exactly the two-constructions drift this function was
    # written to prevent, and it survived because no test built an
    # ArmEnvironment from a real formal-arm record.
    context = verification.get("calibration_context")
    identity = json.dumps(context, sort_keys=True) if context else None

    return summarize_arm(
        arm,
        formal.get("raw_samples") or [],
        candidate_peak_mib=train.get("driver_tree_peak_mib"),
        admission_result=admission,
        identity=str(identity) if identity is not None else None,
        sampling_complete=bool(train.get("sampling_complete"))
        and bool(infer.get("sampling_complete")),
        samples_missed=int(train.get("samples_missed") or 0)
        + int(infer.get("samples_missed") or 0),
        # A worker killed from outside leaves a signal on its status; the
        # parent records `term_sent` so an external kill is distinguishable
        # from one we asked for (Lite-A attempt 20, c5).
        externally_terminated=bool(status.get("externally_terminated")),
        capacity_induced_failure=bool(status.get("capacity_induced_failure")),
        device_total_mib=device_total_mib,
    )


def run_formal_comparison(args: argparse.Namespace) -> dict[str, Any]:
    """The c12 pairs, with an enforced budget checkpoint after pair 1.

    Order alternates across repetitions (A/B, B/A, A/B) so an ordering
    effect -- a warmed driver, a cached dataset page -- cannot masquerade as
    a perturbation. Each arm gets a fresh workspace and a fresh process.

    **Pair 1 decides whether pairs 2 and 3 run.** `T_formal` is unmeasured
    before the first pair, so running all three blind would spend GPU time
    with no stopping point -- exactly the approved safeguard this exists to
    honour. Stopping is a `STOPPED_BY_TIME_BOUND` status, NOT a failure, and
    nothing is shrunk to fit the budget.

    NO correction factor is computed anywhere. The repetitions establish the
    observed repeatability envelope, and the comparison is reported against
    that rather than against an invented tolerance.
    """
    orders = [
        ("with_probe", "without_probe"),
        ("without_probe", "with_probe"),
        ("with_probe", "without_probe"),
    ]
    pairs: list[dict[str, Any]] = []
    projection: dict[str, Any] | None = None
    stopped_by_bound = False

    for index, order in enumerate(orders, start=1):
        if stopped_by_bound:
            break
        before = visible_gpu_processes()
        arms: dict[str, Any] = {}
        for arm in order:
            label = f"p{index}_{arm}"
            probe = run_case_measurement(args, label=label) if arm == "with_probe" else None
            formal = run_formal_execution(args, label=label)
            arms[arm] = {"prephase": probe, "formal": formal}
        after = visible_gpu_processes()
        # Environment assessed PER ARM over each arm's own timestamped
        # series, then the two arms compared. Never pooled: one min/max
        # across both arms cannot tell a wobble INSIDE an arm -- which
        # affects both alike -- from a shift BETWEEN them, which is the only
        # thing that breaks a paired comparison. Attempt 20 refused all
        # three pairs on a pooled 150 MiB range while every arm measured an
        # identical 1476 MiB.
        #
        # Refusal is effect-based. Presence is not contamination and neither
        # is oscillation; what invalidates a pair is external activity that
        # could have changed the peak, the admission verdict, attribution,
        # sampling, or capacity causality. And then only this pair reruns.
        summaries = [summarize_formal_arm(arm, arms[arm]["formal"]) for arm in order]
        comparability = assess_pair_comparability(*summaries, case=args.case)
        pairs.append(
            {
                "pair": index,
                "order": list(order),
                "gpu_processes_before": before,
                "gpu_processes_after": after,
                "formal_phases_complete": all(
                    formal_phases_complete(a["formal"]) for a in arms.values()
                ),
                # Separate keys, deliberately: a shift may be observed while
                # the pair stays comparable, and conflating the two is the
                # defect this replaced.
                "environment_shift_observed": comparability.environment_shift_observed,
                "pair_comparable": comparability.pair_comparable,
                "environment": json.loads(comparability.model_dump_json()),
                "environment_acceptable": comparability.pair_comparable,
                "arms": arms,
            }
        )
        if index == 1:
            projection = project_case12_wall(args, pairs[0])
            stopped_by_bound = not projection["continue"]

    complete = all(pair["formal_phases_complete"] for pair in pairs)
    return {
        "pairs": pairs,
        "correction_factor_applied": False,
        "projection": projection,
        "pairs_completed": len(pairs),
        "pairs_planned": len(orders),
        "gate_status": (
            "STOPPED_BY_TIME_BOUND" if stopped_by_bound else (None if complete else "INCONCLUSIVE")
        ),
        "formal_phases_complete": complete,
        "incompleteness_reason": (
            None if complete else "a formal arm is missing its training or inference phase"
        ),
    }


def run_formal_inference_only(args: argparse.Namespace) -> dict[str, Any]:
    """Formal inference alone, against an already-trained model.

    Calls the SAME `TidmadSandbox.execute_inference` the Gate and the chain
    use; it simply does not re-run training first. `--reuse_run_name` names
    the workspace whose `cached_models/` already holds the checkpoint, so
    the 870 s training phase is not repeated to obtain an inference number
    the 5.88 s saturation curve already showed is unaffected by it.
    """
    from core.sandbox_executor import TidmadSandbox
    from execute_tools.sample_set_builder import build_sample_set

    workspace = Path(args.reuse_workspace)
    sandbox = TidmadSandbox(
        run_name=args.reuse_run_name,
        workspace=str(workspace),
        progress_bar=False,
        device_identity=_device_identity(args.device_uuid),
    )
    eval_set = build_sample_set(
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=args.formal_eval_portion,
        seed=args.formal_seed,
    )
    started = time.time()
    with BackgroundTreeSampler(
        _device_identity(args.device_uuid), args.sampling_interval_seconds
    ) as watcher:
        inference_started = time.time()
        status = sandbox.execute_inference(
            exp_id=args.reuse_exp_id,
            run_name=args.reuse_run_name,
            model_type=args.model_type,
            m_cfg=load_json_arg(args.model_config),
            l_cfg=load_json_arg(args.loss_config),
            sample_set=eval_set,
        )
        ended = time.time()
    window = watcher.window(inference_started, ended)
    return {
        "boundary": "TidmadSandbox.execute_inference",
        "wall_seconds": round(ended - started, 3),
        "status": _jsonable(status),
        "inference_memory": window,
        "raw_samples": watcher.raw_samples,
        "gpu_processes_after": visible_gpu_processes(),
    }


def run_single_arm_characterization(args: argparse.Namespace) -> dict[str, Any]:
    """One production-order arm, with the memory series kept.

    Exactly the boundaries the Gate uses -- `run_case_measurement` then
    `run_formal_execution` -- so nothing here is a second implementation.
    The only difference from a Case 12 arm is that the no-probe comparison
    arm is not run: it answers the perturbation question, not the
    saturation one, and would double the cost for no distinct evidence.
    """
    probe = run_case_measurement(args, label="char_probe")
    formal = run_formal_execution(args, label="char_formal")
    return {
        "gate_pass": False,
        "arm": "with_probe (production order)",
        "probe": probe,
        "formal": formal,
        "saturation": {
            "training": peak_saturation(
                formal["raw_samples"],
                formal["training_memory"]["started_at"],
                formal["training_memory"]["ended_at"],
            ),
            "inference": peak_saturation(
                formal["raw_samples"],
                formal["inference_memory"]["started_at"],
                formal["inference_memory"]["ended_at"],
            ),
        },
    }


def peak_saturation(
    samples: list[dict[str, Any]], started_at: float, ended_at: float
) -> dict[str, Any]:
    """When the phase's cumulative peak stopped rising.

    Reports elapsed SECONDS, not steps: the production training loop emits
    no per-step marker the sampler can key on, so a step figure here would
    be invented. Whether seconds suffice to choose a safe shorter workload
    is precisely what this run exists to establish.
    """
    in_phase = [
        s
        for s in samples
        if s.get("telemetry_available")
        and s.get("own_tree_mib") is not None
        and started_at <= s["at"] <= ended_at
    ]
    if not in_phase:
        return {"observed": False, "reason": "no valid in-phase samples"}
    duration = ended_at - started_at
    running = -1
    curve: list[dict[str, Any]] = []
    last_increase_at: float | None = None
    for s in in_phase:
        value = int(s["own_tree_mib"])
        if value > running:
            running = value
            last_increase_at = s["at"]
            curve.append(
                {"elapsed_s": round(s["at"] - started_at, 3), "cumulative_peak_mib": running}
            )
    first_final = next((c["elapsed_s"] for c in curve if c["cumulative_peak_mib"] == running), None)
    last_elapsed = round(last_increase_at - started_at, 3) if last_increase_at is not None else None
    return {
        "observed": True,
        "phase_duration_s": round(duration, 3),
        "samples_in_phase": len(in_phase),
        "final_peak_mib": running,
        "first_time_final_peak_seen_s": first_final,
        "last_cumulative_increase_s": last_elapsed,
        # The whole point: how much of the run happened after the peak had
        # already stopped moving.
        "stable_tail_s": (round(duration - last_elapsed, 3) if last_elapsed is not None else None),
        "stable_tail_fraction": (
            round((duration - last_elapsed) / duration, 4)
            if last_elapsed is not None and duration > 0
            else None
        ),
        "cumulative_peak_curve": curve,
    }


def project_case12_wall(args: argparse.Namespace, pair_one: dict[str, Any]) -> dict[str, Any]:
    """Whether pairs 2 and 3 fit the budget, from pair 1's real timings.

    Deliberately conservative: `T_formal` is the SLOWER of the two pair-1
    formal arms, not their mean. An optimistic projection would authorise a
    run that then overruns, which is the failure mode the checkpoint exists
    to prevent.
    """
    formals = [arm["formal"]["wall_seconds"] for arm in pair_one["arms"].values()]
    probes = [
        arm["prephase"]["wall_seconds"] for arm in pair_one["arms"].values() if arm.get("prephase")
    ]
    t_formal = max(formals) if formals else 0.0
    t_probe = max(probes) if probes else 0.0
    projected_case12 = 6 * t_formal + 3 * t_probe
    projected_total = args.prior_cases_wall_seconds + projected_case12
    return {
        "t_formal_seconds": round(t_formal, 3),
        "t_formal_basis": "slower of the two pair-1 formal arms (conservative)",
        "t_probe_seconds": round(t_probe, 3),
        "formal_arm_wall_seconds": [round(f, 3) for f in formals],
        "formal_training_wall_seconds": [
            round(arm["formal"]["training_wall_seconds"], 3) for arm in pair_one["arms"].values()
        ],
        "formal_inference_wall_seconds": [
            round(arm["formal"]["inference_wall_seconds"], 3) for arm in pair_one["arms"].values()
        ],
        "formula": "6 x T_formal + 3 x T_probe",
        "projected_case12_wall_seconds": round(projected_case12, 1),
        "prior_cases_wall_seconds": args.prior_cases_wall_seconds,
        "projected_total_lite_a_wall_seconds": round(projected_total, 1),
        "budget_seconds": args.max_total_wall_seconds,
        "continue": projected_total <= args.max_total_wall_seconds,
        "decision": (
            "continue with pairs 2 and 3"
            if projected_total <= args.max_total_wall_seconds
            else "stop cleanly after pair 1; nothing is shrunk to fit"
        ),
    }


def formal_phases_complete(formal: dict[str, Any]) -> bool:
    """Both production phases ran AND were measured.

    A non-empty status is not sufficient, and attempt 5 proved why: pair 1
    reported complete after 886 s of GPU work that recorded **no formal
    peak at all**, so Case 12B -- which compares probe peaks against formal
    peaks -- could not have been answered by it. "It ran" and "we measured
    it" are different claims.
    """
    for status_key, memory_key in (
        ("training_status", "training_memory"),
        ("inference_status", "inference_memory"),
    ):
        if not formal.get(status_key):
            return False
        window = formal.get(memory_key)
        if not isinstance(window, dict):
            return False
        if window.get("driver_tree_peak_mib") is None:
            return False
        if not window.get("sampling_complete"):
            return False
        if window.get("started_at") is None or window.get("ended_at") is None:
            return False
    return True


def _foreign_processes(rows: list[dict[str, Any]], own: set[int]) -> list[dict[str, Any]]:
    return [r for r in rows if isinstance(r.get("pid"), int) and r["pid"] not in own]


class _HarnessSandbox:
    """Receives the delivered requirement so the delivery step is exercised.

    Deliberately inert: it holds the attribute and nothing else. Giving it
    behaviour would start it becoming a second sandbox.
    """


def _pre_spawn_snapshot(sampler, device) -> tuple[Any, str | None]:
    try:
        return sampler(os.getpid(), device), None
    except Exception as exc:  # pragma: no cover - driver-shape guard
        return None, f"{type(exc).__name__}: {exc}"


def dry_run_checks(args: argparse.Namespace) -> dict[str, Any]:
    """Everything checkable without touching the GPU.

    Explicitly NOT gate evidence: it launches no worker, so it establishes
    nothing about the candidate or the card.
    """
    checks: dict[str, Any] = {"case": args.case, "gate_evidence": False}
    checks["data_dir_present"] = Path(args.data_dir).is_dir()
    workspace, artifacts = Path(args.workspace), Path(args.artifact_dir)
    for name, path in (("workspace", workspace), ("artifact_dir", artifacts)):
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".writable"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            checks[f"{name}_writable"] = True
        except OSError as exc:
            checks[f"{name}_writable"] = f"{type(exc).__name__}: {exc}"

    try:
        checks["spec_constructs"] = bool(
            build_spec(args, workspace=workspace, request_id="dry-run")
        )
    except Exception as exc:
        checks["spec_constructs"] = f"{type(exc).__name__}: {exc}"

    from ml_models.models_format_sandbox import get_config_class
    from ml_models.models_sandbox import MODEL_REGISTRY

    checks["candidate_registered"] = args.model_type in MODEL_REGISTRY
    checks["config_class_registered"] = get_config_class(args.model_type) is not None

    facts = environment_facts(args.device_uuid)
    checks["environment"] = facts
    checks["device_uuid_matches"] = facts.get("observed_device_uuid") == args.device_uuid
    return checks


def live_registry_fingerprint() -> dict[str, Any]:
    """A hash of the live duration-calibration trees, for before/after.

    C2 references no registry at all, so this is expected to be identical
    either side. Recording it makes "unchanged" evidence rather than an
    argument -- and one env var governs BOTH evidence systems (the legacy
    v1 table and the v2 registry root), a coupling that already caught a
    C1 validation run out.
    """
    root = Path(os.environ.get("SIDERIUS_LIVE_CALIBRATION_DIR", Path.home() / ".siderius"))
    out: dict[str, Any] = {"root": str(root), "present": root.is_dir()}
    if not root.is_dir():
        return out
    digest = hashlib.sha256()
    entries: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(root))
            entries.append(rel)
            digest.update(rel.encode("utf-8"))
            try:
                digest.update(str(path.stat().st_size).encode("utf-8"))
                digest.update(path.read_bytes())
            except OSError:
                digest.update(b"<unreadable>")
    out["file_count"] = len(entries)
    out["sha256"] = digest.hexdigest()
    return out


def redirect_calibration_dir(workspace: Path) -> str:
    """Point BOTH evidence systems at a temporary root before anything runs.

    `SIDERIUS_CALIBRATION_DIR` governs the legacy v1 table AND the v2
    registry root (`$DIR/runtime_calibration_v2`); it is a base directory,
    not one tree. Redirecting it is belt-and-braces -- C2 writes to neither
    -- but a gate that assumed that and was wrong would corrupt preserved
    evidence.
    """
    temp_root = workspace / "calibration_redirect"
    temp_root.mkdir(parents=True, exist_ok=True)
    os.environ["SIDERIUS_CALIBRATION_DIR"] = str(temp_root)
    return str(temp_root)


def artifact_identity(args: argparse.Namespace, sha: str) -> str:
    """Immutable, unique, and self-describing.

    Gate attempt 4's first c3 induction was invalid -- the PATH still
    reached `/usr/bin/nvidia-smi`, so nothing was injected -- and the
    corrected rerun OVERWROTE it. The invalid artifact is unrecoverable.
    A name that encodes attempt, SHA and case cannot collide across those
    axes, and `_next_sub_attempt` handles the remaining one: the same case
    run twice at the same SHA.
    """
    return f"c2_lite_a{args.gate_attempt}_{sha[:12]}_{args.case}"


def _next_sub_attempt(artifacts: Path, base: str) -> Path:
    """The first free `__subN` path. Never replaces an existing artifact.

    Includes an invalid setup, a contaminated run, a corrected injection
    and a rerun after failure -- every one of those is evidence about what
    happened, and the record of a mistake is often the most useful part.
    """
    for index in range(1, 1000):
        candidate = artifacts / f"{base}__sub{index}.json"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"more than 999 sub-attempts for {base}; refusing to guess")


def write_manifest(args: argparse.Namespace, payload: dict[str, Any]) -> Path:
    """One immutable manifest per invocation, hashed."""
    artifacts = Path(args.artifact_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    sha = str(payload.get("git", {}).get("sha") or "nosha")
    target = _next_sub_attempt(artifacts, artifact_identity(args, sha))
    payload["artifact_path"] = str(target)
    body = json.dumps(payload, indent=1, default=str, sort_keys=True)
    target.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    target.with_suffix(".sha256").write_text(digest, encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload: dict[str, Any] = {
        "harness": "scripts/c2_prephase_validation.py",
        "gate": "V20 PR C2 — Gate 2 Lite",
        "git": git_state(),
        "command": [sys.argv[0], *(argv if argv is not None else sys.argv[1:])],
        "resolved_arguments": vars(args),
        "environment": environment_facts(args.device_uuid),
        "test_evidence_cases": TEST_EVIDENCE_CASES,
    }

    payload["calibration_redirect"] = redirect_calibration_dir(Path(args.workspace))
    payload["workload_bound"] = describe_workload_bound(args)
    payload["live_registry_before"] = live_registry_fingerprint()

    if args.dry_run:
        payload["dry_run"] = dry_run_checks(args)
        payload["live_registry_after"] = live_registry_fingerprint()
        payload["live_registry_unchanged"] = (
            payload["live_registry_before"] == payload["live_registry_after"]
        )
        payload["gate_evidence"] = False
        print(json.dumps(payload["dry_run"], indent=1, default=str))
        write_manifest(args, payload)
        return 0

    payload["gate_evidence"] = True
    payload["result"] = run_case(args)
    payload["live_registry_after"] = live_registry_fingerprint()
    payload["live_registry_unchanged"] = (
        payload["live_registry_before"] == payload["live_registry_after"]
    )
    target = write_manifest(args, payload)
    result = payload["result"]
    print(render_summary(args.case, result, target))
    return 0


def render_summary(case: str, result: dict[str, Any], target: Path) -> str:
    """One line per result SHAPE, not one line assuming a shape.

    Attempt 5 wrote its manifest and then died on `KeyError: 'requirement'`
    because this rendered a comparison result as a measurement one -- after
    30 minutes of GPU work. No evidence was lost, but a run that ends in a
    traceback is not a clean Gate execution.
    """
    if result.get("status") == "BLOCKED_PENDING_OPERATOR_INPUT":
        return f"[c2-lite] {case}: BLOCKED — {result.get('reason')} -> {target}"
    comparison = result.get("comparison")
    if comparison is not None:
        status = comparison.get("gate_status") or "COMPLETE"
        projection = comparison.get("projection") or {}
        return (
            f"[c2-lite] {case}: {status} "
            f"pairs={comparison.get('pairs_completed')}/{comparison.get('pairs_planned')} "
            f"complete={comparison.get('formal_phases_complete')} "
            f"projected_total={projection.get('projected_total_lite_a_wall_seconds')}s "
            f"budget={projection.get('budget_seconds')}s -> {target}"
        )
    only = result.get("formal_inference_only")
    if only is not None:
        w = only["inference_memory"]
        return (
            f"[c2-lite] {case}: FORMAL INFERENCE ONLY (not a Gate pass) "
            f"driver={w['driver_tree_peak_mib']} MiB samples={w['samples_taken']} "
            f"complete={w['sampling_complete']} wall={only['wall_seconds']}s -> {target}"
        )
    char = result.get("characterization")
    if char is not None:
        tr, inf = char["saturation"]["training"], char["saturation"]["inference"]
        return (
            f"[c2-lite] {case}: CHARACTERIZATION (not a Gate pass) | "
            f"training peak={tr.get('final_peak_mib')} MiB "
            f"last_rise={tr.get('last_cumulative_increase_s')}s of "
            f"{tr.get('phase_duration_s')}s (stable tail "
            f"{tr.get('stable_tail_fraction')}) | inference peak="
            f"{inf.get('final_peak_mib')} MiB last_rise="
            f"{inf.get('last_cumulative_increase_s')}s of "
            f"{inf.get('phase_duration_s')}s -> {target}"
        )
    requirement = result.get("requirement")
    if requirement is None:
        return f"[c2-lite] {case}: NO RESULT SHAPE RECOGNISED -> {target}"
    return (
        f"[c2-lite] {case}: outcome={requirement['outcome']} "
        f"disposition={result['disposition']} "
        f"authoritative={result['authoritative']} -> {target}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
