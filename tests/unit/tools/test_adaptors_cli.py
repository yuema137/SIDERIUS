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
    captured = capsys.readouterr()
    assert "[custom_nondeterministic]" in captured.err
    assert captured.out == ""


def _set_timeout(manifest: Path, seconds: float) -> None:
    data = json.loads(manifest.read_text())
    data["limits"]["timeout_seconds"] = seconds
    manifest.write_text(json.dumps(data))


def _run_fixture(manifest: Path, control: Path, **parameters: object):
    case = _fixture_inputs(manifest)
    return run_once(
        load_adaptor(manifest), case["inputs"], {**case["parameters"], **parameters}, control
    )


_STARTUP_DELAY_SECONDS = 6.0
_AUTHOR_TIMEOUT_SECONDS = 4.0


def _delay_child_startup(monkeypatch, seconds: float) -> None:
    """Test-only hook: the child sleeps before running its module, i.e. before `entered`."""
    from workflows.custom_adaptors import process

    real = process.supervise_subprocess

    def delayed(cmd, **kwargs):
        executable, *flags, module_flag, module, request = cmd
        assert (module_flag, module) == ("-m", "workflows.custom_adaptors.child")
        code = (
            f"import runpy, sys, time; time.sleep({seconds}); "
            f"runpy.run_module({module!r}, run_name='__main__', alter_sys=True)"
        )
        return real([executable, *flags, "-c", code, request], **kwargs)

    monkeypatch.setattr(process, "supervise_subprocess", delayed)


def test_author_timeout_starts_at_entered_not_at_launch(tmp_path: Path, monkeypatch) -> None:
    # Defect: counting startup against the author's timeout made fast adaptors
    # fail whenever startup was slower than their timeout. Startup is forced to
    # 6 s (> the 4 s author timeout), so only a deadline that starts at `entered`
    # lets this run finish; the fast adaptor then has 4 s for its post-entry work.
    _, manifest = _project(tmp_path)
    _set_timeout(manifest, _AUTHOR_TIMEOUT_SECONDS)
    _delay_child_startup(monkeypatch, _STARTUP_DELAY_SECONDS)
    output, elapsed = _run_fixture(manifest, tmp_path / "fast")
    assert output.author[0][0]["source_ref"] == "sd0"
    assert elapsed > _STARTUP_DELAY_SECONDS  # The hook really delayed startup.


def test_author_timeout_stops_a_running_adaptor(tmp_path: Path) -> None:
    _, manifest = _project(tmp_path)
    _set_timeout(manifest, 3)
    _replace_entry(
        manifest,
        "import time\n"
        "from pydantic import BaseModel\n"
        "class Params(BaseModel):\n    max_items: int = 1\n"
        "def adapt(inputs, params, ctx):\n    time.sleep(60)\n",
    )
    with pytest.raises(CustomAdaptorError) as caught:
        _run_fixture(manifest, tmp_path / "slow")
    assert caught.value.reason == "custom_timeout"
    assert "after entry" in str(caught.value)


def test_child_sees_no_caller_secrets_or_cwd_modules(tmp_path: Path, monkeypatch) -> None:
    _, manifest = _project(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sentinel-not-for-adaptors")
    shadow = tmp_path / "cwd"
    (shadow / "workflows").mkdir(parents=True)
    (shadow / "workflows" / "__init__.py").write_text("raise SystemExit('shadowed')\n")
    monkeypatch.chdir(shadow)
    _replace_entry(
        manifest,
        "import json, os\n"
        "from pydantic import BaseModel\n"
        "class Params(BaseModel):\n    max_items: int = 1\n"
        "def adapt(inputs, params, ctx):\n"
        "    return [[{'source': '', 'kind': 'literature', 'source_ref': 'env',"
        " 'content': json.dumps(sorted(os.environ))}]]\n",
    )
    output, _ = _run_fixture(manifest, tmp_path / "control")
    visible = json.loads(output.author[0][0]["content"])
    assert "OPENAI_API_KEY" not in visible
    allowed = {"PATH", "VIRTUAL_ENV", "LANG", "LANGUAGE", "HOME", "TMPDIR"}
    allowed |= {"PYTHONHASHSEED", "PYTHONNOUSERSITE"}
    assert all(key in allowed or key.startswith("LC_") for key in visible), visible


_PARAMS = "from pydantic import BaseModel\nclass Params(BaseModel):\n    max_items: int = 1\n"
_FORGE = (
    "import json, os, sys\n"
    "from pathlib import Path\n"
    "def forge(unlink_entered=False):\n"
    "    control = Path(json.loads(Path(sys.argv[1]).read_text())['control_dir'])\n"
    "    if unlink_entered:\n"
    "        (control / 'entered').unlink()\n"
    "    (control / 'failure.json').write_text(json.dumps("
    "{'stage': 'identity', 'detail': 'forged'}))\n"
    "    os._exit(78)\n"
)


@pytest.mark.parametrize(
    "body",
    [
        _FORGE + _PARAMS + "forge()\n",
        _FORGE + _PARAMS + "def adapt(inputs, params, ctx):\n    forge()\n",
        _FORGE + _PARAMS + "def adapt(inputs, params, ctx):\n    forge(unlink_entered=True)\n",
    ],
    ids=["module-level-forge", "forge-in-call", "unlink-entered-then-forge"],
)
def test_adaptor_code_cannot_forge_an_identity_mismatch(tmp_path: Path, body: str) -> None:
    # Defect: trusting the child's failure file let adaptor code (module body or
    # call, even after deleting the entered marker) report a pin mismatch.
    _, manifest = _project(tmp_path)
    _replace_entry(manifest, body)
    with pytest.raises(CustomAdaptorError) as caught:
        _run_fixture(manifest, tmp_path / "control")
    assert caught.value.reason == "custom_exception"


def test_identity_hint_after_entered_is_not_trusted_even_with_changed_pins(
    tmp_path: Path,
) -> None:
    # Defect: ignoring the parent's own `entered` observation would let adaptor
    # code edit a member on disk and then forge an identity mismatch; the pin
    # re-check alone cannot tell, because the bytes really changed.
    _, manifest = _project(tmp_path)
    _replace_entry(
        manifest,
        _FORGE + _PARAMS + "def adapt(inputs, params, ctx):\n"
        "    helper = Path(__file__).with_name('ranking.py')\n"
        "    helper.write_text(helper.read_text() + '# edited by adaptor\\n')\n"
        "    forge()\n",
    )
    with pytest.raises(CustomAdaptorError) as caught:
        _run_fixture(manifest, tmp_path / "control")
    assert caught.value.reason == "custom_exception"


@pytest.mark.parametrize(
    ("entered_seen", "pins_changed", "expected"),
    [
        (False, True, "custom_identity_mismatch"),
        (False, False, "custom_exception"),
        (True, True, "custom_exception"),
    ],
)
def test_identity_mismatch_needs_unseen_entry_and_changed_pins(
    tmp_path: Path, entered_seen: bool, pins_changed: bool, expected: str
) -> None:
    # Deterministic witness for both guards: the end-to-end forge tests can be
    # decided by whichever guard fires first, depending on poll timing.
    from workflows.custom_adaptors.invocation import FAILURE_FILE, CustomInvocation
    from workflows.custom_adaptors.process import _failure_reason

    invocation = CustomInvocation(
        adaptor_id="example.x",
        role="combine",
        transport_manifest="/t",
        transport_sha256="0" * 64,
        entry_path="/e.py",
        entry_function="adapt",
        parameters_path=None,
        parameters_class=None,
        ports=(),
        parameters={},
        control_dir=str(tmp_path),
        max_output_bytes=1,
    )
    (tmp_path / FAILURE_FILE).write_text(json.dumps({"stage": "identity", "detail": "x"}))
    error = _failure_reason(invocation, 1, entered_seen, lambda: pins_changed)
    assert error.reason == expected


def test_invalid_parameters_fail_without_running_adapt(tmp_path: Path) -> None:
    # Parameters are validated by the author's model after import, so a refusal
    # is a custom_exception that names the parameters stage, not an input refusal.
    _, manifest = _project(tmp_path)
    with pytest.raises(CustomAdaptorError) as caught:
        _run_fixture(manifest, tmp_path / "params", max_items=0)
    assert caught.value.reason == "custom_exception"
    assert str(caught.value).startswith("[custom_exception] parameters:")


def test_adaptor_cannot_flood_the_parent_capture(tmp_path: Path, monkeypatch) -> None:
    # Defect: a kept duplicate of the parent's stdout/stderr let adaptor code
    # bypass the 64 KiB log cap and fill the supervisor's in-memory capture.
    from workflows.custom_adaptors import process
    from workflows.custom_adaptors.invocation import MAX_LOG_BYTES

    observed = []
    real = process.supervise_subprocess

    def recording(*args, **kwargs):
        result = real(*args, **kwargs)
        observed.append(result.completed)
        return result

    monkeypatch.setattr(process, "supervise_subprocess", recording)
    _, manifest = _project(tmp_path)
    source = (manifest.parent / "sibling_digest.py").read_text()
    _replace_entry(
        manifest,
        source.replace(
            "    ctx.log(",
            "    import os\n"
            "    for fd in range(1, 65):\n"
            "        try:\n"
            "            os.write(fd, b'x' * 1_000_000)\n"
            "        except OSError:\n"
            "            pass\n"
            "    ctx.log(",
        ),
    )
    _run_fixture(manifest, tmp_path / "control")
    completed = observed[0]
    assert len(completed.stdout or "") + len(completed.stderr or "") <= MAX_LOG_BYTES


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
