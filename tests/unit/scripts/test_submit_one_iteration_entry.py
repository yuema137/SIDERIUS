"""Full-entry regressions for the shipped Slurm wrapper."""

from __future__ import annotations

import json
import subprocess
import venv
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WRAPPER = REPO / "scripts/slurm/submit_one_iteration.slurm"


@dataclass(frozen=True)
class WrapperResult:
    process: subprocess.CompletedProcess[str]
    capture_path: Path
    probe_tmp: Path

    @property
    def returncode(self) -> int:
        return self.process.returncode

    @property
    def stdout(self) -> str:
        return self.process.stdout

    @property
    def stderr(self) -> str:
        return self.process.stderr


def _run(
    tmp_path: Path,
    *args: str,
    mode: str = "ok",
    probe: int | None = 0,
    interpreter: str | None = None,
    equals: bool = True,
) -> WrapperResult:
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "wrapper.slurm"
    text = WRAPPER.read_text()
    inert = tmp_path / "inert.py"
    inert.write_text(
        "import json, os, sys\nfrom pathlib import Path\n"
        "p=__import__('argparse').ArgumentParser(add_help=False)\n"
        "p.add_argument('--workspace',required=True); p.add_argument('--iteration'); p.add_argument('--start_iteration')\n"
        "p.add_argument('--source_paths',nargs='+'); p.add_argument('--seed_paths',nargs='+'); a,_=p.parse_known_args()\n"
        "cap=os.environ.get('INERT_CAPTURE')\n"
        "if cap: Path(cap).write_text(json.dumps({'argv':sys.argv[1:], 'prefix':sys.prefix, 'pythonpath':os.environ.get('PYTHONPATH'), 'virtual_env':os.environ.get('VIRTUAL_ENV')}))\n"
        "iteration=a.iteration or a.start_iteration; d=Path(a.workspace)/f'iter_{int(iteration):03d}'; d.mkdir(parents=True,exist_ok=True)\n"
        "if os.environ.get('INERT_MODE') == 'no-manifest': raise SystemExit(0)\n"
        "(d/'manifest.json').write_text('{\"status\":\"completed\"}')\n"
        "if os.environ.get('INERT_MODE') == 'fail': raise SystemExit(7)\n"
        "print('INERT_CHILD', *sys.argv[1:])\n"
    )
    seam = '"$PYTHON_BIN" "$PROJECT_DIR/src/workflows/run_one_iteration.py"'
    assert text.count(seam) == 1
    text = text.replace(seam, f'"$PYTHON_BIN" "{inert}"')
    assert text.count(str(inert)) == 1
    probe_tmp = tmp_path / "probe-temp"
    assert text.count('PROBE_TMP="$(mktemp -d)"') == 1
    text = text.replace(
        'PROBE_TMP="$(mktemp -d)"', f'mkdir -p "{probe_tmp}"\nPROBE_TMP="{probe_tmp}"'
    )
    if probe is None:
        text = text.replace(
            "$PROJECT_DIR/scripts/launch/_import_resolution_probe.py",
            "$PROJECT_DIR/scripts/launch/missing_probe.py",
        )
    elif probe != 0:
        stub = tmp_path / "probe_stub.py"
        stub.write_text(f"raise SystemExit({probe})\n")
        text = text.replace("$PROJECT_DIR/scripts/launch/_import_resolution_probe.py", str(stub))
    if interpreter is not None:
        text = text.replace(
            'PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"', f'PYTHON_BIN="{interpreter}"'
        )
    script.write_text(text)
    capture = tmp_path / "child.json"
    checkout = [f"--siderius-checkout={REPO}"] if equals else ["--siderius-checkout", str(REPO)]
    result = subprocess.run(
        ["bash", str(script), *checkout, *args],
        cwd=tmp_path,
        env={
            "HOME": str(tmp_path),
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(tmp_path / "foreign"),
            "VIRTUAL_ENV": str(tmp_path / "foreign-v"),
            "INERT_MODE": mode,
            "INERT_CAPTURE": str(capture),
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    return WrapperResult(result, capture, probe_tmp)


def _captured(result: WrapperResult) -> dict:
    return json.loads(result.capture_path.read_text())


def test_full_wrapper_matrix_preserves_argv_defaults_and_cleanup(tmp_path: Path) -> None:
    canonical = _run(
        tmp_path / "canonical",
        "--workspace",
        str(tmp_path / "canonical/ws"),
        "--start_iteration",
        "1",
        "--seed_paths",
        str(tmp_path / "seed one.json"),
        "--data_scope",
        "4-9",
        "--max_rounds=7",
        "--mystery",
        "spaced value",
        "--no-is_trial",
    )
    assert canonical.returncode == 0, canonical.stderr
    assert "[import-probe] PASS (tree-only)" in canonical.stdout
    child = _captured(canonical)
    assert child["argv"][:4] == [
        "--workspace",
        str(tmp_path / "canonical/ws"),
        "--start_iteration",
        "1",
    ]
    assert child["argv"][4:6] == ["--seed_paths", str(tmp_path / "seed one.json")]
    assert "--data_scope" in child["argv"] and "spaced value" in child["argv"]
    assert "--max_rounds=7" in child["argv"] and "--cleanup_denoised" in child["argv"]
    assert "--is_trial" not in child["argv"]
    assert child["pythonpath"] is None and child["virtual_env"] == str(REPO / ".venv")
    assert Path(child["prefix"]).resolve() == (REPO / ".venv").resolve()
    assert (tmp_path / "canonical/ws/iter_001/manifest.json").is_file()
    assert not canonical.probe_tmp.exists()

    retained = _run(
        tmp_path / "retained",
        "--workspace",
        str(tmp_path / "retained/ws"),
        "--start_iteration",
        "1",
        "--seed_paths",
        str(tmp_path / "seed one.json"),
        "--retain_model_outputs",
    )
    assert retained.returncode == 0, retained.stderr
    assert "--retain_model_outputs" in _captured(retained)["argv"]
    assert "--cleanup_denoised" not in _captured(retained)["argv"]

    legacy = _run(
        tmp_path / "legacy",
        "--workspace",
        str(tmp_path / "legacy/ws"),
        "--iteration",
        "1",
        "--source_paths",
        str(tmp_path / "seed.json"),
        equals=False,
    )
    assert legacy.returncode == 0, legacy.stderr
    assert "--iteration" in _captured(legacy)["argv"]
    for mode, expected in (("fail", 7), ("no-manifest", 1)):
        result = _run(
            tmp_path / mode,
            "--workspace",
            str(tmp_path / mode / "ws"),
            "--iteration",
            "1",
            "--source_paths",
            "/tmp/seed",
            mode=mode,
        )
        assert result.returncode == expected
        if mode == "no-manifest":
            assert "Manifest not found" in result.stderr
        assert result.capture_path.exists()  # child was reached in both cases


def test_full_wrapper_refuses_probe_outcomes_and_foreign_interpreter(tmp_path: Path) -> None:
    for code in (None, 3, 4, 9):
        result = _run(
            tmp_path / f"probe-{code}",
            "--workspace",
            str(tmp_path / f"probe-{code}/ws"),
            "--iteration",
            "1",
            "--source_paths",
            "/tmp/seed",
            probe=code,
        )
        assert result.returncode == 1 and "probe" in result.stderr.lower()
        assert not result.capture_path.exists()
    foreign_env = tmp_path / "foreign-env"
    venv.EnvBuilder(with_pip=False, clear=True).create(foreign_env)
    foreign = _run(
        tmp_path / "foreign",
        "--workspace",
        str(tmp_path / "foreign/ws"),
        "--iteration",
        "1",
        "--source_paths",
        "/tmp/seed",
        interpreter=str(foreign_env / "bin/python"),
    )
    assert foreign.returncode == 1 and "not owned" in foreign.stderr


def test_full_wrapper_rejects_binding_errors(tmp_path: Path) -> None:
    for argv in (("--siderius-checkout",), ("--siderius-checkout", "")):
        result = subprocess.run(
            ["bash", str(WRAPPER), *argv], text=True, capture_output=True, check=False, timeout=10
        )
        assert result.returncode == 2 and "requires a nonempty value" in result.stderr
    duplicate = subprocess.run(
        ["bash", str(WRAPPER), "--siderius-checkout", str(REPO), "--siderius-checkout", str(REPO)],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert duplicate.returncode == 2 and "duplicate" in duplicate.stderr
