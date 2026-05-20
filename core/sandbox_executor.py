# core/sandbox_executor.py
import os
import re
import sys
import json
import time
import random
import subprocess
import datetime
from typing import Callable, Dict, Any, List, Optional
from ml_models.models_format_sandbox import get_config_class, TrainConfig, LossConfig, ExperimentConfig, PLUGIN_CONFIG_REGISTRY
from execute_tools.scoring_utils import coerce_nonfinite_to_none, validate_sample_set
from execute_tools.data_paths import TIDMAD_DATA_DIR
from core.inference_defaults import inference_batch_for


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

_ROLE_DEFAULT_RSS_GB = {
    "training":  40,   # CUDA — 20 (static) + 16 (working VRAM) + 4 (safety)
    "inference": 40,   # CUDA — same breakdown as training
    "scoring":   24,   # CPU-only — kept at original value, protects the 2026-04-20 incident path
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


def _limited_preexec(gb: int) -> Optional[Callable[[], None]]:
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
    limit_bytes = gb * (1024 ** 3)

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
    if e.stderr and _MEMORY_ERROR_RE.search(e.stderr):
        return True
    return False


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


def _subprocess_env(plugin_dir: Optional[str] = None) -> dict:
    """
    Returns an env dict for subprocesses with ml_models and execute_tools
    added to PYTHONPATH, so flat imports in those scripts resolve correctly
    regardless of the working directory.

    Args:
        plugin_dir: Optional run-scoped plugin directory. When provided, the
            returned env sets ``SIDERIUS_PLUGIN_DIRS=<plugin_dir>`` so the
            training/inference/scoring subprocess scans only this directory
            instead of the legacy global ``agent_generated/models/``. See
            docs/run_scoped_plugins.md (Phase 2). When ``None``, the env var
            is not set and the subprocess falls back to the legacy global
            dir — this preserves back-compat for any caller outside the
            tuner sandbox flow.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    extra_paths = [
        project_root,
        os.path.join(project_root, "ml_models"),
        os.path.join(project_root, "execute_tools"),
    ]
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(extra_paths + ([existing] if existing else []))
    if plugin_dir:
        env["SIDERIUS_PLUGIN_DIRS"] = plugin_dir
    return env

# --- Storage Strategies ---

class BaseRecorder:
    """Base class for experiment recording."""
    def save_record(self, record: Dict[str, Any]):
        raise NotImplementedError

    def get_summary(self) -> list:
        raise NotImplementedError

class LocalRecorder(BaseRecorder):
    """File-based recording for persistent agent memory."""
    def __init__(self, record_dir: str, summary_file: str, run_name: str):
        self.summary_file = summary_file
        self.record_dir = os.path.join(record_dir, run_name)
        _ensure_dir(self.record_dir)

    def save_record(self, record: Dict[str, Any]):
        exp_id = record["exp_id"]

        # Coerce float('-inf') no-signal sentinels to JSON null so the on-disk
        # record stays browser-safe (RFC-8259 doesn't allow Infinity / -Infinity).
        safe_record = coerce_nonfinite_to_none(record)

        # every detail json should stay in the run_name folder
        detail_path = os.path.join(self.record_dir, f"{exp_id}.json")
        with open(detail_path, 'w', encoding='utf-8') as f:
            json.dump(safe_record, f, indent=4, ensure_ascii=False)

        summary = self.get_summary()
        existing_idx = next((i for i, item in enumerate(summary) if item.get("exp_id") == exp_id), None)

        if existing_idx is not None:
            summary[existing_idx] = safe_record
        else:
            summary.append(safe_record)

        with open(self.summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=4, ensure_ascii=False)

    def get_summary(self) -> list:
        if os.path.exists(self.summary_file):
            try:
                with open(self.summary_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return []
        return []

class MongoRecorder(BaseRecorder):
    """MongoDB-based recording for robust development."""
    def __init__(self, uri: str, db_name: str):
        from pymongo import MongoClient
        self.client = MongoClient(uri)
        self.db = self.client[db_name]
        self.collection = self.db["experiments"]

    def save_record(self, record: Dict[str, Any]):
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
    except PermissionError:
        raise RuntimeError(
            f"[Sandbox] Permission denied: cannot create directory '{path}'. "
            "Check that you have write access to the workspace."
        )
    except OSError as e:
        raise RuntimeError(
            f"[Sandbox] Failed to create directory '{path}': {e}. "
            "Check that the path is valid and the filesystem is accessible."
        )
    if not os.access(path, os.W_OK):
        raise RuntimeError(
            f"[Sandbox] Directory '{path}' exists but is not writable. "
            "Check filesystem permissions."
        )

class TidmadSandbox:
    def __init__(self, metadata_source: str = "local", mongodb_uri: Optional[str] = None,
                 run_name: str = "test_run", workspace: str = "./siderius_workspace",
                 progress_bar: bool = False, file_index: int = 6):
        self.base_dir = os.path.abspath(workspace)
        self.dirs = {
            "configs": os.path.join(self.base_dir, "configs", run_name),
            "models": os.path.join(self.base_dir, "cached_models"),
            "records": os.path.join(self.base_dir, "records"),
            "data": _tidmad_data_dir()
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
                self.run_name
            )

    def save_record(self, record: Dict[str, Any]):
        """Direct access for ml_hyperparameter_tune_agent to save finalized research records."""
        self.recorder.save_record(record)

    def get_summary(self) -> list:
        """Retrieves experiment history for the Agent's planning phase."""
        return self.recorder.get_summary()

    def _validate_configs(self, model_type: str, m_cfg: Dict, t_cfg: Dict, l_cfg: Dict, exp_id: str, run_name: str):
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
                validated_l = LossConfig(**l_cfg).model_dump()
                return validated_m, validated_t, validated_l
            except Exception as e:
                raise ValueError(f"Plugin Experiment Configuration Rejected: {str(e)}")

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
            raise ValueError(f"Experiment Configuration Rejected: {str(e)}")

    def execute_training(self, exp_id: str, run_name: str, model_type: str, m_cfg: Dict, t_cfg: Dict, l_cfg: Dict,
                         sample_set: Optional[Dict] = None, train_portion: Optional[float] = None,
                         train_base_seed: Optional[int] = None):
        """Executes the training physical script.

        Args:
            sample_set:      Optional SampleSet dict — the data scope. When provided,
                             written to JSON and passed via --sample_set_json.
            train_portion:   Fraction of the scope to subsample per epoch for training.
                             Passed via --train_portion.
            train_base_seed: Base seed for per-epoch subsampling reproducibility.
                             Passed via --train_base_seed.
        """
        try:
            vm, vt, vl = self._validate_configs(model_type, m_cfg, t_cfg, l_cfg, exp_id, run_name)

            paths = {
                "m": os.path.abspath(os.path.join(self.dirs["configs"], f"model_config_{exp_id}.json")),
                "t": os.path.abspath(os.path.join(self.dirs["configs"], f"train_config_{exp_id}.json")),
                "l": os.path.abspath(os.path.join(self.dirs["configs"], f"loss_config_{exp_id}.json"))
            }
            for k, v in zip(["m", "t", "l"], [vm, vt, vl]):
                with open(paths[k], 'w') as f: json.dump(v, f)

            cmd = [sys.executable, "execute_tools/train_engine_sandbox.py",
                    "--model_cfg", paths["m"],
                    "--train_cfg", paths["t"],
                    "--loss_cfg", paths["l"],
                    "--exp_id", exp_id,
                    "--run_name", run_name,
                    "--sandbox_dir", self.base_dir,
                    "--file_index", str(self.file_index)]

            # Validate and write data scope SampleSet to JSON
            if sample_set is not None:
                sample_set = validate_sample_set(sample_set)
                ss_path = os.path.abspath(os.path.join(self.dirs["configs"], f"train_sample_set_{exp_id}.json"))
                with open(ss_path, 'w') as f:
                    json.dump(sample_set, f)
                cmd.extend(["--sample_set_json", ss_path])
                if train_portion is not None:
                    cmd.extend(["--train_portion", str(train_portion)])
                if train_base_seed is not None:
                    cmd.extend(["--train_base_seed", str(train_base_seed)])

            print(f">>> [Executor] Running training for {exp_id}...")
            result = subprocess.run(
                    cmd,
                    check=True,
                    stdout=None if self.progress_bar else subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=os.getcwd(),
                    env=_subprocess_env(plugin_dir=self.plugin_dir),
                    preexec_fn=_limited_preexec(_subprocess_rss_gb("training")),
                )

            if not self.progress_bar and result.stdout:
                print(f"--- Train Script Output ---\n{result.stdout}")

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
            sentinel_path = os.path.abspath(os.path.join(
                self.dirs["models"], f"_OK_{exp_id}",
            ))
            if not os.path.exists(sentinel_path):
                stderr_tail = "\n".join(
                    (result.stderr or "").splitlines()[-20:]
                )
                silent_msg = (
                    f"error_training: subprocess returned 0 but no _OK_ "
                    f"sentinel for exp_id={exp_id} "
                    f"(expected {sentinel_path}).\n"
                    f"--- stderr tail (last 20 lines) ---\n{stderr_tail}"
                )
                print(f"--- Train Silent Crash ---\n{silent_msg}")
                return {"status": "error", "message": silent_msg}

            # Read the training-result JSON written by train_engine_sandbox.py
            # so the caller gets final_loss / loss_history / model_params.
            train_json_path = os.path.abspath(os.path.join(
                self.dirs["records"], run_name,
                f"experiment_results_{model_type}_{exp_id}.json",
            ))
            results = {}
            if os.path.isfile(train_json_path):
                with open(train_json_path, "r") as f:
                    results = json.load(f)
            return {"status": "success", "message": "Training finished.", "results": results}

        except subprocess.CalledProcessError as e:
            error_msg = _format_subprocess_error(e, "Train")
            print(f"--- Train Script Error ---\n{error_msg}")
            status = "oom_host_ram" if _is_oom_failure(e) else "error"
            return {"status": status, "message": error_msg}
        except Exception as e:
            print(f"!!! [Executor Internal Error] !!!: {str(e)}") 
            return {"status": "error", "message": str(e)}

    def _validate_model_and_loss(self, model_type: str, m_cfg: Dict, l_cfg: Dict):
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

    def execute_inference(self, exp_id: str, run_name: str, model_type: str, m_cfg: Dict, l_cfg: Dict,
                          sample_set: Optional[Dict] = None,
                          inference_batch: Optional[int] = None):
        """Executes the inference physical script.

        Args:
            m_cfg:           Model config dict — validated and written to JSON.
            l_cfg:           Loss config dict — validated and written to JSON.
            sample_set:      Optional SampleSet dict. When provided, written to JSON
                             and passed via --sample_set_json.
            inference_batch: Phase 6.6 A.10 — explicit batch chosen by the
                             pre-flight ``evaluate_vram_skill``. When provided,
                             it is the authoritative runtime batch. When ``None``
                             (legacy path and during the A.6–A.11 landing window),
                             fall back to ``inference_batch_for(model_type)`` so
                             callers not yet wired through the tuner keep running.
                             A.9 will remove the fallback once every caller has
                             been migrated.
        """
        validated_m, validated_l = self._validate_model_and_loss(model_type, m_cfg, l_cfg)
        m_path = os.path.abspath(os.path.join(self.dirs["configs"], f"model_config_{exp_id}.json"))
        l_path = os.path.abspath(os.path.join(self.dirs["configs"], f"loss_config_{exp_id}.json"))
        with open(m_path, 'w') as f: json.dump(validated_m, f)
        with open(l_path, 'w') as f: json.dump(validated_l, f)
        model_path = os.path.abspath(os.path.join(self.dirs["models"], f"model_{model_type}_{exp_id}_agent.pth"))
        inf_bs = str(
            inference_batch if inference_batch is not None
            else inference_batch_for(model_type)
        )

        # Per-iter sidecar path. Iteration scoping comes from ``run_name`` (the
        # configs dir is already iter-keyed); ``exp_id`` makes it unique within
        # an iteration so concurrent rounds don't clobber each other.
        timing_out = os.path.abspath(
            os.path.join(self.dirs["configs"], f"inference_timing_{exp_id}.json")
        )

        cmd = [sys.executable, "execute_tools/inference_single.py", "--mode", "agent", "-m", model_type,
               "--model_cfg", m_path, "--loss_cfg", l_path,
               "--model_path", model_path, "--exp_id", exp_id, "--run_name", run_name,
               "--output_dir", self.base_dir, "--inference_batch_size", inf_bs,
               "--file_index", str(self.file_index)]

        # Validate and write eval SampleSet to JSON
        if sample_set is not None:
            sample_set = validate_sample_set(sample_set)
            ss_path = os.path.abspath(os.path.join(self.dirs["configs"], f"eval_sample_set_{exp_id}.json"))
            with open(ss_path, 'w') as f:
                json.dump(sample_set, f)
            cmd.extend(["--sample_set_json", ss_path])
            # Trial-mode only — the subprocess emits per-file timings to
            # ``timing_out`` and we read them back below to feed the
            # measurement-driven gate path (see refine_inference_time_estimator.md).
            cmd.extend(["--timing_out_json", timing_out])

        try:
            print(f">>> [Executor] Running inference for {exp_id}...")
            t_subprocess_start = time.perf_counter()
            result = subprocess.run(
                cmd,
                check=True,
                stdout=None if self.progress_bar else subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True, cwd=os.getcwd(),
                env=_subprocess_env(plugin_dir=self.plugin_dir),
                preexec_fn=_limited_preexec(_subprocess_rss_gb("inference")),
            )
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
                    sum_per_file = sum(
                        float(t.get("elapsed_ms", 0.0)) for t in per_file_timings_ms
                    )
                    process_startup_ms = max(0.0, subprocess_wall_ms - sum_per_file)
                except Exception as exc:
                    print(f"[execute_inference] sidecar parse failed: {exc}")

            return {
                "status": "success",
                "message": "Inference finished.",
                "per_file_timings_ms": per_file_timings_ms,
                "process_startup_ms": process_startup_ms,
                "subprocess_wall_ms": subprocess_wall_ms,
            }
        except subprocess.CalledProcessError as e:
            error_msg = _format_subprocess_error(e, "Inference")
            print(f"--- Inference Error ---\n{error_msg}")
            status = "oom_host_ram" if _is_oom_failure(e) else "error"
            return {
                "status": status,
                "message": error_msg,
                "per_file_timings_ms": [],
                "process_startup_ms": None,
                "subprocess_wall_ms": None,
            }

    def score_vector(self, sample_set, anchor_map: dict, s_max: float,
                     denoised_filename_fn: callable, **kwargs) -> tuple:
        """Anchor-normalised multi-file scoring. Delegates to execute_tools.scoring_utils.score_vector.

        Wraps the module-level function so that the agent's scoring path goes
        through the sandbox — making it injectable in tests just like
        execute_training / execute_inference / execute_scoring.

        Args:
            sample_set:           SampleSet dict (file_index → segment list).
            anchor_map:           The ``"anchors"`` dict from segment_anchors.json.
            s_max:                Global max CH2 SNR from the anchor map.
            denoised_filename_fn: Callable (file_index) → denoised filename.
            **kwargs:             Forwarded to scoring_utils.score_vector
                                  (parallel, num_workers, raw_data_dir, …).

        Returns:
            (file_vector, final_scalar_score)
        """
        from execute_tools.scoring_utils import score_vector as _score_vector
        return _score_vector(
            data_dir=self.base_dir,
            sample_set=sample_set,
            anchor_map=anchor_map,
            s_max=s_max,
            denoised_filename_fn=denoised_filename_fn,
            raw_data_dir=self.dirs["data"],
            **kwargs,
        )

    def execute_scoring(self, exp_id: str, run_name: str, model_type: str, m_cfg: Dict, t_cfg: Dict, l_cfg: Dict):
        """Calculates score and returns results to Skill layer."""
        result_dir = os.path.join(self.dirs["records"], run_name)
        _ensure_dir(result_dir)
        
        train_json_path = os.path.abspath(os.path.join(result_dir, f"experiment_results_{model_type}_{exp_id}.json"))
        score_json_path = os.path.abspath(os.path.join(result_dir, f"score_results_{model_type}_{exp_id}.json"))

        try:
            # Pre-create the scoring JSON so the script can write to it
            with open(score_json_path, 'w') as f:
                json.dump({}, f)

            print(f">>> [Executor] Running scoring for {exp_id}...")
            result = subprocess.run(
                [sys.executable, "execute_tools/denoising_score_single.py", "--mode", "agent", "-m", model_type,
                 "--exp_id", exp_id, "--run_name", run_name, "--output_json", score_json_path,
                 "--data_dir", self.base_dir, "--file_index", str(self.file_index)],
                check=True,
                stdout=None if self.progress_bar else subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True, cwd=os.getcwd(),
                env=_subprocess_env(plugin_dir=self.plugin_dir),
                preexec_fn=_limited_preexec(_subprocess_rss_gb("scoring")),
            )

            # Merge training results (loss history) with scoring results
            results = {}
            if os.path.exists(train_json_path):
                with open(train_json_path, 'r') as f:
                    results.update(json.load(f))
            with open(score_json_path, 'r') as f:
                results.update(json.load(f))

            if os.path.exists(score_json_path): os.remove(score_json_path)

            # Note: We NO LONGER call self.recorder.save_record(record) here.
            # We return results to ml_hyperparameter_tune_agent.py, which adds LLM memory and then saves.
            return {"status": "success", "results": results}
        except subprocess.CalledProcessError as e:
            error_msg = _format_subprocess_error(e, "Scoring")
            print(f"--- Scoring Script Error ---\n{error_msg}")
            status = "oom_host_ram" if _is_oom_failure(e) else "error"
            return {"status": status, "message": error_msg}
        except Exception as e:
            print(f"--- Scoring Internal Error ---\n{str(e)}")
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
        mongodb_uri: Optional[str] = None,
        run_name: str = "test_run",
        workspace: str = "./siderius_workspace",
        progress_bar: bool = False,
        file_index: int = 6,
        run_id: Optional[str] = None,
    ):
        super().__init__(
            metadata_source=metadata_source,
            mongodb_uri=mongodb_uri,
            run_name=run_name,
            workspace=workspace,
            progress_bar=progress_bar,
            file_index=file_index,
        )
        self._run_id: str = run_id or run_name
        self._rng = random.Random(self._run_id)
        self.saved_records: List[Dict[str, Any]] = []
        # Cache training results so ``execute_scoring`` can merge them like
        # prod does (the prod path reads ``experiment_results_*.json`` from
        # disk; the stub keeps an in-memory analogue keyed by ``exp_id``).
        self._train_results_cache: Dict[str, Dict[str, Any]] = {}

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
        m_cfg: Dict,
        t_cfg: Dict,
        l_cfg: Dict,
        sample_set: Optional[Dict] = None,
        train_portion: Optional[float] = None,
        train_base_seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Synthesise a successful training result. No subprocess launch."""
        final_loss = self._rng.uniform(0.5, 5.0)
        results = {
            "final_loss": final_loss,
            "loss_history": [final_loss],
            "model_params": self._rng.randint(1_000, 100_000_000),
        }
        self._train_results_cache[exp_id] = results
        return {
            "status": "success",
            "message": "stub_training_ok",
            "results": results,
        }

    def execute_inference(
        self,
        exp_id: str,
        run_name: str,
        model_type: str,
        m_cfg: Dict,
        l_cfg: Dict,
        sample_set: Optional[Dict] = None,
        inference_batch: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Synthesise a successful inference result. No subprocess launch."""
        return {
            "status": "success",
            "message": "stub_inference_ok",
            "per_file_timings_ms": [],
            "process_startup_ms": 10.0,
            "subprocess_wall_ms": 10.0,
        }

    def execute_scoring(
        self,
        exp_id: str,
        run_name: str,
        model_type: str,
        m_cfg: Dict,
        t_cfg: Dict,
        l_cfg: Dict,
    ) -> Dict[str, Any]:
        """Synthesise scoring + merge cached training results.

        Mirrors the prod merge order in ``TidmadSandbox.execute_scoring``:
        training keys first, then scoring keys (so ``final_loss`` /
        ``loss_history`` / ``model_params`` from the cached trainer output
        appear alongside the synthetic ``denoising_score`` etc.).
        """
        results: Dict[str, Any] = {}
        results.update(self._train_results_cache.get(exp_id, {}))
        results["denoising_score"] = self._rng.uniform(-3.0, -2.0)
        results["file_vector"] = [
            self._rng.uniform(-3.0, -2.0) for _ in range(9)
        ]
        results["is_degenerate"] = False
        results["failure_reason"] = None
        return {"status": "success", "results": results}

    def score_vector(
        self,
        sample_set,
        anchor_map: dict,
        s_max: float,
        denoised_filename_fn,
        **kwargs,
    ) -> tuple:
        """Synthesise the anchor-normalised scoring 4-tuple. No h5 read.

        Production ``TidmadSandbox.score_vector`` delegates to
        ``execute_tools.scoring_utils.score_vector``, which opens the
        ``abra_validation_denoised_*.h5`` artefacts produced by inference.
        Under ``--is_pseudo_training`` those artefacts never get written
        (inference is stubbed), so calling the inherited implementation
        crashes with ``FileNotFoundError`` mid-scoring. This override
        mirrors the synthesis contract of ``execute_scoring`` — same
        ``denoising_score`` ∈ [-3.0, -2.0] band, length-9 ``file_vector``,
        and the fixed ``is_degenerate=False / failure_reason=None`` pair —
        and returns them in the 4-tuple order the tuner unpacks at
        ``ml_hyperparameter_tune_agent.py`` (``score_vector`` call site).

        Args mirror the production signature for swap-in compatibility;
        all are accepted but only ``**kwargs`` swallowing matters here
        (e.g. ``reference_file_vector`` from the tuner's formal-round
        health check). No anchor lookup, no parallel workers, no disk I/O.

        Returns:
            (file_vector, final_scalar, is_degenerate, failure_reason)
        """
        file_vector = [self._rng.uniform(-3.0, -2.0) for _ in range(9)]
        final_scalar = self._rng.uniform(-3.0, -2.0)
        return file_vector, final_scalar, False, None

    def save_record(self, record: Dict[str, Any]) -> None:
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