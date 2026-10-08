"""Versioned admission semantics for successfully completed workloads.

The framework owns generic policies. Consumers own selection for historical runs.
"""

from typing import Literal

RuntimeCompletionPolicy = Literal["completed-workload-v1", "verified-prediction-v1"]
