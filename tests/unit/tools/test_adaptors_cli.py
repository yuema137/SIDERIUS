"""`python -m tools.adaptors` against the synthetic external-style fixture.

These launch real supervised children (CPU only, no network, no LLM).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from core.layout import checkout_root
from tools.adaptors.cli import EXIT_DIAGNOSTIC, EXIT_OK, main
from workflows.custom_adaptors.errors import CustomAdaptorError
from workflows.custom_adaptors.manifest import load_adaptor
from workflows.custom_adaptors.runner import run_once

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "custom_adaptors" / "sibling_digest"


def _project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    shutil.copytree(FIXTURE, project / "adaptors" / "sibling_digest")
    return project, project / "adaptors" / "sibling_digest" / "adaptor.json"


def _replace_entry(manifest: Path, body: str) -> None:
    (manifest.parent / "sibling_digest.py").write_text(body)


def _fixture_inputs(manifest: Path) -> dict[str, object]:
    return json.loads((manifest.parent / "fixtures" / "two_reviews.input.json").read_text())


def test_admit_writes_only_into_the_external_project(tmp_path: Path, capsys) -> None:
    project, manifest = _project(tmp_path)
    assert main(["admit", "--manifest", str(manifest), "--project", str(project)]) == EXIT_OK
    loaded = load_adaptor(manifest)
    record_path = (
        project
        / ".siderius"
        / "adaptors"
        / "example.sibling-digest"
        / f"{loaded.identity_sha256}.admission.json"
    )
    record = json.loads(record_path.read_text())
    assert record["identity_sha256"] == loaded.identity_sha256
    assert record["manifest_sha256"] == loaded.manifest.digest
    assert record["manifest"] == "adaptors/sibling_digest/adaptor.json"
    assert json.loads(capsys.readouterr().out)["admission"] == str(record_path)

    checkout = checkout_root()
    if checkout is None:
        pytest.skip("installed package without a source checkout")
    code = main(["admit", "--manifest", str(FIXTURE / "adaptor.json"), "--project", str(checkout)])
    assert code == EXIT_DIAGNOSTIC
    assert "[admission_location]" in capsys.readouterr().err
    assert not (checkout / ".siderius" / "adaptors").exists()


def test_self_test_catches_nondeterministic_output(tmp_path: Path, capsys) -> None:
    _, manifest = _project(tmp_path)
    _replace_entry(
        manifest,
        "import os\n"
        "from pydantic import BaseModel\n"
        "class Params(BaseModel):\n    max_items: int = 1\n"
        "def adapt(inputs, params, ctx):\n"
        "    return [[{'source': '', 'kind': 'findings', 'content': os.urandom(8).hex(),"
        " 'source_ref': 'x'}]]\n",
    )
    assert main(["self-test", "--manifest", str(manifest)]) == EXIT_DIAGNOSTIC
    assert "[custom_nondeterministic]" in capsys.readouterr().err


def test_timeout_is_a_typed_failure(tmp_path: Path) -> None:
    _, manifest = _project(tmp_path)
    data = json.loads(manifest.read_text())
    data["limits"]["timeout_seconds"] = 0.5
    manifest.write_text(json.dumps(data))
    _replace_entry(
        manifest,
        "import time\n"
        "from pydantic import BaseModel\n"
        "class Params(BaseModel):\n    max_items: int = 1\n"
        "def adapt(inputs, params, ctx):\n    time.sleep(60)\n",
    )
    loaded = load_adaptor(manifest)
    case = _fixture_inputs(manifest)
    with pytest.raises(CustomAdaptorError) as caught:
        run_once(loaded, case["inputs"], case["parameters"], tmp_path / "control")
    assert caught.value.reason == "custom_timeout"


def test_child_refuses_member_edited_after_capture(tmp_path: Path) -> None:
    # Defect: a child importing current disk bytes would run code that was never
    # admitted. The captured pins must be verified before adaptor code executes.
    _, manifest = _project(tmp_path)
    loaded = load_adaptor(manifest)
    helper = manifest.parent / "ranking.py"
    helper.write_text(helper.read_text() + "\n# edited after capture\n")
    case = _fixture_inputs(manifest)
    with pytest.raises(CustomAdaptorError) as caught:
        run_once(loaded, case["inputs"], case["parameters"], tmp_path / "control")
    assert caught.value.reason == "custom_identity_mismatch"
