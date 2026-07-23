"""
DS6d — run_comparison DataScope/HealthGate surfaces.

Covers: spec parsing + v17_pregate override pin at main() startup (both fail
before any workspace/phase work), and run_agent forwarding the operator's
raw spec strings to the tuner subprocess CLI.
See docs/design/enable_partial_file_list.md (Commit DS6).
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.run_comparison import run_agent


def _main(argv: list[str]) -> None:
    from scripts import run_comparison

    with patch.object(sys, "argv", ["run_comparison.py", *argv]):
        run_comparison.main()


class TestMainStartupGuards:
    def test_malformed_data_scope_exits(self):
        with pytest.raises(SystemExit, match="malformed"):
            _main(["--model", "punet", "--data_scope", "4-x"])

    def test_v17_pregate_forbids_health_gate_files(self):
        with pytest.raises(SystemExit, match="pins its HealthGate policy"):
            _main(
                [
                    "--model",
                    "wavenet",
                    "--run_name",
                    "v17_pregate_baseline",
                    "--health_gate_files",
                    "4,7,9",
                ]
            )

    def test_v17_pregate_forbids_disabling_gates(self):
        with pytest.raises(SystemExit, match="pins its HealthGate policy"):
            _main(
                [
                    "--model",
                    "wavenet",
                    "--run_name",
                    "v17_pregate_baseline",
                    "--no-health_gate_enabled",
                ]
            )


class TestRunAgentForwarding:
    def _cmd(self, **kwargs) -> list[str]:
        with patch("scripts.run_comparison.subprocess.run") as mock_run:
            mock_run.return_value = SimpleNamespace(returncode=0)
            with patch("scripts.run_comparison._verify_agent_completion", create=True):
                try:
                    run_agent(
                        model_type="punet",
                        agent_workspace="/tmp/ws",
                        agent_run_name="r1",
                        provider="gemini",
                        model_id="m",
                        max_rounds=1,
                        **kwargs,
                    )
                except BaseException:
                    # Post-subprocess completion verification sys.exit(2)s on
                    # the empty workspace (PR #121 partial-exit contract) —
                    # the launched cmd is all this test needs.
                    pass
            return mock_run.call_args.args[0]

    def test_specs_forwarded_verbatim(self):
        cmd = self._cmd(data_scope_spec="4-9", health_gate_files_spec="4,7,9")
        assert "--data_scope" in cmd and cmd[cmd.index("--data_scope") + 1] == "4-9"
        assert "--health_gate_files" in cmd and cmd[cmd.index("--health_gate_files") + 1] == "4,7,9"
        assert "--no-health_gate_enabled" not in cmd

    def test_disabled_gates_forwarded(self):
        cmd = self._cmd(health_gate_enabled=False)
        assert "--no-health_gate_enabled" in cmd
        assert "--data_scope" not in cmd

    def test_defaults_forward_nothing(self):
        cmd = self._cmd()
        assert "--data_scope" not in cmd
        assert "--health_gate_files" not in cmd
        assert "--no-health_gate_enabled" not in cmd
