"""Single native child wrapper; iteration scheduling remains in run_chain.sh."""

from tools.native_chain.check import (
    CHECK_ERRORS,
    launch_context,
    parse_check,
    print_refusal,
    verify_dispatch,
)
from tools.native_chain.models import NativeChainDispatch
from workflows.native_chain_binding import NativeChainCaptureRefusal


def main() -> int:
    try:
        args, reference, argv = parse_check()
        if args.command != "dispatch":
            raise ValueError("dispatch_required")
        dispatch = NativeChainDispatch(capture=reference, iteration=args.iteration, argv=argv)
        capture = verify_dispatch(dispatch)
        context = launch_context(capture, dispatch.iteration)
    except CHECK_ERRORS as error:
        print_refusal(error)
        return 78
    from workflows.run_one_iteration import main as native_main

    try:
        native_main(list(dispatch.argv), chain_capture=context)
    except NativeChainCaptureRefusal as error:
        print_refusal(error)
        return 78
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
