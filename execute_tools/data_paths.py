"""
Machine-specific data paths — loaded from tidmad_data_config.json.

All modules import from here instead of hardcoding paths.
When migrating to a new server, update tidmad_data_config.json only.

Usage:
    from execute_tools.data_paths import TIDMAD_DATA_DIR, SIDERIUS_DATA_DIR
"""

import os
import json

# Find config file relative to project root
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "tidmad_data_config.json")

if os.path.exists(_CONFIG_PATH):
    with open(_CONFIG_PATH, "r") as f:
        _config = json.load(f)
else:
    raise FileNotFoundError(
        f"Data config not found at {_CONFIG_PATH}. "
        "Copy tidmad_data_config.json.example and update paths for this machine."
    )

TIDMAD_DATA_DIR: str = _config["tidmad_data_dir"]
SIDERIUS_DATA_DIR: str = _config["siderius_data_dir"]
