"""Full-entry Slurm wrapper regressions (no parser slicing).

The fixture replaces only the expensive ROI with an inert manifest writer; the
shipped wrapper's complete bootstrap, argument loop, probe, defaults, exit and
post-run verification execute unchanged.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WRAPPER = REPO / "scripts/slurm/submit_one_iteration.slurm"


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "wrapper.slurm"
    text = WRAPPER.read_text()
    inert = tmp_path / "inert.py"
    inert.write_text(
        "from pathlib import Path\n"
        "import argparse\n"
        "p=argparse.ArgumentParser(add_help=False)\n"
        "p.add_argument('--workspace',required=True); p.add_argument('--iteration'); p.add_argument('--start_iteration')\n"
        "p.add_argument('--source_paths',nargs='+'); p.add_argument('--seed_paths',nargs='+'); a,_=p.parse_known_args()\n"
        "iteration=a.iteration or a.start_iteration; d=Path(a.workspace)/f'iter_{int(iteration):03d}'; d.mkdir(parents=True,exist_ok=True)\n"
        "(d/'manifest.json').write_text('{\"status\":\"completed\"}')\n"
        "print('INERT_CHILD', *(__import__('sys').argv[1:]))\n"
    )
    text = text.replace(
        '"$PYTHON_BIN" "$PROJECT_DIR/src/workflows/run_one_iteration.py"',
        f'"$PYTHON_BIN" "{inert}"',
    )
    script.write_text(text)
    return subprocess.run(
        ["bash", str(script), "--siderius-checkout", str(REPO), *args],
        cwd=tmp_path,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(tmp_path / "foreign")},
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def test_full_wrapper_canonical_and_legacy_forwarding(tmp_path: Path) -> None:
    canonical = _run(
        tmp_path / "canonical",
        "--workspace", str(tmp_path / "canonical" / "ws"),
        "--start_iteration", "1", "--seed_paths", str(tmp_path / "seed one.json"),
        "--data_scope", "4-9", "--max_rounds", "7",
    )
    assert canonical.returncode == 0, canonical.stderr
    assert "INERT_CHILD" in canonical.stdout
    assert "--start_iteration 1" in canonical.stdout
    assert (tmp_path / "canonical" / "ws/iter_001/manifest.json").is_file()

    legacy = _run(
        tmp_path / "legacy",
        "--workspace", str(tmp_path / "legacy" / "ws"),
        "--iteration", "1", "--source_paths", str(tmp_path / "seed.json"),
    )
    assert legacy.returncode == 0, legacy.stderr
    assert "--iteration 1" in legacy.stdout


def test_full_wrapper_rejects_checkout_binding_errors(tmp_path: Path) -> None:
    missing = subprocess.run(
        ["bash", str(WRAPPER), "--siderius-checkout"],
        text=True, capture_output=True, check=False, timeout=10,
    )
    assert missing.returncode == 2
    assert "requires a nonempty value" in missing.stderr

    duplicate = subprocess.run(
        ["bash", str(WRAPPER), "--siderius-checkout", str(REPO), "--siderius-checkout", str(REPO)],
        text=True, capture_output=True, check=False, timeout=10,
    )
    assert duplicate.returncode == 2
    assert "duplicate" in duplicate.stderr
