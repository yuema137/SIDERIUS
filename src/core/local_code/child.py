"""Optional Python entry guard; existing callers still own all process supervision."""

from __future__ import annotations

import os
import runpy
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from core.local_code.capture import LocalCodeError
from core.local_code.failure import (
    FAILURE_ENV,
    REFUSAL_EXIT,
    FailureChannel,
    check_child_failure,
    code_package_failure,
    new_failure_channel,
    publish_failure,
    read_failure_channel,
)


@dataclass(frozen=True)
class ChildInvocation:
    argv: list[str]
    env: dict[str, str]
    channel: FailureChannel | None = None

    def check(self, returncode: int | None = None) -> None:
        check_child_failure(self.channel, returncode)


def prepare_child(argv: Sequence[str], environ: Mapping[str, str]) -> ChildInvocation:
    """Wrap only known Python forms under a captured package; never spawn here."""
    from core.local_code.binding import active_package
    from core.local_code.transport import DIGEST_ENV, MANIFEST_ENV

    env = dict(environ)
    if MANIFEST_ENV not in env and DIGEST_ENV not in env:
        return ChildInvocation(list(argv), env)
    package = active_package()
    if package is None:
        raise LocalCodeError("code_package child requires its captured parent binding")
    channel = read_failure_channel(env) or new_failure_channel(env, package.identity.digest)
    if channel.package_digest != package.identity.digest:
        raise LocalCodeError("code_package failure channel differs from captured package")
    if len(argv) < 2 or argv[0] != sys.executable:
        raise LocalCodeError("code_package child requires the current Python executable")
    target = list(argv[1:])
    if target[0] == "-m" and len(target) >= 2:
        mode, target = "module", target[1:]
    elif not target[0].startswith("-") and os.path.isfile(target[0]):
        mode = "script"
    else:
        raise LocalCodeError("code_package child supports only Python script files or -m modules")
    env[FAILURE_ENV] = channel.model_dump_json()
    command = [argv[0], "-m", "core.local_code.child", mode, *target]
    return ChildInvocation(command, env, channel)


def _run_target(args: list[str]) -> None:
    if len(args) < 2 or args[0] not in {"script", "module"}:
        raise LocalCodeError("code_package child guard requires script/module and target")
    mode, target, *arguments = args
    sys.argv = [target, *arguments]
    if mode == "script":
        if not os.path.isfile(target):
            raise LocalCodeError("code_package guarded script must be a file")
        runpy.run_path(target, run_name="__main__")
    else:
        runpy.run_module(target, run_name="__main__", alter_sys=True)


def _report_refusal(channel: FailureChannel | None, exc: LocalCodeError) -> int:
    print(f"[code_package_integrity] {exc}", file=sys.stderr)
    if channel is not None:
        try:
            publish_failure(channel, exc)
        except (OSError, LocalCodeError) as report_error:
            print(f"[code_package_integrity] report unavailable: {report_error}", file=sys.stderr)
    return REFUSAL_EXIT


def main(args: list[str] | None = None) -> int:
    from core.local_code.binding import active_package, bootstrap_code_package

    channel = None
    try:
        channel = read_failure_channel(os.environ)
        if channel is None:
            raise LocalCodeError("code_package guard requires a failure descriptor")
        bootstrap_code_package()
        package = active_package()
        if package is None or package.identity.digest != channel.package_digest:
            raise LocalCodeError("code_package guard descriptor differs from captured package")
        _run_target(sys.argv[1:] if args is None else args)
        check_child_failure(channel)
    except SystemExit as exc:
        check_child_failure(channel)
        if exc.code == REFUSAL_EXIT:
            print(f"ordinary target exit {REFUSAL_EXIT} remapped to exit 1", file=sys.stderr)
            return 1
        raise
    except Exception as exc:
        refusal = code_package_failure(exc)
        if refusal is None:
            check_child_failure(channel)
            raise
        return _report_refusal(channel, refusal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
