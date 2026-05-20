"""
Machine-specific data paths — loaded from tidmad_data_config.yaml.

All modules import from here instead of hardcoding paths.
When migrating to a new server, update tidmad_data_config.yaml only.

Usage:
    from execute_tools.data_paths import TIDMAD_DATA_DIR, SIDERIUS_DATA_DIR
"""

import os

# Find config file relative to project root
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "tidmad_data_config.yaml")

if os.path.exists(_CONFIG_PATH):
    # Use yaml if available, fall back to simple parsing
    try:
        import yaml

        with open(_CONFIG_PATH) as f:
            _config = yaml.safe_load(f)
    except ImportError:
        # Minimal YAML parsing for simple key: value files
        _config = {}
        with open(_CONFIG_PATH) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, _, value = line.partition(":")
                _config[key.strip()] = value.strip()
else:
    raise FileNotFoundError(
        f"Data config not found at {_CONFIG_PATH}. "
        "Copy tidmad_data_config.yaml and update paths for this machine."
    )

TIDMAD_DATA_DIR: str = _config["tidmad_data_dir"]
SIDERIUS_DATA_DIR: str = _config["siderius_data_dir"]
