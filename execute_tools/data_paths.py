"""
Machine-specific data paths — loaded from tidmad_data_config.yaml.

All modules import from here instead of hardcoding paths.
When migrating to a new server, update tidmad_data_config.yaml only.

Usage:
    from execute_tools.data_paths import TIDMAD_DATA_DIR, SIDERIUS_DATA_DIR
"""

import os
import warnings

# Find config file relative to project root. The real (gitignored) config is
# ``tidmad_data_config.yaml``; the tracked template is
# ``tidmad_data_config.example.yaml``. Fall back to the template (with a
# warning) so unit tests and fresh clones can import this module without
# manual setup — production code that actually reads from these paths still
# fails loudly when the placeholder template values are used.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "tidmad_data_config.yaml")
_EXAMPLE_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "tidmad_data_config.example.yaml")

if os.path.exists(_CONFIG_PATH):
    _active_config_path = _CONFIG_PATH
elif os.path.exists(_EXAMPLE_CONFIG_PATH):
    warnings.warn(
        f"tidmad_data_config.yaml not found at {_CONFIG_PATH}; "
        f"falling back to template at {_EXAMPLE_CONFIG_PATH}. "
        "Copy the template and update paths for this machine before running "
        "anything that reads from TIDMAD_DATA_DIR or SIDERIUS_DATA_DIR.",
        stacklevel=2,
    )
    _active_config_path = _EXAMPLE_CONFIG_PATH
else:
    raise FileNotFoundError(
        f"Data config not found at {_CONFIG_PATH} and no template available at "
        f"{_EXAMPLE_CONFIG_PATH}. Restore tidmad_data_config.example.yaml or "
        "create tidmad_data_config.yaml manually."
    )

# Use yaml if available, fall back to simple parsing
try:
    import yaml

    with open(_active_config_path) as f:
        _config = yaml.safe_load(f)
except ImportError:
    # Minimal YAML parsing for simple key: value files
    _config = {}
    with open(_active_config_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition(":")
            _config[key.strip()] = value.strip()

TIDMAD_DATA_DIR: str = _config["tidmad_data_dir"]
SIDERIUS_DATA_DIR: str = _config["siderius_data_dir"]
