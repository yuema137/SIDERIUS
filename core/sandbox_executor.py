# core/sandbox_executor.py
import os
import sys
import json
import subprocess
import datetime
from typing import Dict, Any, Optional
from ml_models.models_format_sandbox import get_config_class, TrainConfig, LossConfig, ExperimentConfig, PLUGIN_CONFIG_REGISTRY
from execute_tools.scoring_utils import validate_sample_set
from execute_tools.data_paths import TIDMAD_DATA_DIR


def _tidmad_data_dir() -> str:
    return TIDMAD_DATA_DIR


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
        
        # every detail json should stay in the run_name folder
        detail_path = os.path.join(self.record_dir, f"{exp_id}.json")
        with open(detail_path, 'w', encoding='utf-8') as f:
            json.dump(record, f, indent=4, ensure_ascii=False)
        
        summary = self.get_summary()
        existing_idx = next((i for i, item in enumerate(summary) if item.get("exp_id") == exp_id), None)
        
        if existing_idx is not None:
            summary[existing_idx] = record
        else:
            summary.append(record)
            
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
                )

            if not self.progress_bar and result.stdout:
                print(f"--- Train Script Output ---\n{result.stdout}")

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
            return {"status": "error", "message": error_msg}
        except Exception as e:
            print(f"!!! [Executor Internal Error] !!!: {str(e)}") 
            return {"status": "error", "message": str(e)}

    # Inference batch sizes matching the original TIDMAD paper (inference.py).
    # These were chosen to keep GPU memory under ~2 GB per model.
    # transformer=1 due to O(T²) attention memory; rnn=10 due to LSTM hidden states.
    _INFERENCE_BATCH_SIZE = {
        "punet": 25, "wavenet": 25, "fcnet": 25,
        "rnn": 10,
        "transformer": 1,
    }

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
                          sample_set: Optional[Dict] = None):
        """Executes the inference physical script.

        Args:
            m_cfg:      Model config dict — validated and written to JSON.
            l_cfg:      Loss config dict — validated and written to JSON.
            sample_set: Optional SampleSet dict. When provided, written to JSON
                        and passed via --sample_set_json.
        """
        validated_m, validated_l = self._validate_model_and_loss(model_type, m_cfg, l_cfg)
        m_path = os.path.abspath(os.path.join(self.dirs["configs"], f"model_config_{exp_id}.json"))
        l_path = os.path.abspath(os.path.join(self.dirs["configs"], f"loss_config_{exp_id}.json"))
        with open(m_path, 'w') as f: json.dump(validated_m, f)
        with open(l_path, 'w') as f: json.dump(validated_l, f)
        model_path = os.path.abspath(os.path.join(self.dirs["models"], f"model_{model_type}_{exp_id}_agent.pth"))
        inf_bs = str(self._INFERENCE_BATCH_SIZE.get(model_type, 25))

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

        try:
            print(f">>> [Executor] Running inference for {exp_id}...")
            result = subprocess.run(
                cmd,
                check=True,
                stdout=None if self.progress_bar else subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True, cwd=os.getcwd(),
                env=_subprocess_env(plugin_dir=self.plugin_dir),
            )
            if not self.progress_bar and result.stdout:
                print(f"--- Inference Output ---\n{result.stdout}")
            return {"status": "success", "message": "Inference finished."}
        except subprocess.CalledProcessError as e:
            error_msg = _format_subprocess_error(e, "Inference")
            print(f"--- Inference Error ---\n{error_msg}")
            return {"status": "error", "message": error_msg}

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
        except Exception as e:
            print(f"--- Scoring Internal Error ---\n{str(e)}")
            return {"status": "error", "message": str(e)}