"""Preview, check or run an explicitly configured orchestration sandbox."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

from pydantic import ValidationError

from tools.workspace_sandbox.command import SandboxUnavailable, build_command
from tools.workspace_sandbox.profile import SandboxProfile, runtime_roots
from tools.workspace_sandbox.runner import run


def _probe(profile: SandboxProfile) -> list[str]:
    # No provider calls, model imports, dataset reads or persistent probe artifacts.
    roots = [str(path) for path in (*runtime_roots(), *profile.read_only)]
    code = f"""
import json, os, tempfile
from pathlib import Path
import pydantic
import tools.workspace_sandbox
for root in {roots!r}:
    assert os.statvfs(root).f_flag & os.ST_RDONLY, 'not read-only: ' + root
with tempfile.TemporaryDirectory(prefix='.sandbox-check-', dir={str(profile.workspace)!r}) as directory:
    (Path(directory) / 'write-check').write_text('ok')
with tempfile.TemporaryDirectory() as directory:
    (Path(directory) / 'write-check').write_text('ok')
print(json.dumps({{'status': 'passed', 'checks': ['python imports', 'read-only mounts', 'workspace write', 'private tmp write']}}))
"""
    return [sys.executable, "-c", code]


class _Termination(KeyboardInterrupt):
    """Ensure CLI termination unwinds the runner and cleans its namespace."""


def _terminate(signum: int, frame: object) -> None:
    raise _Termination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "check", "run"))
    parser.add_argument(
        "profile", type=Path, help="JSON profile; only environment variable names, never values"
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, help="run: -- executable arg ...")
    args = parser.parse_args(argv)
    previous_term = signal.signal(signal.SIGTERM, _terminate)
    try:
        profile = SandboxProfile.model_validate_json(args.profile.read_bytes())
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if args.action != "run" and command:
            raise ValueError("only run accepts a command")
        if args.action == "preview":
            build_command(profile, [sys.executable, "-c", "pass"])
            print(
                json.dumps(
                    {
                        "profile": profile.model_dump(mode="json"),
                        "runtime_read_only": [str(root) for root in runtime_roots()],
                        "status": "not_run",
                    },
                    indent=2,
                )
            )
            return 0
        result = run(profile, _probe(profile) if args.action == "check" else command)
        print(result.model_dump_json(), file=sys.stderr)
        if args.action == "check" and result.status != "completed":
            print(
                "Sandbox check failed. Inspect the error above; verify bubblewrap/user namespaces and declared runtime paths. No unsandboxed fallback was attempted.",
                file=sys.stderr,
            )
        return result.returncode if result.returncode >= 0 else 128 - result.returncode
    except (ValidationError, ValueError, OSError, SandboxUnavailable) as exc:
        print(f"workspace sandbox refused: {exc}", file=sys.stderr)
        return 2
    except _Termination:
        return 143
    except KeyboardInterrupt:
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous_term)


if __name__ == "__main__":
    raise SystemExit(main())
