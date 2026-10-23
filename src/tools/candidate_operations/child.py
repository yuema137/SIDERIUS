"""One operation process: publish identity, invoke native owner, record references."""

import sys
from pathlib import Path
from uuid import UUID

from tools.candidate_prepare import prepare_candidate
from tools.candidate_worker import launch_candidate

from .files import canonical, publish, read_model
from .models import Completion, OperationRecord
from .process import current_identity, runtime_identity
from .read import native_receipt
from .store import load_record


def execute(path: Path) -> int:
    canonical(str(path))
    # No caller-selected executable or callable; the directory UUID binds the record.
    seed = read_model(path / "request.json", OperationRecord, private_file=True)
    record = load_record(seed.config, UUID(path.name))
    expected = Path(record.config.state_root) / "operations" / str(record.submission.request_id)
    if path != expected:
        raise ValueError("operation directory disagrees with request")
    publish(path / "process.json", current_identity(record))
    entered = False
    try:
        if runtime_identity() != record.runtime:
            raise ValueError("operation runtime binding changed")
        entered = True
        if record.submission.kind == "prepare":
            prepare_candidate(record.submission.request)
        else:
            launch_candidate(record.submission.request)
        native = native_receipt(record)
        if native is None:
            raise ValueError("native invocation returned without final receipt")
        completion = Completion(
            operation_id=record.submission.request_id,
            request_digest=record.request_digest,
            outcome="native",
            receipt_digest=native[1],
            reason="native_terminal",
        )
    except (Exception, KeyboardInterrupt):
        # Do not serialize exception messages: arbitrary plugins can include credentials.
        completion = Completion(
            operation_id=record.submission.request_id,
            request_digest=record.request_digest,
            outcome="unknown" if entered else "pre_dispatch_failure",
            reason="native_outcome_unresolved" if entered else "runtime_binding_failed",
        )
    publish(path / "completion.json", completion)
    return 0 if completion.outcome == "native" else 1


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    try:
        return execute(Path(sys.argv[1]))
    except (Exception, KeyboardInterrupt):
        print("operation wrapper could not publish a trusted outcome", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
