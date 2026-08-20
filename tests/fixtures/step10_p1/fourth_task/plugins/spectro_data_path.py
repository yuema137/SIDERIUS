"""A fourth task's data path, supplied as an OUT-OF-TREE plugin file.

Nothing in SIDERIUS imports this module, names this task, or knows its id
exists. The composition manifest names the file and the symbol; the loader
executes it and registers the instance through the SAME public registry the
built-ins use. That is the whole extension mechanism.

The four methods are deliberately minimal — P1 proves the COMPOSITION
contract (a conforming implementation binds, transports and reaches its
consumers with zero framework edits), not that this synthetic task trains.
"""

from __future__ import annotations

from typing import Any, ClassVar

SPECTRO_TASK_DATA_PATH_ID = "spectro_segmentation_v0"


class SpectroTaskDataPath:
    """A conforming implementation that declares its own id."""

    task_data_path_id: ClassVar[str] = SPECTRO_TASK_DATA_PATH_ID

    def training_dataset(self, scope: Any, sampling: Any) -> Any:
        raise NotImplementedError(
            "fixture task: P1 binds and transports this implementation; it "
            "never executes it (executable closure is P6's)."
        )

    def validation_dataset(self, scope: Any, sampling: Any) -> Any:
        raise NotImplementedError("fixture task: see training_dataset.")

    def write_deliverable(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("fixture task: see training_dataset.")

    def read_evaluation_payload(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("fixture task: see training_dataset.")
