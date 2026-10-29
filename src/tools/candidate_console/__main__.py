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


def main() -> int:
    parser = argparse.ArgumentParser(description="Local configured candidate console")
    parser.add_argument("command", choices=("check", "serve", "init"))
    parser.add_argument("--config", help="console.json path (check, serve)")
    parser.add_argument(
        "--workspace",
        help="existing parent directory for siderius_workspace/ (init only; no default)",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="init only")
    args = parser.parse_args()
    if args.command == "init":
        if args.workspace is None or args.config is not None:
            parser.error("init requires --workspace and takes no --config")
        try:
            config_path = str(init_workspace(args.workspace, port=args.port))
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
        config_path = args.config
    resolved = _load(config_path)
    if resolved is None:
        return 2
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
