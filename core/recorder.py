# core/recorder.py
import os
import json
from datetime import datetime

class TidmadRecorder:
    def __init__(self, base_dir: str):
        """
        Initializes the recorder and ensures storage structures exist.
        """
        self.base_dir = base_dir
        self.summary_path = os.path.join(self.base_dir, "summary.json")
        self.records_dir = os.path.join(self.base_dir, "records")
        
        # Ensure the records directory exists
        os.makedirs(self.records_dir, exist_ok=True)

    def save_record(self, record: dict):
        """
        Saves the complete experimental record, including LLM research memory,
        to both a detailed JSON file and the global summary.json.
        """
        # 1. Add a safe timestamp if not present
        if "timestamp" not in record:
            record["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 2. Save Detailed Individual Record
        # Path: TIDMAD_Sandbox/records/exp_NNN.json
        exp_id = record.get("exp_id", f"unknown_{int(datetime.now().timestamp())}")
        detailed_path = os.path.join(self.records_dir, f"{exp_id}.json")
        
        with open(detailed_path, 'w', encoding='utf-8') as f:
            json.dump(record, f, indent=4, ensure_ascii=False)
        print(f"📄 Detailed record saved to: {detailed_path}")

        # 3. Update Global Summary (The Agent's Memory)
        # Path: TIDMAD_Sandbox/summary.json
        history = self.get_summary()
        
        # Check if we are updating an existing entry or adding a new one
        # (This prevents duplicate entries if you re-run an exp_id)
        existing_idx = next((i for i, item in enumerate(history) if item.get("exp_id") == exp_id), None)
        
        if existing_idx is not None:
            history[existing_idx] = record
        else:
            history.append(record)

        with open(self.summary_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=4, ensure_ascii=False)
        print(f"🧠 Research Memory updated in summary.json")

    def get_summary(self):
        """
        Loads the entire history for the Agent to observe.
        """
        if not os.path.exists(self.summary_path):
            return []
        
        try:
            with open(self.summary_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []