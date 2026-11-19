"""Explicit external selections; no native task import in the test parent."""

from pathlib import Path

import pytest

from tests.helpers.process_bounds import CHILD_PROCESS_BOUND_SECONDS
from tools.candidate_prepare import CandidatePreparationRequest

REPO = Path(__file__).resolve().parents[4]
#: Preparation allocation for real offline preparation children: the shared child
#: bound (30 s expired under host load and turned the receipt into ``failed``).
PREPARATION_TIMEOUT_SECONDS = CHILD_PROCESS_BOUND_SECONDS


@pytest.fixture
def selection(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "llm.json"
    config.write_text("{}")
    return CandidatePreparationRequest(
        task_manifest=str(REPO / "configs/task_composition/quickstart.yaml"),
        data_root=str(data),
        llm_config_file=str(config),
        output_dir=str(tmp_path / "bundle"),
        candidate_workspace=str(tmp_path / "candidate"),
        run_name="candidate",
        preparation_timeout_seconds=PREPARATION_TIMEOUT_SECONDS,
        candidate_timeout_seconds=60.0,
        task_read_only=(),
        candidate_network=False,
        candidate_devices=(),
        candidate_environment_names=(),
        proposal_advice="Check all four input features.",
        implementation_advice="Keep code small.",
        validation_advice="Check the declared shape.",
        allowed_output_types=("classifier",),
    )
