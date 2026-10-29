"""Explicit single-process loopback console; no reload or proxy trust."""

import argparse
import contextlib
import sys
from urllib.parse import urlsplit

from pydantic import ValidationError

from .config import load_console
from .config_errors import MissingConfigFile, invalid_config_fields
from .files import config_bytes
from .readiness_models import WorkspaceReadiness
from .settings_file import MissingSetting, SettingsInvalid
from .settings_models import ResolvedConsole
from .workspace import (
    DEFAULT_PORT,
    CredentialFileNotAdded,
    WorkspaceRefused,
    init_workspace,
    resolve_console,
    workspace_readiness,
)

INVALID = (
    "Console configuration is invalid or unavailable; check paths and private file permissions."
)


def _print_readiness(readiness: WorkspaceReadiness | None) -> None:
    if readiness is None or readiness.ready:
        return
    for entry in readiness.entries:
        if entry.status != "present" and entry.created_by != "writer":
            print(f"Workspace {entry.name}: {entry.status}", file=sys.stderr)
    if readiness.init_command is not None:
        print(f"Create missing workspace folders with: {readiness.init_command}", file=sys.stderr)


def _load(path: str) -> ResolvedConsole | None:
    try:
        return load_console(path)
    except MissingSetting as error:
        print(f"Console configuration is incomplete: {error}.", file=sys.stderr)
    except SettingsInvalid as error:
        print(f"Console settings are invalid: {error}.", file=sys.stderr)
    except ValidationError as error:
        for message in invalid_config_fields(error):
            print(message, file=sys.stderr)
    except MissingConfigFile as error:
        print(error, file=sys.stderr)
    except (OSError, ValueError):
        print(INVALID, file=sys.stderr)
        # Name unusable workspace folders when the file itself resolves.
        with contextlib.suppress(OSError, ValueError):
            _print_readiness(workspace_readiness(resolve_console(config_bytes(path))))
    return None


def _print_credential_line(error: CredentialFileNotAdded) -> None:
    """init never rewrites an existing console.json: name the one member to add or change."""
    print(
        "Workspace folders are ready, but settings/console.json already exists and init "
        "never rewrites it.",
        file=sys.stderr,
    )
    if error.replaces:
        print(
            "It names a different credential_file. Replace the value on that line so it "
            "reads as below, keeping the line's trailing comma if it has one:",
            file=sys.stderr,
        )
        print(f"  {error.member}", file=sys.stderr)
    else:
        print(
            "It has no credential_file. Add this line right after its opening {:",
            file=sys.stderr,
        )
        print(f"  {error.member},", file=sys.stderr)
    print(
        "Then check the configuration (and restart the console if it is running):", file=sys.stderr
    )
    print(
        f"  .venv/bin/python -m tools.candidate_console check --config {error.config_path}",
        file=sys.stderr,
    )


def _report(resolved: ResolvedConsole) -> None:
    """Access instructions, workspace readiness and GPU prerequisite warnings."""
    from .package_mounts import gpu_warnings

    config = resolved.config
    browser_port = urlsplit(config.browser_origin).port
    print(f"Console address: {config.browser_origin}")
    print(f"Access token file: {config.auth_token_file}")
    print("  The console asks for this token when you connect, on this machine or remotely.")
    print(f"  Show it with: cat {config.auth_token_file}")
    print("  On this machine: open the console address in your browser.")
    print("  On a remote server: first run on your own computer")
    print(f"    ssh -N -L 127.0.0.1:{browser_port}:127.0.0.1:{config.port} YOUR_HOST")
    print("  then open the console address there.")
    _print_readiness(workspace_readiness(resolved))
    for warning in gpu_warnings(config):
        print(f"Warning: {warning}", file=sys.stderr)


def _add_task(argv: list[str]) -> int:
    from .add_task import run_command as add_task

    status, config_path = add_task(argv)
    if config_path is None:
        return status
    resolved = _load(config_path)
    if resolved is None:
        print(
            "The task was added, but check failed: fix the problem above, run check again, "
            "then restart the console to load the new task.",
            file=sys.stderr,
        )
        return 2
    _report(resolved)
    print("Restart the console to load the new task.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["add-task"]:
        return _add_task(argv[1:])
    parser = argparse.ArgumentParser(
        description="Local configured candidate console; register a task with: add-task --help"
    )
    parser.add_argument("command", choices=("check", "serve", "init"))
    parser.add_argument("--config", help="console.json path (check, serve)")
    parser.add_argument(
        "--workspace",
        help="existing parent directory for siderius_workspace/ (init only; no default)",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="init only")
    parser.add_argument(
        "--credential-file",
        help=(
            "init only: absolute path of your private API key file (mode 600); "
            "recorded as credential_file in a new console.json; values are never printed"
        ),
    )
    parser.add_argument(
        "--gpu",
        action="store_true",
        help=(
            "check only: start CUDA inside the run sandbox for each task that lists a "
            "/dev/nvidia<N> device (no network, no model calls)"
        ),
    )
    parser.add_argument("--task", help="check --gpu only: probe just this task ID")
    args = parser.parse_args(argv)
    if (args.gpu or args.task is not None) and args.command != "check":
        parser.error("--gpu and --task are for check only")
    if args.task is not None and not args.gpu:
        parser.error("--task requires --gpu")
    if args.command == "init":
        if args.workspace is None or args.config is not None:
            parser.error("init requires --workspace and takes no --config")
        try:
            config_path = str(
                init_workspace(args.workspace, port=args.port, credential_file=args.credential_file)
            )
        except CredentialFileNotAdded as error:
            _print_credential_line(error)
            return 2
        except WorkspaceRefused as error:
            print(f"Workspace init refused: {error}. Nothing was deleted.", file=sys.stderr)
            return 2
        except MissingSetting as error:
            print(
                f"Workspace init stopped: console.json is incomplete: {error}. "
                "Nothing was deleted.",
                file=sys.stderr,
            )
            return 2
        except SettingsInvalid as error:
            print(
                f"Workspace init stopped: console settings are invalid: {error}. "
                "Nothing was deleted.",
                file=sys.stderr,
            )
            return 2
        except ValidationError as error:
            for message in invalid_config_fields(error):
                print(message, file=sys.stderr)
            print("Nothing was deleted.", file=sys.stderr)
            return 2
        except (OSError, ValueError):
            print(
                "Workspace init failed: a filesystem operation was refused. Nothing was deleted.",
                file=sys.stderr,
            )
            return 2
        print(f"Workspace configuration: {config_path}")
    else:
        if args.config is None or args.workspace is not None:
            parser.error(f"{args.command} requires --config and takes no --workspace")
        if args.credential_file is not None:
            parser.error("--credential-file is for init only")
        config_path = args.config
    resolved = _load(config_path)
    if resolved is None:
        return 2
    config = resolved.config
    _report(resolved)
    if args.gpu:
        from .gpu_check import check_gpu

        return check_gpu(config, args.task)
    if args.command == "serve":
        import uvicorn

        from .app import create_app

        uvicorn.run(
            create_app(config, resolved.settings),
            host=config.bind_host,
            port=config.port,
            proxy_headers=False,
            access_log=False,
            workers=1,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
