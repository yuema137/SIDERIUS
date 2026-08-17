# core/sandbox_executor.py
import contextlib
import json
import os
import random
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from typing import Any

# V21 PR C2 — imported for its SIDE EFFECT, deliberately.
#
# This module reads ``PLUGIN_CONFIG_REGISTRY`` directly at two sites
# (``_validate_configs`` and ``execute_training``'s config validation),
# testing membership rather than going through ``get_config_class``. That
# registry is populated by ``models_sandbox``'s module tail; importing
# ``models_format_sandbox`` alone does NOT populate it. Measured before this
# import: a process importing only ``core.sandbox_executor`` saw 0 of 82
# plugins, so a plugin model would have failed the membership test and
# fallen through to the built-in branch, producing a confusing config error
# instead of using its own config class.
#
# In today's chain the parent process always registers the current model
# explicitly (``model_exploration`` on generation, ``resume`` on restore),
# so the fall-through was not observed in production. "Not observed" is
# precisely what was believed about the same shape before V20 spent two PRs
# on it (#184, #185), which is why this is closed rather than argued away.
#
# A one-line side-effect import is used instead of rewriting the two
# membership tests, because changing which branch a model takes is a
# behavioural risk and this is not.
import ml_models.models_sandbox  # noqa: F401  (import side effect: plugin registry)
from core.inference_defaults import inference_batch_for
from core.runtime_control.records import MEASUREMENT_BACKED_SOURCES, RuntimeObservation
from core.runtime_control.session import RuntimeControlPolicy
from execute_tools.data_paths import TIDMAD_DATA_DIR
from execute_tools.dataset_config import (
    DataScope,
    ScopeViolationError,
    resolve_dataset_profile,
)
from execute_tools.deliverable_spec import DeliverableNaming, default_deliverable_naming
from execute_tools.evaluation_metric import (
    EvaluationMetric,
    MetricResult,
    NotScoreableError,
    NotScoreableResult,
    derive_tidmad_metric,
)
from execute_tools.scoring_utils import coerce_nonfinite_to_none, validate_sample_set
from execute_tools.training_history import (
    TRAINING_HISTORY_KEY,
    TrainingHistory,
    objective_config_fingerprint,
    stamp_comparability,
)
from ml_models.models_format_sandbox import (
    PLUGIN_CONFIG_REGISTRY,
    ExperimentConfig,
    LossConfig,
    TrainConfig,
    get_config_class,
    validate_output_loss_compatibility,
)
from ml_models.plugin_loader import UnknownOutputContractError


def _tidmad_data_dir() -> str:
    return TIDMAD_DATA_DIR


# ---------------------------------------------------------------------------
# Subprocess host-RAM hardening (Fix 1 of docs/optimize_inference_and_scoring.md)
# ---------------------------------------------------------------------------
#
# Context: on 2026-04-20 the orchestrator was terminated by the kernel's
# global OOM-killer mid-scoring with a 36.9 GB anon-RSS. SIGKILL is silent
# and irrecoverable — the parent had no chance to log or persist partial
# records. Wiring RLIMIT_AS into every subprocess we spawn converts the
# failure mode from "kernel kills the process" to "Python raises
# MemoryError", which the orchestrator can catch, record as a structured
# ``oom_host_ram`` failure, and skip past.
#
# The ceiling applies to virtual address space (RLIMIT_AS), not RSS, because
# RSS is not a POSIX-enforceable limit. VMS is a superset of RSS, so an AS
# cap transitively caps RSS — but the ratio is workload-dependent.
#
# VA-vs-RSS calibration (measured 2026-04-22 on RTX 5090, verified via
# /proc/self/status in an isolated reproducer — see docs §Fix 1 addendum):
#
#   * CPU-only subprocess (e.g. scoring): VmSize ≈ RSS + ~1 GiB import
#     overhead. 24 GiB VA cap gives ~23 GiB of real working memory.
#   * CUDA subprocess (training / inference): `import torch` alone reserves
#     ~5.8 GiB VA; `torch.cuda.is_available()` + context init reserves
#     another ~12.5 GiB VA for unified-memory mappings; a single cached
#     tensor adds another ~1.3 GiB. Total baseline ≈ 18-20 GiB VA with
#     ~0.7 GiB RSS. Under a 24 GiB cap, CUDA workloads get only ~4-6 GiB
#     of working VA — insufficient for PUNet-scale models plus AdamW
#     state plus focal-loss intermediates.
#
# CUDA-role budget is derived as:
#
#     40 GiB  =  20 GiB (static CUDA + torch VA overhead, rounded up
#                        from the 18-20 GiB measured baseline for headroom
#                        against driver-version drift)
#             +  16 GiB (target physical VRAM budget for model weights,
#                        activations, gradients, optimizer state — matches
#                        the pre-existing "training workloads peak below
#                        16 GB RSS" calibration)
#             +   4 GiB (safety margin for DataLoader workers, intermediate
#                        tensors the caching allocator reserves fresh VA
#                        for, and h5py read buffers)
#
# At 40 GiB the host still has ~21 GiB of physical RAM free after the cap,
# keeping the original Fix-1 protection intent intact — the point was to
# catch a runaway before the kernel OOM-killer wakes up, not to minimise
# absolute VA. Scoring stays at 24 GiB because its VA ≈ RSS on CPU-only
# code, and that was the exact codepath the 2026-04-20 incident hit.
#
# Inference override (bumped 2026-07-13 from 40 → 60 GiB): the Phase 1
# baseline path (``run_baseline_trial`` in ``scripts/run_comparison.py``,
# hardcoded ``trial_portion=1.0``) holds four ~1.86 GiB int8 numpy arrays
# simultaneously at ``inference_single.py:325-331`` (``denoised`` +
# ``injected`` + their ``.flatten().astype()`` copies passed to
# ``create_abra_file``) — ~7.4 GiB numpy peak on wavenet at seg_size=40k.
# Combined with the ~18-20 GiB CUDA VA baseline and h5py buffers, that
# reproducibly exceeded the 40 GiB cap (numpy._ArrayMemoryError on the
# fourth allocation). Trial-round and formal-round inference use much
# smaller LLM-planned ``eval_portion`` sample sets and would fit under
# 40 GiB, but sharing the cap keeps the sandbox launch path simple.

_ROLE_DEFAULT_RSS_GB = {
    "training": 40,  # CUDA — 20 (static) + 16 (working VRAM) + 4 (safety)
    "inference": 60,  # CUDA — training's 40 GiB + 20 GiB for full-scope numpy peak
    "scoring": 24,  # CPU-only — kept at original value, protects the 2026-04-20 incident path
}


def _subprocess_rss_gb(role: str) -> int:
    """Host-RAM ceiling (GiB) applied to a sandboxed subprocess.

    Args:
        role: One of ``"training"``, ``"inference"``, or ``"scoring"``.
              The default ceiling is chosen per-role because CUDA and
              CPU-only subprocesses have very different VA footprints
              (see VA-vs-RSS calibration note above).

    Resolution order:
        1. ``SIDERIUS_SUBPROCESS_RSS_GB`` (global override — if set, wins
           for every role; backward-compatible with the pre-role env var).
        2. Role-specific default from ``_ROLE_DEFAULT_RSS_GB``.

    Special values:
        * ``0`` — disable the ceiling entirely (pre-Fix-1 behaviour).
        * Negative / non-numeric env override — ignored, falls back to
          the role default.
    """
    if role not in _ROLE_DEFAULT_RSS_GB:
        raise ValueError(
            f"_subprocess_rss_gb: unknown role {role!r}; "
            f"expected one of {sorted(_ROLE_DEFAULT_RSS_GB)}"
        )
    raw = os.environ.get("SIDERIUS_SUBPROCESS_RSS_GB")
    if raw is None:
        return _ROLE_DEFAULT_RSS_GB[role]
    try:
        v = int(raw)
    except ValueError:
        return _ROLE_DEFAULT_RSS_GB[role]
    return v if v >= 0 else _ROLE_DEFAULT_RSS_GB[role]


def _limited_preexec(gb: int) -> Callable[[], None] | None:
    """Return a ``preexec_fn`` that caps the child's virtual address space.

    The callable is invoked by ``subprocess`` after ``fork`` and before
    ``exec``, so the limit takes effect for the child only — the parent is
    unaffected.

    Returns ``None`` when:
      * ``gb <= 0`` — the caller (via env var) disabled the ceiling;
      * the POSIX ``resource`` module is unavailable (non-POSIX hosts such
        as Windows).

    ``subprocess.run`` treats ``preexec_fn=None`` as "no hook", so callers
    can thread the return value through unconditionally.
    """
    if gb <= 0:
        return None
    try:
        import resource as _resource
    except ImportError:
        return None
    limit_bytes = gb * (1024**3)

    def _apply_limit() -> None:
        _resource.setrlimit(_resource.RLIMIT_AS, (limit_bytes, limit_bytes))

    return _apply_limit


_MEMORY_ERROR_RE = re.compile(r"\bMemoryError\b")


def _is_oom_failure(e: subprocess.CalledProcessError) -> bool:
    """Does ``e`` look like a host-RAM exhaustion in the child?

    Two signatures qualify:
      1. Python's built-in ``MemoryError`` appears in stderr — the RLIMIT_AS
         ceiling caught the allocation and Python raised a catchable
         exception. This is the post-Fix-1 happy path.
      2. The process was killed by SIGKILL (``returncode == -9``) — the
         kernel OOM-killer intervened, typically because the ceiling was
         disabled or the allocation was too large to be intercepted (e.g.
         a single ``mmap`` bigger than the cap). This is the pre-Fix-1
         failure mode and the case Fix 1 exists to prevent.

    We match ``MemoryError`` with word boundaries to avoid a false positive
    on ``torch.OutOfMemoryError``, which is a distinct CUDA-side error —
    the GPU allocator failed to serve a device allocation, and the host
    RSS/VA are not necessarily exhausted. Tagging a CUDA OOM as
    ``oom_host_ram`` would send the orchestrator down the wrong recovery
    path (it would shrink host-facing knobs when the real pressure is on
    the GPU, or — more importantly pre-role-aware-ceiling — obscure a
    VA-cap misconfiguration under a generic "host RAM" label).
    """
    if e.returncode == -9:
        return True
    return bool(e.stderr and _MEMORY_ERROR_RE.search(e.stderr))


def _format_subprocess_error(e: subprocess.CalledProcessError, label: str = "Subprocess") -> str:
    """
    Format a CalledProcessError into a useful diagnostic message.

    Combines stderr, stdout, exit code, and signal info so silent crashes
    (segfault, OOM-killed, GPU watchdog timeout) still leave a trace.
    """
    parts = [f"{label} failed with exit code {e.returncode}"]

    # Negative exit code = killed by signal
    if e.returncode is not None and e.returncode < 0:
        signal_num = -e.returncode
        signal_names = {
            9: "SIGKILL (likely OOM-killed by OS)",
            11: "SIGSEGV (segfault — likely C extension or driver crash)",
            6: "SIGABRT (assertion or abort)",
            15: "SIGTERM (terminated)",
        }
        sig_desc = signal_names.get(signal_num, f"signal {signal_num}")
        parts.append(f"Killed by {sig_desc}")

    if _is_oom_failure(e):
        parts.append(
            "[oom_host_ram] Host RAM exhaustion detected — either RLIMIT_AS "
            "ceiling hit (Python MemoryError) or kernel SIGKILL. See Fix 1 "
            "in docs/optimize_inference_and_scoring.md."
        )

    if e.stderr:
        parts.append(f"--- stderr ---\n{e.stderr}")
    if e.stdout:
        parts.append(f"--- stdout ---\n{e.stdout}")
    if not e.stderr and not e.stdout:
        parts.append("(no stdout/stderr captured — process may have crashed silently)")

    return "\n".join(parts)


def get_plugin_dir(workspace: str, run_name: str) -> str:
    """Compute the run-scoped plugin directory for a given workspace + run_name.

    Single source of truth for the layout described in
    docs/run_scoped_plugins.md: ``<workspace>/plugins/<run_name>/``. Both
    ``TidmadSandbox`` (producer of the dir) and the workflow's
    ``_register_plugin`` (which has to copy into it before the sandbox is
    constructed in-process) resolve the destination through this helper, so
    the two sides cannot drift.

    The path is absolutised to match ``TidmadSandbox.plugin_dir`` exactly —
    the sandbox computes its ``base_dir`` via ``os.path.abspath(workspace)``,
    so we do the same here to keep string equality usable in tests.
    """
    return os.path.join(os.path.abspath(workspace), "plugins", run_name)


def get_loss_dir(workspace: str, run_name: str) -> str:
    """Compute the run-scoped loss-plugin directory for a given workspace + run_name.

    Mirror of :func:`get_plugin_dir` for the loss-plugin surface (L1b — see
    ``docs/design/enable_loss_inventory.md`` § Commit L1). Single source of
    truth for the layout ``<workspace>/losses/<run_name>/`` so both
    ``TidmadSandbox`` (producer) and any future workflow-side staging helper
    cannot drift apart.

    The path is absolutised for the same reason as :func:`get_plugin_dir`:
    the sandbox stores `os.path.abspath(workspace)` internally, so we
    pre-compute the absolute form here to keep string equality usable.
    """
    return os.path.join(os.path.abspath(workspace), "losses", run_name)


def _subprocess_env(
    plugin_dir: str | None = None,
    loss_dir: str | None = None,
) -> dict:
    """Thin alias over the shared builder in `core.subprocess_env`.

    Kept as a name because this module's call sites and their tests refer
    to it. The CONSTRUCTION moved out after V20 attempt 2: the isolated
    measurement worker needed the identical environment, and two copies of
    "which variables a SIDERIUS subprocess needs" is precisely how the
    worker came to be missing `SIDERIUS_PLUGIN_DIRS` in the first place.
    """
    from core.subprocess_env import subprocess_env

    return subprocess_env(plugin_dir=plugin_dir, loss_dir=loss_dir)


# --- Storage Strategies ---


class BaseRecorder:
    """Base class for experiment recording."""

    def save_record(self, record: dict[str, Any]):
        raise NotImplementedError

    def get_summary(self) -> list:
        raise NotImplementedError


class LocalRecorder(BaseRecorder):
    """File-based recording for persistent agent memory."""

    def __init__(self, record_dir: str, summary_file: str, run_name: str):
        self.summary_file = summary_file
        self.record_dir = os.path.join(record_dir, run_name)
        _ensure_dir(self.record_dir)

    def save_record(self, record: dict[str, Any]):
        exp_id = record["exp_id"]

        # Coerce float('-inf') no-signal sentinels to JSON null so the on-disk
        # record stays browser-safe (RFC-8259 doesn't allow Infinity / -Infinity).
        safe_record = coerce_nonfinite_to_none(record)

        # every detail json should stay in the run_name folder
        detail_path = os.path.join(self.record_dir, f"{exp_id}.json")
        with open(detail_path, "w", encoding="utf-8") as f:
            json.dump(safe_record, f, indent=4, ensure_ascii=False)

        summary = self.get_summary()
        existing_idx = next(
            (i for i, item in enumerate(summary) if item.get("exp_id") == exp_id), None
        )

        if existing_idx is not None:
            summary[existing_idx] = safe_record
        else:
            summary.append(safe_record)

        with open(self.summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=4, ensure_ascii=False)

    def get_summary(self) -> list:
        if os.path.exists(self.summary_file):
            try:
                with open(self.summary_file, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                return []
        return []


class MongoRecorder(BaseRecorder):
    """MongoDB-based recording for robust development."""

    def __init__(self, uri: str, db_name: str):
        from pymongo import MongoClient  # type: ignore[reportMissingImports]

        self.client = MongoClient(uri)
        self.db = self.client[db_name]
        self.collection = self.db["experiments"]

    def save_record(self, record: dict[str, Any]):
        self.collection.update_one({"exp_id": record["exp_id"]}, {"$set": record}, upsert=True)

    def get_summary(self) -> list:
        # For MongoDB, we return more fields to support Agent reasoning
        cursor = self.collection.find({}, {"_id": 0})
        return list(cursor)


# --- Main Executor ---


def _ensure_dir(path: str) -> None:
    """Create directory if it does not exist. Raises RuntimeError with a clear message on failure."""
    try:
        os.makedirs(path, exist_ok=True)
    except PermissionError as e:
        raise RuntimeError(
            f"[Sandbox] Permission denied: cannot create directory '{path}'. "
            "Check that you have write access to the workspace."
        ) from e
    except OSError as e:
        raise RuntimeError(
            f"[Sandbox] Failed to create directory '{path}': {e}. "
            "Check that the path is valid and the filesystem is accessible."
        ) from e
    if not os.access(path, os.W_OK):
        raise RuntimeError(
            f"[Sandbox] Directory '{path}' exists but is not writable. "
            "Check filesystem permissions."
        )


def _watchdog_deadline_provider(
    policy: "RuntimeControlPolicy", rv_sidecar_path: str
) -> Callable[[], tuple[float | None, str]]:
    """§4 deadline: ``max(floor, min(operator_budget, verified × safety))``.

    The safety multiplier is the WATCHDOG-EFFECTIVE factor:
    ``policy.watchdog.safety_factor`` when set (V19 admission/watchdog
    split, 2026-07-29), else the shared ``policy.safety_factor`` —
    admission always reads the shared factor, so setting the watchdog
    override can never change admission behavior.

    The verified estimate comes from the attempt's LIVE observation
    sidecar (the RT2 event log) — the deadline tightens mid-flight as
    soon as the in-subprocess verification lands component predictions.
    Returns a provider yielding ``(deadline_seconds | None,
    estimate_source)``; ``None`` disables the deadline (nothing to
    enforce yet).

    **CLOCK CONVENTION — TOTAL ELAPSED SINCE SUBPROCESS START, not time
    remaining.** Recorded here by Step 07 / PR 07c C5 because it was
    implicit, and a term added under the wrong convention produces a
    deadline that looks right and fires at the wrong moment. The enforcement
    site is the only authority: ``t_start = time.perf_counter()`` is taken
    immediately after ``Popen`` and the watchdog loop compares
    ``elapsed = time.perf_counter() - t_start`` against ``deadline``. So a
    returned value is the whole wall-clock budget for the child, which is
    exactly what ``sum(predicted) * watchdog_factor`` already expresses.

    That is why 07c added the validation term WITHOUT touching the
    arithmetic below: a validation component with a measurement-backed
    prediction joins ``sum(predicted)`` and the total grows by the
    validation term and by nothing else.
    """
    watchdog_factor = (
        policy.watchdog.safety_factor
        if policy.watchdog.safety_factor is not None
        else policy.safety_factor
    )

    def provider() -> tuple[float | None, str]:
        candidates: list[tuple[float, str]] = []
        if policy.operator_budget_seconds is not None:
            candidates.append((policy.operator_budget_seconds, "operator_budget"))
        # VALIDATION POSTURE, None in every production campaign. A third
        # candidate rather than a replacement, so it can only ever TIGHTEN
        # the deadline. It is the only hard wall clock available on a
        # trial round, where operator_budget_seconds is None by design and
        # every remaining candidate is forecast-derived.
        if policy.watchdog.max_phase_seconds is not None:
            candidates.append((policy.watchdog.max_phase_seconds, "validation_max_phase"))
        block = _read_runtime_observation_sidecar(rv_sidecar_path)
        if block:
            components = (block.get("components") or {}).values()
            # C8d: a deadline may only be derived from MEASUREMENT-BACKED
            # component predictions (§7.4 watchdog column: static evidence
            # is `never_used`, historical priors `never_used_alone`). Every
            # prediction the RT2 session writes is measurement-backed by
            # construction — setup measures itself, phases predict only
            # after verifying — so this changes no production number; it
            # closes the door on a prior ever setting a kill deadline.
            # The arithmetic below is unchanged.
            predicted = [
                c["prediction"]["predicted_seconds"]
                for c in components
                if c.get("prediction") is not None
                and c["prediction"].get("predicted_seconds") is not None
                and c["prediction"].get("source") in MEASUREMENT_BACKED_SOURCES
            ]
            if predicted:
                estimate = sum(predicted) * watchdog_factor
                candidates.append((estimate, "verified_components"))
        if not candidates:
            return None, "none"
        deadline, source = min(candidates, key=lambda t: t[0])
        return max(deadline, policy.watchdog.floor_seconds), source

    return provider


def _phase_requirement(sandbox: Any, phase: str) -> tuple[float | None, str | None]:
    """The measured requirement for **this** phase, or `(None, None)`.

    B-G0 measured the same PUNet candidate at 1,476 MiB for training and
    2,716 MiB for inference — 1.8x apart on one card, in one run. A
    single figure shared by both gates therefore judges one phase by a
    measurement of the other, which is the applicability conflation the
    attribution rules exist to prevent, arriving through the requirement
    instead of through the verdict.

    So the requirement is a mapping keyed by phase:

        measured_requirements = {
            "training":  {"requirement_mib": ..., "provenance": ...},
            "inference": {"requirement_mib": ..., "provenance": ...},
        }

    A phase with no entry returns `(None, None)` and is refused in
    formal mode. There is deliberately **no fallback** — not to the other
    phase, not to the larger of the two, not to a model-name match. A
    substituted figure would be an assumption wearing a measurement's
    provenance.
    """
    # V20 PR C2 / C2-6. The TYPED table is the production channel. §8.A
    # names the duck-typed read below as the gap that "survived PR B and
    # its whole test suite" — a read no production code satisfied — so a
    # typed object now carries the requirement, and only an authoritative
    # measurement can be assembled into one.
    #
    # The `getattr` path is kept for the B-G validation harness, which
    # injects a plain dict and whose runs are evidence about this gate's
    # behaviour. Same shape as `admission_policy` / `admission_mode`
    # above: typed first, and when a typed table is present it is
    # authoritative, so the requirement cannot be read from two
    # disagreeing places.
    from core.runtime_control.gpu_requirement import MeasuredRequirementTable

    typed = getattr(sandbox, "measured_requirement_table", None)
    if isinstance(typed, MeasuredRequirementTable):
        return typed.for_phase(phase)

    table = getattr(sandbox, "measured_requirements", None)
    if not isinstance(table, Mapping):
        return None, None
    entry = table.get(phase)
    if not isinstance(entry, Mapping):
        return None, None
    requirement = entry.get("requirement_mib")
    provenance = entry.get("provenance")
    return (
        requirement if isinstance(requirement, int | float) else None,
        provenance if isinstance(provenance, str) else None,
    )


def _admission_refusal(sandbox: Any, *, phase: str) -> dict | None:
    """Refuse a GPU phase the device cannot currently hold (B-C4b).

    Returns a refusal status dict, or `None` to proceed. It is placed
    after the observer is constructed and **before** the watchdog/plain
    branch, so both launch paths sit behind one gate — a branch outside
    it would be a hole that looks like coverage.

    **Never raises, but never fails open in formal mode.** An error is
    converted into "no measurement was obtained" and handed to the
    admission policy, which decides by mode: trial proceeds with a
    recorded warning, formal refuses. Swallowing the error here into an
    unconditional `return None` would make the guard silently permissive
    exactly when it is supposed to protect — the fail-open posture this
    commit exists to remove.

    Pre-spawn this phase's child does not exist yet, so the tree rooted
    at this process is what "ours" means and everything else on the card
    is somebody else's. Whatever this process tree already holds is
    *measured* and counted as ours; PR A's isolated worker made that
    figure small in practice, but the logic does not assume it is zero.

    The requirement is whatever the run was given. PR B does not produce
    or promote one (D-B5), so in the default `trial` mode this admits and
    records that it asserted nothing; formal mode refuses until PR C
    supplies a measurement. No default moves in this commit.
    """
    identity = getattr(sandbox, "device_identity", None)
    if identity is None:
        # No device identity means there is no device to decide about —
        # the pre-PR-B path. Unchanged behaviour, not a refusal.
        return None

    # B-G3: the typed policy is the production channel. The `getattr`
    # fallbacks below are the pre-B-G3 path and the validation harness's
    # injection seam; when a policy is supplied it is authoritative, so
    # posture and ceiling cannot be read from two disagreeing places.
    policy = getattr(sandbox, "admission_policy", None)
    mode = policy.mode if policy is not None else getattr(sandbox, "admission_mode", "trial")
    ceiling_gib = policy.ceiling_gib if policy is not None else None
    # Enforcement comes ONLY from the typed policy. The legacy duck-typed
    # path — a bare `admission_mode` attribute, which is how the B-G
    # validation harness injects posture — always enforced, and B-G1/B-G2
    # are evidence about that behaviour, so it keeps enforcing. Defaulting
    # it to `observe_only` here would have silently disarmed the gate for
    # every harness scenario while the tests still looked green.
    #
    # Production always supplies a policy, so production gets the
    # `observe_only` compatibility default from the field itself.
    enforcement = policy.enforcement if policy is not None else "enforce"
    requirement_mib, requirement_provenance = _phase_requirement(sandbox, phase)
    snapshot = None
    sampling_error = None
    try:
        from core.runtime_control.gpu_accounting import sample

        # Pre-spawn: this phase's child does not exist yet, so the tree
        # rooted at this process is what "ours" means, and everything
        # else on the card is somebody else's. Whatever this process
        # tree already holds is counted as ours rather than as other —
        # measurement, not an assumption that it is near zero.
        snapshot = sample(os.getpid(), identity)
    except Exception as exc:
        sampling_error = f"{type(exc).__name__}: {exc}"

    try:
        from core.runtime_control.admission import evaluate_gpu_admission

        decision = evaluate_gpu_admission(
            snapshot=snapshot,
            requirement_mib=requirement_mib,
            requirement_provenance=requirement_provenance,
            mode=mode,
            run_name=getattr(sandbox, "run_name", None) or "candidate",
            ceiling_gib=ceiling_gib,
            sampling_error=sampling_error,
        )
    except Exception as exc:
        # The policy itself failed, so there is no decision to consult.
        # Only an explicitly `trial` posture may proceed: formal must not
        # fall through to a launch, and an unrecognised mode is a
        # misconfiguration, which is also not permission.
        if mode == "trial":
            return None
        reason = f"the admission decision could not be evaluated ({type(exc).__name__}: {exc})"
        print(f"--- [Admission] {phase} refused: {reason}")
        return {
            "status": "skipped_resource_admission",
            "message": reason,
            "admission": {
                "admitted": False,
                "reason_code": "measurement_unavailable",
                "requirement_source": "unavailable",
                "reason": reason,
                "evidence": {"mode": mode, "policy_error": str(exc)},
            },
        }

    if decision.admitted:
        return None

    # B-G3/D-B4 split: the decision above is real either way. What
    # `enforcement` decides is whether an adverse one STOPS the phase.
    #
    # `observe_only` is the compatibility default while PR C does not yet
    # supply authoritative measurements: without it, making the gate
    # reachable would stop formal training repository-wide, because every
    # formal round would correctly refuse `policy_unavailable`.
    #
    # The phase is NOT relabelled to keep it running. Calling a formal
    # round `trial` would make every record claim a posture the round did
    # not have; provenance that lies is worse than a guard that does not
    # fire. So the posture stays `formal`, the refusal is recorded as
    # `would_refuse`, and execution continues.
    #
    # M5 (2026-08-06), frozen by the operator after the pre-launch audit:
    #
    #     current resources + candidate demand + safety policy -> Admission
    #         enough      -> admit
    #         insufficient -> REJECT, and production must not continue
    #
    # `enforce_resource_limits` — the V20 production posture — stops the
    # phase on that resource verdict. `enforce` still stops on everything.
    # `admission.stops_phase` owns the distinction so this executor cannot
    # answer the question differently from the policy module.
    #
    # Presence, registration, variability and PID churn of external work
    # are not consulted anywhere in this decision — `insufficient_headroom`
    # is a statement about measured headroom, never about who else is on
    # the card. An empty GPU is not required.
    from core.runtime_control.admission import stops_phase

    if not stops_phase(enforcement, decision.reason_code):
        # Why this one was observed rather than enforced is itself a fact
        # an audit needs: under `enforce`, "observed" now means the refusal
        # was an evidence gap, not a resource verdict, and a reader must be
        # able to tell those apart without re-deriving the policy.
        not_enforced_because = (
            "reason_code_is_not_a_resource_rejection"
            if enforcement == "enforce_resource_limits"
            else "enforcement_observe_only"
        )
        observation = {
            "phase": phase,
            "enforcement": enforcement,
            "would_refuse": True,
            "mode": mode,
            "reason": decision.reason,
            "reason_code": decision.reason_code,
            "not_enforced_because": not_enforced_because,
            "admission": decision.model_dump(mode="json"),
        }
        _record_admission_observation(sandbox, observation)
        print(
            f"--- [Admission] {phase} WOULD BE REFUSED ({enforcement}, "
            f"{decision.reason_code}): {decision.reason}. Proceeding because "
            f"{not_enforced_because}; the phase posture remains '{mode}'."
        )
        return None

    print(f"--- [Admission] {phase} refused: {decision.reason}")
    return {
        "status": "skipped_resource_admission",
        "message": decision.reason,
        "admission": decision.model_dump(mode="json"),
    }


def _record_admission_observation(sandbox: Any, observation: dict) -> None:
    """Persist an observe-only admission decision.

    Kept out of `_admission_refusal` so that function stays a decision,
    not a decision plus a writer. The list is what a run is audited by:
    an `observe_only` interval must leave behind exactly which phases
    would have been refused and why, or "we observed it" is unfalsifiable.
    """
    try:
        observations = getattr(sandbox, "admission_observations", None)
        if observations is None:
            observations = []
            sandbox.admission_observations = observations
        observations.append(observation)
    except Exception:
        # Recording is auditing, not control. It must never be able to
        # stop a phase the gate decided to allow.
        return


def _make_phase_observer(sandbox: Any) -> Any:
    """One observer for one GPU phase, or None when there is no identity.

    Imported lazily so `sandbox_executor` keeps no import-time dependency
    on the observer, and so a telemetry import failure can never stop a
    training run.
    """
    identity = getattr(sandbox, "device_identity", None)
    if identity is None:
        return None
    try:
        from core.runtime_control.gpu_observer import GpuPhaseObserver

        return GpuPhaseObserver(identity, policy=getattr(sandbox, "observation_policy", None))
    except Exception:  # pragma: no cover - telemetry must not break the phase
        return None


def _has_host_memory_evidence(e: subprocess.CalledProcessError) -> bool:
    """Genuine host-memory corroboration, distinct from a bare signal.

    Deliberately NOT ``_is_oom_failure``: that also returns True for
    ``returncode == -9``, which is compatible with a kernel OOM kill, a
    quota watchdog and an operator, and cannot tell them apart. Only the
    ``MemoryError`` signature is real evidence — the RLIMIT_AS ceiling
    caught the allocation and Python raised. Feeding ``-9`` in here
    would let a signal launder itself into a verdict, which is the
    inference B-C3 exists to refuse.
    """
    return bool(e.stderr and _MEMORY_ERROR_RE.search(e.stderr))


def _with_failure_attribution(
    result: dict, e: subprocess.CalledProcessError, observer: Any
) -> dict:
    """Classify the failure here, where the evidence still exists (B-C3b).

    This is the only point at which all of it coexists: the child's full
    stderr (with the attempted-allocation size), the live evidence
    bundle, and the return code. Downstream the message is truncated to
    its last 500 characters — and because stdout is appended after
    stderr, that window normally holds trainer progress output rather
    than the allocation line. Attribution reconstructed from a stored
    record would therefore be attribution built on the wrong text.

    Never raises: a failure to classify must not change the phase's own
    result. An absent attribution reads as ``unknown`` downstream.
    """
    with contextlib.suppress(Exception):
        from core.runtime_control.failure_attribution import (
            attribute_gpu_failure,
            attribute_process_termination,
            extract_attempted_allocation_mib,
            looks_like_cuda_oom,
        )

        # Arbitration: a credible device-side OOM is a statement about
        # the device; anything else is a statement about the process.
        if looks_like_cuda_oom(e.stderr):
            verdict = attribute_gpu_failure(
                bundle=observer.bundle() if observer is not None else None,
                attempted_allocation_mib=extract_attempted_allocation_mib(e.stderr),
                failure_text=e.stderr,
            )
        else:
            verdict = attribute_process_termination(
                returncode=e.returncode,
                host_memory_evidence=_has_host_memory_evidence(e),
                # No producer exists for an external-termination marker;
                # claiming one would manufacture certainty (FU-B-10).
                external_signal_evidence=False,
                failure_text=e.stderr,
            )
        result["failure_attribution"] = verdict.model_dump(mode="json")
    return result


def _with_gpu_evidence(result: dict, observer: Any) -> dict:
    """Attach the bounded evidence bundle to a FAILURE result.

    Failure only, per the B-C2b persistence boundary: sampling runs on
    every attempt because the baseline and peak cannot be reconstructed
    afterwards, but writing four snapshots into every successful record
    would be an unannounced schema and storage change on the hot path.

    Never raises. Telemetry must not be able to fail the phase it
    watched, so a bundle that cannot be produced is simply absent.
    """
    if observer is None:
        return result
    with contextlib.suppress(Exception):  # telemetry never fails the phase
        result["gpu_evidence"] = observer.bundle().model_dump(mode="json")
    return result


def _run_observed_subprocess(
    cmd: list[str],
    *,
    env: dict,
    preexec_fn: Callable[[], None] | None,
    capture_stdout: bool,
    deadline_provider: Callable[[], tuple[float | None, str]] | None = None,
    grace_seconds: float = 0.0,
    poll_seconds: float = 0.0,
    label: str = "",
    observer: Any = None,
) -> tuple[subprocess.CompletedProcess | None, dict[str, Any] | None]:
    """The single seam every GPU child is launched through (V20 B-C2a1).

    **Routing only.** This commit changes *where* the four GPU launches
    are expressed, not *how* any of them runs. Both implementations below
    are the pre-existing ones, moved behind one door so that the observer
    in B-C2b attaches once instead of at four call sites, where one
    branch could silently lose it.

    ``deadline_provider=None`` — plain mode, delegating to the same
    ``subprocess.run(..., check=True)`` these call sites used before.

    ``deadline_provider`` supplied — deadline mode, the existing §4
    watchdog: own process group, SIGTERM, ``grace_seconds``, SIGKILL,
    then assert the group is gone. Returns ``(None, kill_info)`` when the
    deadline fires.

    **Why plain mode is not also on ``Popen`` yet.** B-C2b needs the child
    PID while the child is alive, which ``subprocess.run`` cannot give.
    But moving plain mode to ``Popen`` retires the launch point that 58
    existing stubs across six test files are aimed at, and a stub that
    stops intercepting does not fail — it lets the real thing run. That
    was measured, not predicted: real ``train_engine_sandbox.py``
    subprocesses launched out of the unit suite. The migration is
    therefore its own checkpoint (B-C2a2), so a test-infrastructure
    change, an execution-mechanism change and a telemetry change cannot
    mask one another.

    **Why the session behaviour is not unified, and will not be.**
    ``killpg`` needs its own group, so deadline mode passes
    ``start_new_session=True``. A child in its own session does *not*
    receive a terminal SIGINT, while a child in the caller's group does —
    and the chain runs under ``timeout --signal=INT``, so operator stop
    depends on that signal reaching the work. Unifying the two would
    change operator stop semantics through a diff that looks like a
    refactor.

    **The observer is an argument, not a third return value.** B-C2b
    needs evidence out of this function, and the obvious shape is to
    return it — but the return tuple is what 48 migrated test stubs
    across six files were just reshaped around, and widening it would
    re-break every one of them for a reason unrelated to what they test.
    So the caller owns the observer, passes it in, and reads
    ``observer.bundle()`` afterwards. The seam only drives its lifecycle.
    """
    if deadline_provider is None:
        # Plain mode. Faithful to the `subprocess.run(..., check=True)`
        # this replaced, but on `Popen` so B-C2b can hold the child PID
        # while the child is alive — which is the whole reason for the
        # migration, and something `subprocess.run` cannot give.
        #
        # `start_new_session` is NOT passed, matching `subprocess.run`'s
        # default: a child in the caller's process group receives a
        # terminal SIGINT, and the chain runs under `timeout
        # --signal=INT`. Only the deadline path below takes its own
        # session, because `killpg` requires one.
        if observer is not None:
            # Before the child exists, so it can claim nothing about it.
            observer.capture_baseline()
        plain = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE if capture_stdout else None,
            stderr=subprocess.PIPE,
            text=True,
            cwd=os.getcwd(),
            env=env,
            preexec_fn=preexec_fn,
        )
        if observer is not None:
            observer.start(plain.pid)
        failed = True
        try:
            stdout, stderr = plain.communicate()
            failed = plain.returncode != 0
        except BaseException:
            # `subprocess.run` kills and reaps rather than leaking the
            # child on any exception; reproduce that exactly.
            plain.kill()
            plain.wait()
            raise
        finally:
            # In `finally`, so the observer stops on every path — success,
            # non-zero exit, and any exception. It never affects the
            # child's own result.
            if observer is not None:
                observer.stop(child_pid=plain.pid, failed=failed)
        if plain.returncode != 0:
            # `Popen` has no `check`. The property downstream handlers
            # depend on is the exception, not the keyword.
            raise subprocess.CalledProcessError(plain.returncode, cmd, output=stdout, stderr=stderr)
        return (
            subprocess.CompletedProcess(cmd, plain.returncode, stdout=stdout, stderr=stderr),
            None,
        )

    if observer is not None:
        observer.capture_baseline()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE if capture_stdout else None,
        stderr=subprocess.PIPE,
        text=True,
        cwd=os.getcwd(),
        env=env,
        preexec_fn=preexec_fn,
        start_new_session=True,  # own process group — killpg reaches every child
    )
    if observer is not None:
        observer.start(proc.pid)
    t_start = time.perf_counter()
    stdout, stderr = "", ""
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=poll_seconds)
            break  # natural exit
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - t_start
            deadline, source = deadline_provider()
            if deadline is None or elapsed <= deadline:
                continue
            # §4 kill sequence: TERM the group → grace → KILL the group.
            pgid = os.getpgid(proc.pid)
            print(
                f"--- Watchdog [{label}] deadline exceeded "
                f"({elapsed:.1f}s > {deadline:.1f}s, source={source}) — "
                f"killing process group {pgid} ---"
            )
            escalated = False
            os.killpg(pgid, signal.SIGTERM)
            try:
                stdout, stderr = proc.communicate(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                escalated = True
                os.killpg(pgid, signal.SIGKILL)
                stdout, stderr = proc.communicate()
            # Orphan check: the group must be gone (§4 "verify no
            # surviving pids"). killpg(0) probes without sending.
            # After SIGKILL the kernel needs a brief moment to reap PIDs;
            # ``proc.communicate()`` above only waits for the TRACKED
            # child, so children in the same process group can still be
            # in the reap window when the probe runs. Poll briefly
            # (bounded, ≤2 s at 50 ms intervals) so the fast path
            # (already reaped) still returns on the first probe while
            # ruling out reap-window races that used to false-positive
            # under load (CI runners, busy dev boxes).
            survivors = True
            _survivor_probe_deadline = time.perf_counter() + 2.0
            while time.perf_counter() < _survivor_probe_deadline:
                try:
                    os.killpg(pgid, 0)
                except ProcessLookupError:
                    survivors = False
                    break
                time.sleep(0.05)
            if survivors:
                print(f"--- Watchdog [{label}] WARNING: process group {pgid} survived ---")
            if observer is not None:
                observer.stop(child_pid=proc.pid, failed=True)
            return None, {
                "elapsed_s": round(elapsed, 3),
                "deadline_s": round(deadline, 3),
                "estimate_source": source,
                "escalated_to_kill": escalated,
                "survivors_detected": survivors,
                "stdout_tail": (stdout or "")[-2000:],
                "stderr_tail": (stderr or "")[-2000:],
            }
    if observer is not None:
        observer.stop(child_pid=proc.pid, failed=proc.returncode != 0)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=stdout, stderr=stderr)
    return (
        subprocess.CompletedProcess(cmd, proc.returncode, stdout=stdout, stderr=stderr),
        None,
    )


def _read_runtime_observation_sidecar(path: str) -> dict[str, Any] | None:
    """Read + validate the subprocess's runtime-verification sidecar (RT2-B).

    Returns the observation as a plain dict, or ``None`` when the sidecar
    is absent (legacy subprocess, non-streaming mode) or malformed. A
    malformed sidecar is reported and treated as absent — verification
    evidence degrades to "no evidence", it never breaks the training
    result path (fail-open here is safe: absence of evidence is already
    the fail-closed default everywhere it is consumed, §7.3).
    """
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return RuntimeObservation.model_validate(raw).model_dump(mode="json")
    except Exception as exc:
        print(f"[Executor] runtime-verification sidecar unreadable ({path}): {exc}")
        return None


def _scope_violation_result(e: ScopeViolationError) -> dict[str, Any]:
    """Convert a ScopeViolationError into the executor error-dict shape.

    ``error_type="scope_violation"`` is the structured classification the
    tuner keys on (non-retryable configuration/invariant failure — see
    docs/design/enable_partial_file_list.md, DS5). The
    ``error_scope_violation:`` message prefix follows the existing
    ``error_training:`` prefix convention for greppability.
    """
    msg = f"error_scope_violation: {e}"
    print(f"--- Scope Violation ---\n{msg}")
    return {"status": "error", "error_type": "scope_violation", "message": msg}


class TidmadSandbox:
    def __init__(
        self,
        metadata_source: str = "local",
        mongodb_uri: str | None = None,
        run_name: str = "test_run",
        workspace: str = "./siderius_workspace",
        progress_bar: bool = False,
        file_index: int = 6,
        data_scope: DataScope | None = None,
        device_identity: Any = None,
        observation_policy: Any = None,
        admission_policy: Any = None,
        deliverable_naming: DeliverableNaming | None = None,
    ):
        # Step 05c — the run's deliverable naming authority. The tuner resolves
        # it ONCE from the run profile and passes it here, so the parent-side
        # readers (this class's watchdog cleanup) and the tuner's own readers
        # cannot disagree about what an attempt's artifacts are called. `None`
        # resolves the shipped TIDMAD default, which is what every caller that
        # predates 05c gets — identical behaviour, no migration.
        self.deliverable_naming = (
            deliverable_naming if deliverable_naming is not None else default_deliverable_naming()
        )
        # Boundary DataScope invariant: every SampleSet is validated against
        # this scope before any file I/O (train / inference / score_vector).
        # Default = complete dataset (behavior identical to pre-scope code).
        # V20 B-C2b. Explicit and optional: `None` means telemetry is
        # unavailable, and this class must never discover a device of its
        # own — implicit rediscovery is how "GPU 0" gets assumed.
        self.device_identity = device_identity
        self.observation_policy = observation_policy
        # V20 B-G3. The typed admission boundary. `None` preserves
        # pre-B-G3 behaviour exactly: the gate falls back to the
        # `admission_mode`/`measured_requirements` duck-typed reads, which
        # in production resolve to trial + no requirement and therefore
        # admit. Setting it is what makes the gate reachable at all.
        self.admission_policy = admission_policy
        #: Adverse decisions taken while enforcement was `observe_only`.
        #: Empty is a real result: it means nothing would have been
        #: refused, not that nothing was checked.
        self.admission_observations: list[dict] = []
        self.data_scope = data_scope or DataScope.default()
        self.base_dir = os.path.abspath(workspace)
        self.dirs = {
            "configs": os.path.join(self.base_dir, "configs", run_name),
            "models": os.path.join(self.base_dir, "cached_models"),
            "records": os.path.join(self.base_dir, "records"),
            "data": _tidmad_data_dir(),
        }
        for key, d in self.dirs.items():
            if key != "data":  # data dir is read-only input, not agent-generated output
                _ensure_dir(d)

        # Run-scoped plugin directory — see docs/run_scoped_plugins.md (Phase 2).
        # Lives under ``self.base_dir`` (the workspace) alongside
        # ``configs/<run_name>/``, so two sandboxes on different workspaces
        # never collide and tests that point ``workspace`` at ``tmp_path`` are
        # automatically self-contained. Created eagerly so downstream steps
        # (seed plugin copy in Phase 3, implementor writes in Phase 4) have a
        # stable target without having to mkdir. The layout is computed via
        # ``get_plugin_dir`` so the workflow (which copies implementor output
        # into this dir *before* the sandbox exists in-process) and the
        # sandbox itself share one path formula.
        self.plugin_dir = get_plugin_dir(workspace, run_name)
        _ensure_dir(self.plugin_dir)

        # Run-scoped loss-plugin directory (L1b — enable_loss_inventory).
        # Mirror of ``plugin_dir`` for the loss surface: lives under
        # ``self.base_dir`` so test workspaces are self-contained, created
        # eagerly so the subprocess can scan it (empty until L4 actually
        # generates a loss into it). Threaded into every subprocess env
        # below via ``_subprocess_env(..., loss_dir=self.loss_dir)``.
        self.loss_dir = get_loss_dir(workspace, run_name)
        _ensure_dir(self.loss_dir)

        self.run_name = run_name
        self.progress_bar = progress_bar
        self.file_index = file_index
        # Initialize Recorder based on strategy
        if metadata_source == "mongodb" and mongodb_uri:
            self.recorder = MongoRecorder(mongodb_uri, "tidmad_db")
        else:
            self.recorder = LocalRecorder(
                self.dirs["records"],
                os.path.join(self.base_dir, f"summary_{self.run_name}.json"),
                self.run_name,
            )

    def save_record(self, record: dict[str, Any]):
        """Direct access for ml_hyperparameter_tune_agent to save finalized research records."""
        self.recorder.save_record(record)

    def get_summary(self) -> list:
        """Retrieves experiment history for the Agent's planning phase."""
        return self.recorder.get_summary()

    def _validate_configs(
        self, model_type: str, m_cfg: dict, t_cfg: dict, l_cfg: dict, exp_id: str, run_name: str
    ):
        """Internal helper to validate dicts using the appropriate config schema.

        Plugin models bypass ExperimentConfig (which has hardcoded Literals for core
        model types) and are validated directly against their own config class.
        """
        # Plugin model: validate against the plugin's own config class
        if model_type in PLUGIN_CONFIG_REGISTRY:
            try:
                validated_m = PLUGIN_CONFIG_REGISTRY[model_type](**m_cfg).model_dump()
                # Ensure model_type is in the serialized config so the training
                # subprocess can look up the correct model class.
                validated_m["model_type"] = model_type
                validated_t = TrainConfig(**t_cfg).model_dump()
                loss_cfg = LossConfig(**l_cfg)

                # V21 PR A2b — model/loss compatibility on the GENERATED-MODEL
                # branch. Before this call, ExperimentConfig (which carries the
                # rule) was bypassed here, so the only kind of model the agent
                # actually invents was governed by no compatibility rule at
                # all: a plugin declaring `classifier` paired with `smooth_l1`
                # was accepted and failed later, deep in the loss.
                #
                # This calls the SHARED authority. Do not inline the rule —
                # a second copy is the defect A1 deleted.
                from ml_models.plugin_loader import get_output_type

                validate_output_loss_compatibility(
                    get_output_type(model_type),
                    loss_cfg.loss_type,
                    model_type=model_type,
                )

                validated_l = loss_cfg.model_dump()
                return validated_m, validated_t, validated_l
            except UnknownOutputContractError as e:
                # V21 PR C1 — typed INFRASTRUCTURE refusal, deliberately
                # worded apart from "Configuration Rejected" below.
                #
                # Reaching here means the model IS in PLUGIN_CONFIG_REGISTRY
                # but NOT in PLUGIN_OUTPUT_TYPE_REGISTRY: the registries have
                # diverged, which is a partial-registration bug, not a bad
                # config the agent could fix by proposing different values.
                #
                # V20 burned two PRs on a `CONFIG_REJECTED` that was really a
                # registry-reconstruction failure (#184 then #185). Letting
                # this fall into the generic branch below would reproduce
                # exactly that misdiagnosis.
                raise ValueError(
                    f"Plugin Output Contract Unavailable (registration defect, "
                    f"not a config error): {e!s}"
                ) from e
            except Exception as e:
                raise ValueError(f"Plugin Experiment Configuration Rejected: {e!s}") from e

        # Core model: use the strict ExperimentConfig with cross-validation
        try:
            full_payload = {
                "exp_id": exp_id,
                "run_name": run_name,
                "model_type": model_type,
                "network_config": m_cfg,
                "train_config": t_cfg,
                "loss_config": l_cfg,
            }
            exp_config = ExperimentConfig(**full_payload)
            return (
                exp_config.network_config.model_dump(),
                exp_config.train_config.model_dump(),
                exp_config.loss_config.model_dump(),
            )
        except Exception as e:
            raise ValueError(f"Experiment Configuration Rejected: {e!s}") from e

    def _write_model_io_config(self, exp_id: str) -> str | None:
        """Materialize the resolved Model-I/O contract for a subprocess.

        The parent half of the Step-03 transport, using the SAME
        config-file + argv-flag mechanism as ``--dataset_profile_json`` and
        ``--model_cfg``. No new IPC is introduced — §16 routes IPC to Step 11,
        and the 02a C3 lesson is to follow the existing pattern exactly.

        Returns ``None`` when the shipped task declares no ``model_io``, i.e.
        a legacy prose-only contract. The caller then omits the flag entirely,
        which is the Regime-A adapter — deliberately different from supplying
        a broken path, which fails closed in the child.

        Step 05b: the value comes from ``run_bound_model_io_contract`` — the
        ONE run-binding acquisition point — rather than from an expression
        restated here. The tuner's resource pre-flight now needs the same
        contract, and two sites computing it independently would make
        "training and the pre-flight agree" a coincidence rather than a
        structural fact.
        """
        from workflows.task_config import run_bound_model_io_contract

        contract = run_bound_model_io_contract()
        if contract is None:
            return None
        path = os.path.abspath(os.path.join(self.dirs["configs"], f"model_io_{exp_id}.json"))
        with open(path, "w") as handle:
            json.dump(contract.model_dump(mode="json"), handle)
        return path

    def _write_dataset_profile_config(self, exp_id: str) -> str:
        """Materialize the resolved Dataset Profile for a subprocess.

        One declaration, one file, three consumers. Training, inference and
        scoring each receive the SAME resolved profile through the same
        config-file + argv-flag mechanism already used for ``--model_cfg``
        and friends, so the three data paths cannot interpret the dataset
        differently — the exact failure the operator cited when deciding all
        three boundaries stay in one PR (§3.4).

        Written once per ``exp_id``; re-writing is idempotent because the
        resolved profile does not change within a run.

        Args:
            exp_id: Experiment id, used to key the file within the run.

        Returns:
            Absolute path to the JSON the child loads.
        """
        path = os.path.abspath(os.path.join(self.dirs["configs"], f"dataset_profile_{exp_id}.json"))
        with open(path, "w") as handle:
            json.dump(resolve_dataset_profile().model_dump(), handle)
        return path

    def execute_training(
        self,
        exp_id: str,
        run_name: str,
        model_type: str,
        m_cfg: dict,
        t_cfg: dict,
        l_cfg: dict,
        sample_set: dict | None = None,
        train_portion: float | None = None,
        train_base_seed: int | None = None,
        runtime_policy: dict | None = None,
        order_strategy: str = "shuffle",
        file_order: list[int] | None = None,
        eval_sample_set: dict | None = None,
    ):
        """Executes the training physical script.

        Args:
            sample_set:      Optional SampleSet dict — the data scope. When provided,
                             written to JSON and passed via --sample_set_json.
            eval_sample_set: Step 07a — the tuner's EXISTING run-bound eval
                             SampleSet (VALIDATION file family). Streaming mode
                             only: when BOTH ``sample_set`` and this are given
                             it is validated by the SAME rule as the train set
                             (``validate_sample_set(scope=self.data_scope)``),
                             written to ``configs/<run>/eval_sample_set_<exp_id>.json``
                             in the SAME compact ``json.dump`` byte form, and
                             passed as the ONE declared argv delta
                             ``--eval_sample_set_json <path>`` immediately after
                             the ``--sample_set_json`` pair. Legacy mode
                             (``sample_set is None``) never emits the flag.
                             (The inference route writes the same file name
                             with the same tuner-owned set for the attempt.)
            train_portion:   Fraction of the scope to subsample per epoch for training.
                             Passed via --train_portion.
            train_base_seed: Base seed for per-epoch subsampling reproducibility.
                             Passed via --train_base_seed.
            runtime_policy:  Optional RT2-B runtime policy dict (validated
                             against ``RuntimeControlPolicy`` before launch).
                             Streaming mode only. When the in-subprocess
                             admission decision rejects the attempt, the
                             return is ``{"status": "rejected_time_risk",
                             "runtime_verification": <observation>}`` —
                             distinguishable from every error path.

        The returned dict carries ``runtime_verification`` (the subprocess's
        observation sidecar as a dict, or ``None``) on success, rejection,
        and subprocess-error paths alike — a partially written observation
        from a crashed run is still evidence (§6.2 event log).
        """
        # Sidecar the subprocess writes its runtime observation to (RT2-B).
        # Computed up front so every return path (including exception
        # handlers) can attach whatever the subprocess managed to record.
        rv_sidecar_path = os.path.abspath(
            os.path.join(self.dirs["configs"], f"runtime_verification_{exp_id}.json")
        )
        try:
            policy_obj = (
                RuntimeControlPolicy(**runtime_policy) if runtime_policy is not None else None
            )
            vm, vt, vl = self._validate_configs(model_type, m_cfg, t_cfg, l_cfg, exp_id, run_name)

            paths = {
                "m": os.path.abspath(
                    os.path.join(self.dirs["configs"], f"model_config_{exp_id}.json")
                ),
                "t": os.path.abspath(
                    os.path.join(self.dirs["configs"], f"train_config_{exp_id}.json")
                ),
                "l": os.path.abspath(
                    os.path.join(self.dirs["configs"], f"loss_config_{exp_id}.json")
                ),
            }
            for k, v in zip(["m", "t", "l"], [vm, vt, vl], strict=True):
                with open(paths[k], "w") as f:
                    json.dump(v, f)

            dp_path = self._write_dataset_profile_config(exp_id)
            # Step 03 — the Model-I/O contract crosses the SAME boundary.
            # `None` (a task with no `model_io`) omits the flag entirely,
            # which is the child's Regime-A adapter; it is never passed as an
            # empty string, because "flag present but broken" fails closed
            # there and must not be triggered by an absent declaration.
            mio_path = self._write_model_io_config(exp_id)

            cmd = [
                sys.executable,
                "execute_tools/train_engine_sandbox.py",
                "--model_cfg",
                paths["m"],
                "--train_cfg",
                paths["t"],
                "--loss_cfg",
                paths["l"],
                "--dataset_profile_json",
                dp_path,
                "--exp_id",
                exp_id,
                "--run_name",
                run_name,
                "--sandbox_dir",
                self.base_dir,
                "--file_index",
                str(self.file_index),
            ]

            # SampleSet boundary contract — this is ONE of exactly TWO
            # production serialization sites (the other is in
            # ``execute_inference``). Both obey the same shape:
            #
            #     validate_sample_set -> compact json.dump -> --sample_set_json
            #
            if mio_path is not None:
                cmd += ["--model_io_json", mio_path]

            # Keys are int on this side and str on the subprocess side, because
            # that is what JSON is; value lists cross unchanged; the live
            # consumer (``TIDMADEpochDataset``) re-ints NUMERICALLY. An invalid
            # SampleSet is rejected here, before any launch primitive is called.
            #
            # The two sites differ ONLY in how that rejection surfaces — this
            # one is converted by the method's outer handler, the eval one
            # returns a structured error dict for ScopeViolationError. That
            # difference is pre-existing and deliberate; do not "tidy" it.
            #
            # The emitted BYTES are part of the contract: adding ``indent=`` or
            # ``sort_keys=`` here would change every config the subprocess
            # reads. Pinned by tests/unit/execute_tools/
            # test_step02b_b1_sampleset_roundtrip.py and
            # test_step02b_b3_boundary_byte_parity.py.
            if sample_set is not None:
                sample_set = validate_sample_set(sample_set, scope=self.data_scope)
                ss_path = os.path.abspath(
                    os.path.join(self.dirs["configs"], f"train_sample_set_{exp_id}.json")
                )
                with open(ss_path, "w") as f:
                    json.dump(sample_set, f)
                cmd.extend(["--sample_set_json", ss_path])
                # Step 07a — the eval SampleSet's sibling flag: same rule, same
                # byte form, position immediately after the train-set pair
                # (design §3.4, Q-07a-7). Emitted ONLY when an eval set is
                # given, so every pre-07a argv is unchanged.
                if eval_sample_set is not None:
                    eval_sample_set = validate_sample_set(eval_sample_set, scope=self.data_scope)
                    ess_path = os.path.abspath(
                        os.path.join(self.dirs["configs"], f"eval_sample_set_{exp_id}.json")
                    )
                    with open(ess_path, "w") as f:
                        json.dump(eval_sample_set, f)
                    cmd.extend(["--eval_sample_set_json", ess_path])
                if train_portion is not None:
                    cmd.extend(["--train_portion", str(train_portion)])
                if train_base_seed is not None:
                    cmd.extend(["--train_base_seed", str(train_base_seed)])
                # V19 PR 2: RESOLVED ordering only — the subprocess never
                # learns about proposals or overrides. Flags are appended only
                # when non-default, so a run that does not use ordering
                # produces argv identical to pre-PR2.
                if order_strategy != "shuffle":
                    cmd.extend(["--order_strategy", str(order_strategy)])
                if file_order is not None:
                    fo_path = os.path.abspath(
                        os.path.join(self.dirs["configs"], f"file_order_{exp_id}.json")
                    )
                    with open(fo_path, "w") as f:
                        json.dump(list(file_order), f)
                    cmd.extend(["--file_order_json", fo_path])

                # RT2-B: in-subprocess runtime verification (streaming mode
                # only). Remove any stale sidecar from a previous attempt with
                # this exp_id so a pre-launch crash can never resurface old
                # evidence as current.
                if os.path.isfile(rv_sidecar_path):
                    os.remove(rv_sidecar_path)
                cmd.extend(["--runtime_observation_out", rv_sidecar_path])
                if policy_obj is not None:
                    rp_path = os.path.abspath(
                        os.path.join(self.dirs["configs"], f"runtime_policy_{exp_id}.json")
                    )
                    with open(rp_path, "w") as f:
                        json.dump(policy_obj.model_dump(), f)
                    cmd.extend(["--runtime_policy_json", rp_path])

            print(f">>> [Executor] Running training for {exp_id}...")
            _observer = _make_phase_observer(self)
            # B-C4b: one gate before BOTH launch branches.
            _refusal = _admission_refusal(self, phase="training")
            if _refusal is not None:
                return _refusal
            env = _subprocess_env(plugin_dir=self.plugin_dir, loss_dir=self.loss_dir)
            preexec = _limited_preexec(_subprocess_rss_gb("training"))
            if policy_obj is not None and policy_obj.watchdog.enabled and sample_set is not None:
                # RT4 (§4): process-group launch + deadline kill. The
                # deadline tightens mid-flight from the live observation
                # sidecar (component-deadline interface).
                result, kill_info = _run_observed_subprocess(
                    cmd,
                    env=env,
                    preexec_fn=preexec,
                    capture_stdout=not self.progress_bar,
                    deadline_provider=_watchdog_deadline_provider(policy_obj, rv_sidecar_path),
                    grace_seconds=policy_obj.watchdog.grace_seconds,
                    poll_seconds=policy_obj.watchdog.poll_seconds,
                    observer=_observer,
                    label="training",
                )
                if kill_info is not None:
                    # §4 partial-artifact cleanup: the killed attempt's
                    # checkpoint/sentinel/results must not survive.
                    for partial in (
                        os.path.join(self.dirs["models"], f"model_{model_type}_{exp_id}_agent.pth"),
                        os.path.join(self.dirs["models"], f"_OK_{exp_id}"),
                        os.path.join(
                            self.dirs["records"],
                            run_name,
                            f"experiment_results_{model_type}_{exp_id}.json",
                        ),
                    ):
                        if os.path.isfile(partial):
                            os.remove(partial)
                    return {
                        "status": "wall_clock_timeout",
                        "message": (
                            f"watchdog killed training after {kill_info['elapsed_s']}s "
                            f"(deadline {kill_info['deadline_s']}s, "
                            f"source={kill_info['estimate_source']})"
                        ),
                        "watchdog": kill_info,
                        "runtime_verification": _read_runtime_observation_sidecar(rv_sidecar_path),
                    }
            else:
                # B-C2a: same seam as the deadline branch above, so
                # telemetry attaches once. deadline_provider=None keeps
                # subprocess.run's semantics, session behaviour included.
                result, _ = _run_observed_subprocess(
                    cmd,
                    env=env,
                    preexec_fn=preexec,
                    capture_stdout=not self.progress_bar,
                    observer=_observer,
                )
            assert result is not None

            if not self.progress_bar and result.stdout:
                print(f"--- Train Script Output ---\n{result.stdout}")

            # RT2-B: a clean runtime-verification REJECTION exits 0 without a
            # model or _OK_ sentinel — it must be recognized BEFORE the
            # silent-crash sentinel check below, or every rejection would be
            # misclassified as a crash. Distinguishable by the sidecar's
            # admission decision.
            runtime_verification = _read_runtime_observation_sidecar(rv_sidecar_path)
            if (
                runtime_verification is not None
                and (runtime_verification.get("admission") or {}).get("decision") == "rejected"
            ):
                admission_block = runtime_verification.get("admission") or {}
                reason = admission_block.get("reason", "")
                # C9c: an infrastructure-class refusal is NOT a verdict on
                # this candidate — it says the evidence channel is broken.
                # Surfacing it as a candidate rejection would send the chain
                # to the next candidate and straight back into the same
                # failure. Legacy records carry no failure_class and keep the
                # historical (conservative) candidate-rejection path.
                if admission_block.get("failure_class") == "infrastructure":
                    print(f"--- Runtime Evidence-Channel Failure (ABORT) ---\n{reason}")
                    return {
                        "status": "aborted_infrastructure",
                        "message": f"runtime evidence channel failed: {reason}",
                        "runtime_verification": runtime_verification,
                    }
                print(f"--- Runtime Verification Rejected ---\n{reason}")
                return {
                    "status": "rejected_time_risk",
                    "message": f"runtime verification rejected the attempt: {reason}",
                    "runtime_verification": runtime_verification,
                }

            # Phase 6.7 Fix 3 — silent-crash detection. The trainer-side
            # ``_save_with_sentinel`` (Commit 3) writes ``_OK_<exp_id>`` only
            # after ``torch.save`` returns successfully. If the subprocess
            # exited 0 but the sentinel is missing, training crashed somewhere
            # between ``torch.save``'s nominal success and process exit
            # (kernel OOM-kill on the post-save deallocator, GPU watchdog,
            # segfault in CUDA shutdown). Surface as ``error_training`` —
            # the consumer-side preflight in ``inference_single`` would
            # otherwise raise on the missing .pth and the failure would be
            # misclassified as ``error_inference``. The ``error_training:``
            # prefix is the contract the tuner pattern-matches against.
            sentinel_path = os.path.abspath(
                os.path.join(
                    self.dirs["models"],
                    f"_OK_{exp_id}",
                )
            )
            if not os.path.exists(sentinel_path):
                stderr_tail = "\n".join((result.stderr or "").splitlines()[-20:])
                silent_msg = (
                    f"error_training: subprocess returned 0 but no _OK_ "
                    f"sentinel for exp_id={exp_id} "
                    f"(expected {sentinel_path}).\n"
                    f"--- stderr tail (last 20 lines) ---\n{stderr_tail}"
                )
                print(f"--- Train Silent Crash ---\n{silent_msg}")
                return {
                    "status": "error",
                    "message": silent_msg,
                    "runtime_verification": runtime_verification,
                }

            # Read the training-result JSON written by train_engine_sandbox.py
            # so the caller gets final_loss / loss_history / model_params.
            train_json_path = os.path.abspath(
                os.path.join(
                    self.dirs["records"],
                    run_name,
                    f"experiment_results_{model_type}_{exp_id}.json",
                )
            )
            results = {}
            if os.path.isfile(train_json_path):
                with open(train_json_path) as f:
                    results = json.load(f)
            return {
                "status": "success",
                "message": "Training finished.",
                "results": results,
                "runtime_verification": runtime_verification,
            }

        except ScopeViolationError as e:
            # Before subprocess launch — no file I/O happened. Must precede
            # the generic handler (ScopeViolationError is a ValueError).
            return _scope_violation_result(e)
        except subprocess.CalledProcessError as e:
            error_msg = _format_subprocess_error(e, "Train")
            print(f"--- Train Script Error ---\n{error_msg}")
            status = "oom_host_ram" if _is_oom_failure(e) else "error"
            # A crashed subprocess may still have staged partial observation
            # evidence (setup timing, provenance) — attach it (§6.2).
            return _with_failure_attribution(
                _with_gpu_evidence(
                    {
                        "status": status,
                        "message": error_msg,
                        "runtime_verification": _read_runtime_observation_sidecar(rv_sidecar_path),
                    },
                    _observer,
                ),
                e,
                _observer,
            )
        except Exception as e:
            print(f"!!! [Executor Internal Error] !!!: {e!s}")
            return {"status": "error", "message": str(e)}

    def _validate_model_and_loss(self, model_type: str, m_cfg: dict, l_cfg: dict):
        """Validate model and loss configs via Pydantic. Used by inference."""
        if model_type in PLUGIN_CONFIG_REGISTRY:
            validated_m = PLUGIN_CONFIG_REGISTRY[model_type](**m_cfg).model_dump()
            validated_m["model_type"] = model_type
        else:
            config_class = get_config_class(model_type)
            if config_class is None:
                raise ValueError(f"Unknown model_type: {model_type}")
            validated_m = config_class(**m_cfg).model_dump()
        validated_l = LossConfig(**l_cfg).model_dump()
        return validated_m, validated_l

    def execute_inference(
        self,
        exp_id: str,
        run_name: str,
        model_type: str,
        m_cfg: dict,
        l_cfg: dict,
        sample_set: dict | None = None,
        inference_batch: int | None = None,
        runtime_policy: dict | None = None,
    ):
        """Executes the inference physical script.

        Args:
            m_cfg:           Model config dict — validated and written to JSON.
            l_cfg:           Loss config dict — validated and written to JSON.
            sample_set:      Optional SampleSet dict. When provided, written to JSON
                             and passed via --sample_set_json.
            inference_batch: Phase 6.6 A.10 — explicit batch chosen by the
                             pre-flight ``evaluate_vram_skill``. When provided,
                             it is the authoritative runtime batch. When ``None``,
                             fall back to ``inference_batch_for(model_type)``.
                             V21 PR G (Q-G-4) retires the old "A.9 will remove
                             the fallback" plan: the fallback is INTENTIONALLY
                             retained for no-hint callers (``run_comparison.py``
                             baselines, legacy validation scripts), and on the
                             agent path it is unreachable by construction —
                             every route to ``execute_inference`` carries a
                             hint — a contract pinned by the G4 test on the
                             feasible/CPU-mode resource_check returns.
            runtime_policy:  Optional RT2-D runtime policy dict (validated
                             against ``RuntimeControlPolicy``). Trial mode
                             only. The subprocess RESUMES the attempt's
                             observation sidecar (training components
                             preserved — never deleted here) and records
                             the inference component; the updated
                             observation is attached to the result as
                             ``runtime_verification``.
        """
        policy_obj = RuntimeControlPolicy(**runtime_policy) if runtime_policy is not None else None
        validated_m, validated_l = self._validate_model_and_loss(model_type, m_cfg, l_cfg)
        m_path = os.path.abspath(os.path.join(self.dirs["configs"], f"model_config_{exp_id}.json"))
        l_path = os.path.abspath(os.path.join(self.dirs["configs"], f"loss_config_{exp_id}.json"))
        with open(m_path, "w") as f:
            json.dump(validated_m, f)
        with open(l_path, "w") as f:
            json.dump(validated_l, f)
        model_path = os.path.abspath(
            os.path.join(self.dirs["models"], f"model_{model_type}_{exp_id}_agent.pth")
        )
        inf_bs = str(
            inference_batch if inference_batch is not None else inference_batch_for(model_type)
        )

        # Per-iter sidecar path. Iteration scoping comes from ``run_name`` (the
        # configs dir is already iter-keyed); ``exp_id`` makes it unique within
        # an iteration so concurrent rounds don't clobber each other.
        timing_out = os.path.abspath(
            os.path.join(self.dirs["configs"], f"inference_timing_{exp_id}.json")
        )
        # RT2-D: the SAME per-attempt observation sidecar the training
        # subprocess wrote — the inference subprocess resumes it.
        rv_sidecar_path = os.path.abspath(
            os.path.join(self.dirs["configs"], f"runtime_verification_{exp_id}.json")
        )

        cmd = [
            sys.executable,
            "execute_tools/inference_single.py",
            "--mode",
            "agent",
            "-m",
            model_type,
            "--dataset_profile_json",
            self._write_dataset_profile_config(exp_id),
            "--model_cfg",
            m_path,
            "--loss_cfg",
            l_path,
            "--model_path",
            model_path,
            "--exp_id",
            exp_id,
            "--run_name",
            run_name,
            "--output_dir",
            self.base_dir,
            "--inference_batch_size",
            inf_bs,
            "--file_index",
            str(self.file_index),
        ]

        # Step 03 — same transport, same omit-vs-broken distinction as
        # training. Scoring is deliberately NOT given the contract: it feeds
        # no model, so a dtype requirement has no consumer there.
        inference_mio_path = self._write_model_io_config(exp_id)
        if inference_mio_path is not None:
            cmd += ["--model_io_json", inference_mio_path]

        # Validate and write eval SampleSet to JSON. The scope check happens
        # here, before the subprocess try-block — no file I/O has occurred.
        # Result keys mirror this method's error-dict shape (timing fields
        # included).
        #
        # SampleSet boundary contract — the SECOND of exactly two production
        # serialization sites; the contract is stated in full at the first
        # (``execute_training``). This site's only intentional difference is
        # the structured error dict below: a plain ValueError still
        # propagates, as it does there. The emitted bytes must stay
        # byte-identical to the training site's — asserted by
        # tests/unit/execute_tools/test_step02b_b3_boundary_byte_parity.py.
        if sample_set is not None:
            try:
                sample_set = validate_sample_set(sample_set, scope=self.data_scope)
            except ScopeViolationError as e:
                return {
                    **_scope_violation_result(e),
                    "per_file_timings_ms": [],
                    "process_startup_ms": None,
                    "subprocess_wall_ms": None,
                }
            ss_path = os.path.abspath(
                os.path.join(self.dirs["configs"], f"eval_sample_set_{exp_id}.json")
            )
            with open(ss_path, "w") as f:
                json.dump(sample_set, f)
            cmd.extend(["--sample_set_json", ss_path])
            # Trial-mode only — the subprocess emits per-file timings to
            # ``timing_out`` and we read them back below to feed the
            # measurement-driven gate path (see refine_inference_time_estimator.md).
            cmd.extend(["--timing_out_json", timing_out])

            # RT2-D: resume the attempt's runtime observation (training
            # components stay — the sidecar is NEVER deleted here).
            cmd.extend(["--runtime_observation_out", rv_sidecar_path])
            if policy_obj is not None:
                rp_path = os.path.abspath(
                    os.path.join(self.dirs["configs"], f"runtime_policy_{exp_id}.json")
                )
                with open(rp_path, "w") as f:
                    json.dump(policy_obj.model_dump(), f)
                cmd.extend(["--runtime_policy_json", rp_path])

        try:
            print(f">>> [Executor] Running inference for {exp_id}...")
            _observer = _make_phase_observer(self)
            # B-C4b: one gate before BOTH launch branches.
            _refusal = _admission_refusal(self, phase="inference")
            if _refusal is not None:
                return _refusal
            t_subprocess_start = time.perf_counter()
            env = _subprocess_env(plugin_dir=self.plugin_dir, loss_dir=self.loss_dir)
            preexec = _limited_preexec(_subprocess_rss_gb("inference"))
            if policy_obj is not None and policy_obj.watchdog.enabled and sample_set is not None:
                result, kill_info = _run_observed_subprocess(
                    cmd,
                    env=env,
                    preexec_fn=preexec,
                    capture_stdout=not self.progress_bar,
                    deadline_provider=_watchdog_deadline_provider(policy_obj, rv_sidecar_path),
                    grace_seconds=policy_obj.watchdog.grace_seconds,
                    poll_seconds=policy_obj.watchdog.poll_seconds,
                    observer=_observer,
                    label="inference",
                )
                if kill_info is not None:
                    # §4 partial-artifact cleanup — the killed attempt's
                    # denoised outputs (mirrors --cleanup_denoised).
                    import glob as _glob

                    pattern = os.path.join(
                        self.base_dir,
                        self.deliverable_naming.attempt_glob(
                            model_type=model_type, run_name=run_name, exp_id=exp_id
                        ),
                    )
                    for partial in _glob.glob(pattern):
                        os.remove(partial)
                    return {
                        "status": "wall_clock_timeout",
                        "message": (
                            f"watchdog killed inference after {kill_info['elapsed_s']}s "
                            f"(deadline {kill_info['deadline_s']}s, "
                            f"source={kill_info['estimate_source']})"
                        ),
                        "watchdog": kill_info,
                        "per_file_timings_ms": [],
                        "process_startup_ms": None,
                        "subprocess_wall_ms": None,
                        "runtime_verification": _read_runtime_observation_sidecar(rv_sidecar_path),
                    }
            else:
                # B-C2a: same seam as the deadline branch above, so
                # telemetry attaches once. deadline_provider=None keeps
                # subprocess.run's semantics, session behaviour included.
                result, _ = _run_observed_subprocess(
                    cmd,
                    env=env,
                    preexec_fn=preexec,
                    capture_stdout=not self.progress_bar,
                    observer=_observer,
                )
            assert result is not None
            subprocess_wall_ms = (time.perf_counter() - t_subprocess_start) * 1000.0
            if not self.progress_bar and result.stdout:
                print(f"--- Inference Output ---\n{result.stdout}")

            # Parse the trial-mode sidecar if it exists. ``process_startup_ms``
            # is the parent-side residual: subprocess wall-time minus the sum
            # of per-file elapsed times, capturing fixed costs (Python import,
            # CUDA context, ``torch.load``) that aren't billed to any single
            # file. ``max(0, ...)`` defends against tiny clock skew between
            # the two ``perf_counter`` clocks (subprocess vs. parent).
            per_file_timings_ms: list = []
            process_startup_ms = None
            if sample_set is not None and os.path.exists(timing_out):
                try:
                    with open(timing_out) as f:
                        per_file_timings_ms = json.load(f)
                    sum_per_file = sum(float(t.get("elapsed_ms", 0.0)) for t in per_file_timings_ms)
                    process_startup_ms = max(0.0, subprocess_wall_ms - sum_per_file)
                except Exception as exc:
                    print(f"[execute_inference] sidecar parse failed: {exc}")

            return {
                "status": "success",
                "message": "Inference finished.",
                "per_file_timings_ms": per_file_timings_ms,
                "process_startup_ms": process_startup_ms,
                "subprocess_wall_ms": subprocess_wall_ms,
                "runtime_verification": _read_runtime_observation_sidecar(rv_sidecar_path),
            }
        except subprocess.CalledProcessError as e:
            error_msg = _format_subprocess_error(e, "Inference")
            print(f"--- Inference Error ---\n{error_msg}")
            status = "oom_host_ram" if _is_oom_failure(e) else "error"
            return _with_failure_attribution(
                _with_gpu_evidence(
                    {
                        "status": status,
                        "message": error_msg,
                        "per_file_timings_ms": [],
                        "process_startup_ms": None,
                        "subprocess_wall_ms": None,
                        "runtime_verification": _read_runtime_observation_sidecar(rv_sidecar_path),
                    },
                    _observer,
                ),
                e,
                _observer,
            )

    def evaluate_metric(
        self,
        metric: EvaluationMetric,
        sample_set,
        anchor_map: dict,
        s_max: float,
        denoised_filename_fn: Callable,
        **kwargs,
    ) -> MetricResult:
        """PRODUCTION SCORING, through the metric handle (Step 06 C2).

        The tuner's live scoring route. Order is load-bearing and unchanged
        from the pre-Step-06 route where it existed, extended where it did not:

        1. the SampleSet is validated against the run's DataScope (boundary
           invariant — rejection before ANY file I/O, exactly as before);
        2. the metric's SCOREABILITY contract runs over the deliverables the
           scorer would open (``{file_index: path}``, resolved through
           ``denoised_filename_fn`` and this sandbox's ``base_dir`` exactly as
           ``score_vector`` resolves them);
        3. only then does the handle reach the instance's arithmetic — for
           TIDMAD, ``execute_tools.scoring_utils.score_vector`` with the same
           keyword arguments this method has always passed it.

        Args:
            metric:               The run's evaluation metric handle
                                  (``run_metric`` in the tuner's run scope).
            sample_set:           SampleSet dict (file_index → segment list).
            anchor_map:           The ``"anchors"`` dict from segment_anchors.json.
            s_max:                Global max CH2 SNR from the anchor map.
            denoised_filename_fn: Callable (file_index) → denoised filename.
            **kwargs:             Forwarded to the instance's arithmetic
                                  (for TIDMAD: scoring_utils.score_vector —
                                  parallel, num_workers, profile, …).

        Returns:
            The metric's result: identity, direction, scalar and (for TIDMAD)
            the per-file vector as ``per_sample``.

        Raises:
            ValueError: On an invalid or out-of-scope ``sample_set``
                (``ScopeViolationError``, a ValueError subclass, for scope
                violations) — this seam's established exception contract,
                unlike the error-dict contract of ``execute_training`` /
                ``execute_inference``.
            NotScoreableError: The deliverables failed the metric's
                scoreability contract. Carries the structured
                ``NotScoreableResult``; no scorer arithmetic ran. Raised
                rather than returned because the tuner's scoring ``try`` block
                is the round-outcome path for every scoring-phase failure
                (V8 Domain 2a) and ``run()`` cannot grow a branch.
        """
        sample_set = validate_sample_set(sample_set, scope=self.data_scope)
        deliverables = {
            int(file_index): os.path.join(self.base_dir, denoised_filename_fn(file_index))
            for file_index in sample_set
        }
        # The profile ``score_vector`` would otherwise resolve ambiently,
        # threaded explicitly (design §19 C2) — the same object, one seam.
        kwargs.setdefault("profile", resolve_dataset_profile())
        outcome = metric.evaluate(
            deliverables,
            data_dir=self.base_dir,
            sample_set=sample_set,
            anchor_map=anchor_map,
            s_max=s_max,
            denoised_filename_fn=denoised_filename_fn,
            raw_data_dir=self.dirs["data"],
            **kwargs,
        )
        if isinstance(outcome, NotScoreableResult):
            raise NotScoreableError(outcome)
        return outcome

    def score_vector(
        self,
        sample_set,
        anchor_map: dict,
        s_max: float,
        denoised_filename_fn: Callable,
        metric: EvaluationMetric | None = None,
        **kwargs,
    ) -> tuple:
        """Anchor-normalised multi-file scoring — the pre-Step-06 2-tuple seam.

        Kept for callers that predate the metric handle: the same arguments,
        the same ``(file_vector, final_scalar_score)`` return. Since Step 06
        it is a thin wrapper over :meth:`evaluate_metric`; ``metric=None``
        (Regime A) resolves the TIDMAD instance from the run's profile, so a
        legacy caller obtains exactly today's values through the handle.

        Raises:
            ValueError: as :meth:`evaluate_metric`.
            NotScoreableError: as :meth:`evaluate_metric` — a deliverable the
                contract refuses is a structured refusal, not an incidental
                error from inside the scorer worker.
        """
        handle = metric if metric is not None else derive_tidmad_metric(resolve_dataset_profile())
        result = self.evaluate_metric(
            handle,
            sample_set,
            anchor_map,
            s_max,
            denoised_filename_fn,
            **kwargs,
        )
        return result.per_sample, result.scalar

    def execute_scoring(
        self, exp_id: str, run_name: str, model_type: str, m_cfg: dict, t_cfg: dict, l_cfg: dict
    ):
        """Calculates score and returns results to Skill layer."""
        result_dir = os.path.join(self.dirs["records"], run_name)
        _ensure_dir(result_dir)

        train_json_path = os.path.abspath(
            os.path.join(result_dir, f"experiment_results_{model_type}_{exp_id}.json")
        )
        score_json_path = os.path.abspath(
            os.path.join(result_dir, f"score_results_{model_type}_{exp_id}.json")
        )

        try:
            # Pre-create the scoring JSON so the script can write to it
            with open(score_json_path, "w") as f:
                json.dump({}, f)

            print(f">>> [Executor] Running scoring for {exp_id}...")
            subprocess.run(
                [
                    sys.executable,
                    "execute_tools/denoising_score_single.py",
                    "--mode",
                    "agent",
                    "-m",
                    model_type,
                    "--dataset_profile_json",
                    self._write_dataset_profile_config(exp_id),
                    "--exp_id",
                    exp_id,
                    "--run_name",
                    run_name,
                    "--output_json",
                    score_json_path,
                    "--data_dir",
                    self.base_dir,
                    "--file_index",
                    str(self.file_index),
                ],
                check=True,
                stdout=None if self.progress_bar else subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=os.getcwd(),
                env=_subprocess_env(plugin_dir=self.plugin_dir, loss_dir=self.loss_dir),
                preexec_fn=_limited_preexec(_subprocess_rss_gb("scoring")),
            )

            # Merge training results (loss history) with scoring results
            results = {}
            if os.path.exists(train_json_path):
                with open(train_json_path) as f:
                    results.update(json.load(f))
            with open(score_json_path) as f:
                results.update(json.load(f))

            if os.path.exists(score_json_path):
                os.remove(score_json_path)

            # Note: We NO LONGER call self.recorder.save_record(record) here.
            # We return results to ml_hyperparameter_tune_agent.py, which adds LLM memory and then saves.
            return {"status": "success", "results": results}
        except subprocess.CalledProcessError as e:
            error_msg = _format_subprocess_error(e, "Scoring")
            print(f"--- Scoring Script Error ---\n{error_msg}")
            status = "oom_host_ram" if _is_oom_failure(e) else "error"
            return {"status": status, "message": error_msg}
        except Exception as e:
            print(f"--- Scoring Internal Error ---\n{e!s}")
            return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# StubSandbox — synthetic, deterministic sandbox for 0-cost smoke runs
# ---------------------------------------------------------------------------
#
# Subclasses ``TidmadSandbox`` so it inherits the recorder/workspace plumbing
# and stays a drop-in replacement at the chain orchestration layer. Overrides
# the four execution methods (``execute_training`` / ``execute_inference`` /
# ``execute_scoring`` / ``save_record``) to skip every subprocess launch and
# synthesise pydantic-valid results from a single run-id-seeded RNG.
#
# Determinism contract: ``random.Random(self._run_id)`` — passing the string
# directly uses CPython's stable SHA-512-based seeding path, so the same
# ``run_id`` yields the same number stream on every fresh interpreter.
# ``random.Random(hash(run_id))`` would NOT be stable: ``hash()`` on strings
# is randomized per-process via ``PYTHONHASHSEED``.
class StubSandbox(TidmadSandbox):
    """Stateless, deterministic sandbox for pseudo-mode smoke runs.

    The chain orchestration layer (``ml_hyperparameter_tune_agent``) treats
    a sandbox as a black box that returns ``status: success`` plus a results
    dict shaped like the production trainer / inference / scorer output.
    StubSandbox honours that contract without launching any subprocesses,
    writing any GPU artefacts, or touching the real data directory.

    Per-method synthesis:
        * ``execute_training``: ``final_loss`` ∈ [0.5, 5.0],
          ``loss_history`` = [final_loss], ``model_params`` ∈ [1e3, 1e8].
        * ``execute_inference``: empty per-file timing list, fixed 10 ms
          ``process_startup_ms`` / ``subprocess_wall_ms``.
        * ``execute_scoring``: merges cached training results (mirroring the
          prod merge order in ``TidmadSandbox.execute_scoring``) and adds
          ``denoising_score`` ∈ [-3.0, -2.0], a length-9 ``file_vector``,
          ``is_degenerate=False``, ``failure_reason=None``.
        * ``save_record``: stamps ``_pseudo_origin = "stub_sandbox"`` on the
          record dict (audit trail to distinguish synthetic smoke results
          from real measurements), then delegates to the parent recorder
          for on-disk persistence and mirrors the record into
          ``self.saved_records`` for unit-test inspection.
    """

    def __init__(
        self,
        metadata_source: str = "local",
        mongodb_uri: str | None = None,
        run_name: str = "test_run",
        workspace: str = "./siderius_workspace",
        progress_bar: bool = False,
        file_index: int = 6,
        run_id: str | None = None,
        data_scope: DataScope | None = None,
        device_identity: Any = None,
        deliverable_naming: DeliverableNaming | None = None,
    ):
        # `deliverable_naming` mirrors the parent for exactly the reason given
        # below for `device_identity`: the tuner resolves the run's naming once
        # and passes it to whatever sandbox the factory returns, so a stub that
        # does not accept it makes pseudo mode unusable through the tuner.
        #
        # `device_identity` mirrors the parent (V20 PR B, #153). The tuner
        # resolves the identity ONCE at the orchestration boundary and passes
        # it to whatever sandbox the factory returns, so a stub that does not
        # accept it makes pseudo-training unusable through the tuner —
        # `TypeError: StubSandbox.__init__() got an unexpected keyword
        # argument 'device_identity'`. It is forwarded rather than dropped so
        # a pseudo run describes the same device as a real one.
        super().__init__(
            metadata_source=metadata_source,
            mongodb_uri=mongodb_uri,
            run_name=run_name,
            workspace=workspace,
            progress_bar=progress_bar,
            file_index=file_index,
            data_scope=data_scope,
            device_identity=device_identity,
            deliverable_naming=deliverable_naming,
        )
        self._run_id: str = run_id or run_name
        self._rng = random.Random(self._run_id)
        self.saved_records: list[dict[str, Any]] = []
        # Cache training results so ``execute_scoring`` can merge them like
        # prod does (the prod path reads ``experiment_results_*.json`` from
        # disk; the stub keeps an in-memory analogue keyed by ``exp_id``).
        self._train_results_cache: dict[str, dict[str, Any]] = {}

    def set_run_context(self, run_id: str) -> None:
        """Re-seed the RNG with a new run_id.

        Mirrors ``StubLLMBridge.set_run_context`` so the chain runner can
        bind both the bridge and the sandbox to the same ``run_id`` and get
        consistent synthetic outputs across the two layers.
        """
        self._run_id = run_id
        self._rng = random.Random(self._run_id)

    def execute_training(
        self,
        exp_id: str,
        run_name: str,
        model_type: str,
        m_cfg: dict,
        t_cfg: dict,
        l_cfg: dict,
        sample_set: dict | None = None,
        train_portion: float | None = None,
        train_base_seed: int | None = None,
        runtime_policy: dict | None = None,
        order_strategy: str = "shuffle",
        file_order: list[int] | None = None,
        eval_sample_set: dict | None = None,
    ) -> dict[str, Any]:
        """Synthesise a successful training result. No subprocess launch.

        DataScope parity with the production executor: pseudo-mode tests
        must exercise the boundary invariant, not bypass it.
        ``runtime_policy`` is accepted for signature parity (RT2-B); the
        stub never runs verification, so the result carries
        ``runtime_verification=None`` — the explicit-absence shape
        downstream consumers already fail closed on (§7.3).
        ``order_strategy`` / ``file_order`` are likewise accepted for
        signature parity (V19 PR 2) — the stub trains nothing, so there is
        no visitation order to apply, but a pseudo run must not diverge
        from production at the call boundary. ``eval_sample_set`` (Step
        07a) is accepted and scope-validated exactly like the executor's,
        so a pseudo run exercises the same boundary as production.
        """
        if sample_set is not None:
            try:
                validate_sample_set(sample_set, scope=self.data_scope)
                if eval_sample_set is not None:
                    validate_sample_set(eval_sample_set, scope=self.data_scope)
            except ScopeViolationError as e:
                return _scope_violation_result(e)
        # Step 07a (OD-S7-4): a plausible MULTI-EPOCH train + validation
        # history so pseudo runs and 07b's Gate 1 exercise a real diagnosis.
        # Deterministic from the stub's seeded rng: 5 strictly decreasing
        # training observations ending at `final_loss`; validation
        # decreasing for four epochs then rising slightly (a best-epoch that
        # is not the last). R3 is emitted ONLY when an eval SampleSet was
        # supplied — exactly the production trainer's expected/absent rule.
        final_loss = self._rng.uniform(0.5, 5.0)
        drops = sorted(self._rng.uniform(0.05, 0.6) for _ in range(4))
        loss_history = [final_loss]
        for d in drops:
            loss_history.insert(0, loss_history[0] * (1.0 + d))
        stub_loss_cfg = LossConfig(**l_cfg)
        validation_history = None
        validation_seconds = None
        validation_rows = None
        if eval_sample_set is not None:
            gap = self._rng.uniform(0.01, 0.15)
            validation_history = [v * (1.0 + gap) for v in loss_history]
            validation_history[-1] = validation_history[-2] * (1.0 + self._rng.uniform(0.01, 0.05))
            validation_seconds = [round(self._rng.uniform(0.05, 0.5), 3) for _ in loss_history]
            validation_rows = sum(len(v) for v in eval_sample_set.values())
        history = TrainingHistory(
            objective_kind=stub_loss_cfg.loss_type,
            objective_config_fingerprint=objective_config_fingerprint(stub_loss_cfg),
            objective_reduction=stub_loss_cfg.reduction,
            comparability=stamp_comparability(stub_loss_cfg)[0],
            comparability_reason=stamp_comparability(stub_loss_cfg)[1],
            epochs_planned=len(loss_history),
            epochs_completed=len(loss_history),
            train_objective=loss_history,
            validation_objective=validation_history,
            validation_requested_samples=validation_rows,
            validation_samples=validation_rows,
            validation_seconds=validation_seconds,
        )
        results = {
            "final_loss": final_loss,
            "loss_history": loss_history,
            "model_params": self._rng.randint(1_000, 100_000_000),
            TRAINING_HISTORY_KEY: history.model_dump(),
        }
        self._train_results_cache[exp_id] = results
        return {
            "status": "success",
            "message": "stub_training_ok",
            "results": results,
            "runtime_verification": None,
        }

    def execute_inference(
        self,
        exp_id: str,
        run_name: str,
        model_type: str,
        m_cfg: dict,
        l_cfg: dict,
        sample_set: dict | None = None,
        inference_batch: int | None = None,
        runtime_policy: dict | None = None,
    ) -> dict[str, Any]:
        """Synthesise a successful inference result. No subprocess launch.

        DataScope parity with the production executor (error-dict shape
        mirrors ``TidmadSandbox.execute_inference``, timing fields included).
        ``runtime_policy`` accepted for RT2-D signature parity;
        ``runtime_verification=None`` is the explicit-absence shape.
        """
        if sample_set is not None:
            try:
                validate_sample_set(sample_set, scope=self.data_scope)
            except ScopeViolationError as e:
                return {
                    **_scope_violation_result(e),
                    "per_file_timings_ms": [],
                    "process_startup_ms": None,
                    "subprocess_wall_ms": None,
                }
        return {
            "status": "success",
            "message": "stub_inference_ok",
            "per_file_timings_ms": [],
            "process_startup_ms": 10.0,
            "subprocess_wall_ms": 10.0,
            "runtime_verification": None,
        }

    def execute_scoring(
        self,
        exp_id: str,
        run_name: str,
        model_type: str,
        m_cfg: dict,
        t_cfg: dict,
        l_cfg: dict,
    ) -> dict[str, Any]:
        """Synthesise scoring + merge cached training results.

        Mirrors the prod merge order in ``TidmadSandbox.execute_scoring``:
        training keys first, then scoring keys (so ``final_loss`` /
        ``loss_history`` / ``model_params`` from the cached trainer output
        appear alongside the synthetic ``denoising_score`` etc.).
        """
        results: dict[str, Any] = {}
        results.update(self._train_results_cache.get(exp_id, {}))
        results["denoising_score"] = self._rng.uniform(-3.0, -2.0)
        results["file_vector"] = [self._rng.uniform(-3.0, -2.0) for _ in range(9)]
        results["is_degenerate"] = False
        results["failure_reason"] = None
        return {"status": "success", "results": results}

    def evaluate_metric(
        self,
        metric: EvaluationMetric,
        sample_set,
        anchor_map: dict,
        s_max: float,
        denoised_filename_fn,
        **kwargs,
    ) -> MetricResult:
        """The pseudo-mode mirror of the production metric route (Step 06 C2).

        No deliverable exists under ``--is_pseudo_training``, so no
        scoreability contract can run and no arithmetic can be reached; this
        synthesises the same 2-tuple :meth:`score_vector` has always produced
        and returns it under the run's REAL metric identity/direction — the
        handle's own declaration, not an invention — so the record payload
        the tuner writes has the production shape. Values are synthetic
        exactly as ``denoising_score`` / ``file_vector`` on every pseudo
        record already are.
        """
        file_vector, final_scalar = self.score_vector(
            sample_set, anchor_map, s_max, denoised_filename_fn, **kwargs
        )
        return MetricResult(
            metric_id=metric.spec.id,
            direction=metric.spec.direction,
            scalar=final_scalar,
            per_sample=file_vector,
            references_used=(),
        )

    def score_vector(
        self,
        sample_set,
        anchor_map: dict,
        s_max: float,
        denoised_filename_fn,
        **kwargs,
    ) -> tuple:
        """Synthesise the anchor-normalised scoring 2-tuple. No h5 read.

        Production ``TidmadSandbox.score_vector`` delegates to
        ``execute_tools.scoring_utils.score_vector``, which opens the
        ``abra_validation_denoised_*.h5`` artefacts produced by inference.
        Under ``--is_pseudo_training`` those artefacts never get written
        (inference is stubbed), so calling the inherited implementation
        crashes with ``FileNotFoundError`` mid-scoring. This override
        mirrors the synthesis contract of ``execute_scoring`` — same
        ``denoising_score`` ∈ [-3.0, -2.0] band, length-9 ``file_vector``
        — and returns them in the 2-tuple order the tuner unpacks at
        ``ml_hyperparameter_tune_agent.py`` (``score_vector`` call site).

        Args mirror the production signature for swap-in compatibility;
        ``**kwargs`` remains for backward compatibility with any callers
        still passing removed kwargs like ``reference_file_vector`` (they
        are silently swallowed). No anchor lookup, no parallel workers,
        no disk I/O.

        Health-check separation (commit-5a): the fixed
        ``(is_degenerate=False, failure_reason=None)`` pair that this
        stub previously appended was removed together with
        ``score_vector``'s health-check logic. See
        ``docs/design/pluggable_health_checks.md`` §14 Option A.

        Returns:
            (file_vector, final_scalar)

        Raises:
            ValueError: On an invalid or out-of-scope ``sample_set`` —
                DataScope parity with the production ``score_vector``
                exception contract.
        """
        validate_sample_set(sample_set, scope=self.data_scope)
        file_vector = [self._rng.uniform(-3.0, -2.0) for _ in range(9)]
        final_scalar = self._rng.uniform(-3.0, -2.0)
        return file_vector, final_scalar

    def save_record(self, record: dict[str, Any]) -> None:
        """Stamp ``_pseudo_origin`` audit marker, persist via parent, mirror in-memory.

        ``ExperimentRecord`` (Pydantic v2 default) silently ignores extra
        keys during validation, so the upstream
        ``ExperimentRecord.model_validate(record)`` call in
        ``ml_hyperparameter_tune_agent`` accepts the marker. The raw dict
        (with the marker preserved) is what gets json-dumped on disk by
        ``LocalRecorder.save_record``, so operators can grep the records
        directory for synthetic results.
        """
        record["_pseudo_origin"] = "stub_sandbox"
        super().save_record(record)
        self.saved_records.append(record)
