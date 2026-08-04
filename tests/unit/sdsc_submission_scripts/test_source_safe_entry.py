"""Sourcing a launcher must never run its launch path.

On 2026-07-31 `v19_gate0_pair_runner.sh` was sourced without its
environment-only opt-out in order to read the frozen argv, and executed
its entire main path. Nothing launched — the workspace-exists guard
refused — but it rewrote the Gate pair summary and appended to the
runner log. An opt-out you have to remember is not a guard.

Both launchers now use the standard source-safe entry guard, and these
tests prove the three properties that matter: direct execution runs main,
sourcing does not, and sourcing leaves the filesystem alone.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCHERS = {
    "gate": REPO_ROOT / "sdsc_submission_scripts" / "v19_gate0_pair_runner.sh",
    "queue": REPO_ROOT / "sdsc_submission_scripts" / "v19_queue_runner.sh",
}


def _bash(script: str, **env) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=dict(os.environ, **{k: str(v) for k, v in env.items()}),
        timeout=120,
    )


@pytest.mark.parametrize("name", sorted(LAUNCHERS))
class TestSourceSafety:
    def test_the_guard_is_the_standard_form(self, name):
        source = LAUNCHERS[name].read_text()
        assert '[[ "${BASH_SOURCE[0]}" == "$0" ]]' in source
        assert "main() {" in source

    def test_sourcing_does_not_run_main(self, name, tmp_path):
        """Sourced WITHOUT any opt-out variable — the guard alone must
        hold, because that is the case that actually happened."""
        root = tmp_path / "root"
        result = _bash(
            f"source '{LAUNCHERS[name]}'; echo SOURCED_OK",
            GATE_ROOT=str(root),
            WS_ROOT=str(root),
            EXIT_DIR=str(tmp_path / "markers"),
        )
        assert "SOURCED_OK" in result.stdout
        # main() is what creates the root directory; nothing may exist.
        assert not root.exists(), f"sourcing {name} created {root}"

    def test_sourcing_modifies_no_workspace_log_or_summary(self, name, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        summary = root / "gate0_pair_summary.json"
        runner_log = root / "gate0_runner.log"
        queue_log = root / "v19_queue_runner.log"
        wave_state = root / "v19_wave_state.jsonl"
        workspace = root / "v19_gate_arch_15_19"
        workspace.mkdir()
        sentinel = workspace / "iter_001.json"
        for path in (summary, runner_log, queue_log, wave_state, sentinel):
            path.write_text("ORIGINAL")
        before = {p: (p.read_text(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}

        _bash(
            f"source '{LAUNCHERS[name]}'; true",
            GATE_ROOT=str(root),
            WS_ROOT=str(root),
            EXIT_DIR=str(tmp_path / "markers"),
        )

        after = {p: (p.read_text(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}
        assert after == before, f"sourcing {name} modified files"

    def test_sourcing_still_exposes_the_definitions(self, name):
        """The whole point of sourcing: read the frozen command without
        running it."""
        # Repointed from `${MAX_CONC:-unset}` (D-E-3 deleted MAX_CONC as a
        # label that gated nothing). The old probe would have printed
        # "unset" and passed either way; `$CAMPAIGN_HOME` is a real
        # definition, so an empty result now means sourcing exposed
        # nothing — which is the defect this test is for.
        probe = "gate_chain_args arch | head -2" if name == "gate" else 'echo "$CAMPAIGN_HOME"'
        result = _bash(f"source '{LAUNCHERS[name]}'; {probe}")
        assert result.stdout.strip(), result.stderr


class TestTheGuardIdiomItself:
    """That the idiom works is proved on a THROWAWAY script.

    Executing a real launcher to prove main() runs is not an option: the
    Gate runner takes no arguments, so a direct run performs a real
    launch. An earlier version of this file did exactly that and started
    two chains. The launchers are therefore checked for the idiom
    STATICALLY (above); the idiom's behaviour is checked here.
    """

    GUARD = """
main() { echo "MAIN_RAN"; touch "$1/side_effect"; }
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
"""

    def _script(self, tmp_path: Path) -> Path:
        path = tmp_path / "guarded.sh"
        path.write_text(self.GUARD)
        return path

    def test_direct_execution_runs_main(self, tmp_path):
        script = self._script(tmp_path)
        result = _bash(f"bash '{script}' '{tmp_path}'")
        assert "MAIN_RAN" in result.stdout
        assert (tmp_path / "side_effect").exists()

    def test_sourcing_does_not_run_main(self, tmp_path):
        script = self._script(tmp_path)
        result = _bash(f"source '{script}'; echo SOURCED")
        assert "MAIN_RAN" not in result.stdout
        assert "SOURCED" in result.stdout
        assert not (tmp_path / "side_effect").exists()

    def test_sourcing_still_defines_main(self, tmp_path):
        script = self._script(tmp_path)
        result = _bash(f"source '{script}'; declare -F main")
        assert "main" in result.stdout


class TestLegacyOptOutStillHonoured:
    """Existing callers pass the env var; it must keep working, while no
    longer being the thing that protects us."""

    def test_the_gate_opt_out_is_accepted(self, tmp_path):
        result = _bash(
            f"V19_GATE0_NO_MAIN=1 source '{LAUNCHERS['gate']}'; gate_chain_args loss | head -1",
            GATE_ROOT=str(tmp_path / "root"),
        )
        assert result.stdout.strip() == "--mode"

    def test_the_queue_opt_out_is_accepted(self, tmp_path):
        result = _bash(
            f"V19_QUEUE_NO_MAIN=1 source '{LAUNCHERS['queue']}'; echo $WAVE_WALL_SECONDS",
            WS_ROOT=str(tmp_path / "root"),
        )
        assert int(result.stdout.strip()) > 0
