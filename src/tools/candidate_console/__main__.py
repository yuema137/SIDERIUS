"""Explicit single-process loopback console; no reload or proxy trust."""

import argparse
import sys

from .config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Local configured candidate console")
    parser.add_argument("command", choices=("check", "serve"))
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
    except (OSError, ValueError):
        print(
            "Console configuration is invalid or unavailable; check paths and private file permissions.",
            file=sys.stderr,
        )
        return 2
    print(f"Console: {config.browser_origin}; access token file: {config.auth_token_file}")
    if args.command == "serve":
        import uvicorn

        from .app import create_app

        uvicorn.run(
            create_app(config),
            host=config.bind_host,
            port=config.port,
            proxy_headers=False,
            access_log=False,
            workers=1,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
