# core/sandbox_executor.py
import os
import json
import subprocess
import datetime
from typing import Dict, Any, Optional
from models_format_sandbox import get_config_class, TrainConfig, LossConfig, ExperimentConfig

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
        os.makedirs(self.record_dir, exist_ok=True)

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

class TidmadSandbox:
    def __init__(self, metadata_source: str = "local", mongodb_uri: Optional[str] = None, run_name: str="test_run"):
        # Set up sandbox directory structure - hard coded for now
        self.base_dir = "/home/klz/Data/TIDMAD_Sandbox"
        self.dirs = {
            "configs": os.path.join(self.base_dir, "configs", run_name),
            "models": os.path.join(self.base_dir, "cached_models"),
            "records": os.path.join(self.base_dir, "records"),
            "data": "/home/klz/Data/TIDMAD/" 
        }
        for d in self.dirs.values():
            os.makedirs(d, exist_ok=True)

        self.run_name = run_name
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
        """Direct access for agent_main to save finalized research records."""
        self.recorder.save_record(record)

    def get_summary(self) -> list:
        """Retrieves experiment history for the Agent's planning phase."""
        return self.recorder.get_summary()

    def _validate_configs(self, model_type: str, m_cfg: Dict, t_cfg: Dict, l_cfg: Dict, exp_id: str, run_name: str):
        """Internal helper to validate dicts using the Global ExperimentConfig."""
        try:
            # Consolidate all dicts into one global check
            full_payload = {
                "exp_id": exp_id,
                "run_name": run_name,
                "model_type": model_type,
                "network_config": m_cfg,
                "train_config": t_cfg,
                "loss_config": l_cfg
            }
            
            # This single line performs all individual AND cross-object validations
            exp_config = ExperimentConfig(**full_payload)
            
            return (
                exp_config.network_config.model_dump(),
                exp_config.train_config.model_dump(),
                exp_config.loss_config.model_dump()
            )
        except Exception as e:
            # The agent receives this specific error message and can correct its plan
            raise ValueError(f"Experiment Configuration Rejected: {str(e)}")

    def execute_training(self, exp_id: str, run_name: str, model_type: str, m_cfg: Dict, t_cfg: Dict, l_cfg: Dict):
        """Executes the training physical script."""
        try:
            vm, vt, vl = self._validate_configs(model_type, m_cfg, t_cfg, l_cfg, exp_id, run_name)
            
            paths = {
                "m": os.path.abspath(os.path.join(self.dirs["configs"], f"model_config_{exp_id}.json")),
                "t": os.path.abspath(os.path.join(self.dirs["configs"], f"train_config_{exp_id}.json")),
                "l": os.path.abspath(os.path.join(self.dirs["configs"], f"loss_config_{exp_id}.json"))
            }
            for k, v in zip(["m", "t", "l"], [vm, vt, vl]):
                with open(paths[k], 'w') as f: json.dump(v, f)

            print(f">>> [Executor] Running training for {exp_id}...")
            result = subprocess.run(
                    ["python", "train_engine_sandbox.py", 
                    "--model_cfg", paths["m"], 
                    "--train_cfg", paths["t"], 
                    "--loss_cfg", paths["l"],
                    "--exp_id", exp_id,
                    "--run_name", run_name,],
                    check=True, 
                    capture_output=True, 
                    text=True,
                    cwd=os.getcwd() 
                )
            
            if result.stdout: print(f"--- Train Script Output ---\n{result.stdout}")
            return {"status": "success", "message": "Training finished."}

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else e.stdout
            print(f"--- Train Script Error ---\n{error_msg}")
            return {"status": "error", "message": error_msg}
        except Exception as e:
            print(f"!!! [Executor Internal Error] !!!: {str(e)}") 
            return {"status": "error", "message": str(e)}

    def execute_inference(self, exp_id: str, run_name: str, model_type: str, m_cfg: Dict, l_cfg: Dict):
        """Executes the inference physical script."""
        m_path = os.path.abspath(os.path.join(self.dirs["configs"], f"model_config_{exp_id}.json"))
        l_path = os.path.abspath(os.path.join(self.dirs["configs"], f"loss_config_{exp_id}.json"))
        model_path = os.path.abspath(os.path.join(self.dirs["models"], f"model_{model_type}_{exp_id}_agent.pth"))
        
        try:
            print(f">>> [Executor] Running inference for {exp_id}...")
            result = subprocess.run(
                ["python", "inference_single.py", "--mode", "agent", "-m", model_type, 
                 "--model_cfg", m_path, "--loss_cfg", l_path, 
                 "--model_path", model_path, "--exp_id", exp_id, "--run_name", run_name,], 
                check=True, capture_output=True, text=True, cwd=os.getcwd()
            )
            if result.stdout: print(f"--- Inference Output ---\n{result.stdout}")
            return {"status": "success", "message": "Inference finished."}
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else e.stdout
            print(f"--- Inference Error ---\n{error_msg}")
            return {"status": "error", "message": error_msg}

    def execute_scoring(self, exp_id: str, run_name: str, model_type: str, m_cfg: Dict, t_cfg: Dict, l_cfg: Dict):
        """Calculates score and returns results to Skill layer."""
        result_dir = os.path.join(self.dirs["records"], run_name)
        os.makedirs(result_dir, exist_ok=True)
        
        result_json_name = f"experiment_results_{model_type}_{exp_id}.json"
        actual_json_path = os.path.abspath(os.path.join(result_dir, result_json_name))
        
        try:
            print(f">>> [Executor] Running scoring for {exp_id}...")
            result = subprocess.run(
                ["python", "denoising_score_single.py", "--mode", "agent", "-m", model_type, 
                 "--exp_id", exp_id, "--run_name", run_name, "--output_json", actual_json_path], 
                check=True, capture_output=True, text=True, cwd=os.getcwd()
            )

            with open(actual_json_path, 'r') as f:
                results = json.load(f)
            
            if os.path.exists(actual_json_path): os.remove(actual_json_path)
            
            # Note: We NO LONGER call self.recorder.save_record(record) here.
            # We return results to agent_main.py, which adds LLM memory and then saves.
            return {"status": "success", "results": results}
        except Exception as e:
            print(f"--- Scoring Internal Error ---\n{str(e)}")
            return {"status": "error", "message": str(e)}