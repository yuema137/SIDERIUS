"""Typed storage for one native implementation/validation attempt.

The execution-tools layout owner names directories; this module derives the
native storage request and generated-source locations without creating files.
"""

import os
from dataclasses import dataclass

from agent.schemas.storage import LocalStorageConfig, StorageConfig
from execute_tools.impl_attempts import impl_attempt_dir


@dataclass(frozen=True)
class ImplAttemptStorage:
    """Where ONE implement→validate attempt persists (S2 / U6, #256).

    Every field is derived from the nested ``impl_NNN`` directory the
    ``execute_tools.impl_attempts`` authority names, so the implementor
    record, the validation record and the three generated-source
    directories of one retry can never overwrite another's.
    """

    impl_dir: str
    storage: StorageConfig
    plugin_dir: str
    test_dir: str
    loss_dir: str


def impl_attempt_storage(attempt_dir: str, run_name: str, impl_attempt: int) -> ImplAttemptStorage:
    """The typed persistence boundary for implementation attempt ``impl_attempt``.

    Before U6 the loop reused the proposal attempt's storage and derived
    ``models/`` / ``tests/`` / ``losses/`` from ``attempt_dir`` on every
    retry, so a retry silently replaced the previous attempt's records and
    sources. Extracted so the loop body only sequences; the layout is owned
    here and read back by ``funnel_assembly`` / ``workflow_validation``
    through the same authority.
    """
    impl_dir = impl_attempt_dir(attempt_dir, impl_attempt)
    return ImplAttemptStorage(
        impl_dir=impl_dir,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=impl_dir, run_name=run_name),
        ),
        plugin_dir=os.path.join(impl_dir, "models"),
        test_dir=os.path.join(impl_dir, "tests"),
        loss_dir=os.path.join(impl_dir, "losses"),
    )
