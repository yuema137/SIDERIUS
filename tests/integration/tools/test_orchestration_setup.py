"""The installed documentation bootstrap must work in a fresh isolated caller."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

from tools.orchestration_setup.assembly import assemble
from tools.workspace_sandbox.profile import SandboxProfile
from tools.workspace_sandbox.runner import run

ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="set SIDERIUS_TEST_WORKSPACE_SANDBOX=1 on a bubblewrap-capable host",
)


def test_installed_native_bootstrap_binds_external_library_and_task(tmp_path):
    """Catch task imports before binding; prove projection, not agent execution."""
    project = tmp_path / "external project"
    project.mkdir()
    data = project / "data"
    data.mkdir()
    profile = SandboxProfile(
        workspace=project, read_only=(data,), network=False, timeout_seconds=30
    )
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(profile.model_dump_json())
    declaration = tmp_path / "run.md"
    declaration.write_text("# Synthetic bootstrap witness\nNo providers or training authorized.\n")
    assemble(profile_path, declaration)
    installed = project / ".agents/skills/siderius-toolkit/references/invocation.md"
    match = re.search(
        r"```python\n(def run_native_call\(.*?)(?:\n```)", installed.read_text(), re.S
    )
    assert match is not None
    caller = project / "caller.py"
    output = project / "results"
    manifest = ROOT / "configs/task_composition/quickstart.yaml"
    caller.write_text(
        """import importlib.abc
import sys

class RequireLibraryBeforeTaskImport(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'workflows.task_composition':
            from core.generated_library import generated_library_is_workspace_bound
            assert generated_library_is_workspace_bound(), 'task imported before library binding'
        return None

sys.meta_path.insert(0, RequireLibraryBeforeTaskImport())
"""
        + match.group(1)
        + f"""
def inspect_native_binding(composition, reference, output):
    from pathlib import Path
    from core.generated_library import generated_library_root, generated_library_is_workspace_bound
    from execute_tools.dataset_config import resolve_dataset_profile
    assert generated_library_is_workspace_bound()
    library = Path(generated_library_root())
    assert library.is_relative_to(output)
    library.mkdir(parents=True)
    (library / 'caller-write.txt').write_text('external only')
    assert resolve_dataset_profile() is not None
    assert reference is not None
    return reference

run_native_call({str(manifest)!r}, {str(data)!r}, {str(output)!r}, inspect_native_binding)
"""
    )
    result = run(profile, [sys.executable, str(caller)])
    assert result.status == "completed"
    saved = json.loads((output / "capability-output.json").read_text())
    assert saved["semantic_fingerprint"]
    assert len(list(output.rglob("caller-write.txt"))) == 1
    assert list(data.iterdir()) == []
