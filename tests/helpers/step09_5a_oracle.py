"""PRE/POST differential oracle for Step 09.5a (the workflow run-state prerequisite).

Step 09.5a moves ``run_workflow``'s run-scoped configuration and its
cross-iteration state onto typed carriers and collapses four duplicated
committed-digest readers to one authority. It must change **nothing** a caller,
a node, an artifact or the LLM can observe.

The failure class this module owns is *"this refactor moved something"*, and it
is the one failure no later commit can detect — a baseline reconstructed after
the migration proves nothing. So the snapshot is captured at C0, **before any
production edit**, and compared after.

WHAT IS OBSERVED, AND WHY THAT IS THE RIGHT BOUNDARY
-----------------------------------------------------
The 11 cross-iteration accumulators are *locals* inside ``run_workflow``; they
cannot be read from outside, and instrumenting them would pin the very shape the
refactor is allowed to change. What matters is not where the values live but
where they *arrive*: the node call envelopes, the persisted artifacts and the
returned results are the complete observable projection of that state. Comparing
those is what "behaviour-preserving" actually means here, and it stays valid
across a change of carrier.

The design doc (§24) is the authority for the captured surface.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

#: Values that legitimately differ between two runs of the same code. Each entry
#: is here because it is non-deterministic BY DESIGN, not because it was
#: inconvenient — normalising anything else would hide a real regression.
_VOLATILE_KEY_PATTERNS = (
    re.compile(r"^candidate_id$"),  # minted from uuid4 per proposal
    re.compile(r".*_at$"),  # started_at / finished_at / created_at
    re.compile(r"^timestamp$"),
    re.compile(r"^run_id$"),  # uuid when the caller does not pin one
    # Provenance, not behaviour: the hardware context stamps the current git
    # HEAD, so this changes on EVERY commit by design. Pinning it would make
    # the oracle fail once per commit for a reason unrelated to the refactor
    # — and a guard that cries wolf every commit gets re-baselined blind,
    # which is exactly how a real regression slips through.
    re.compile(r"^repo_commit$"),
    # arXiv P1 — the lock's generated-library PROVENANCE ({root, source}).
    # Under the suite's isolation fixture the root is a per-test tmp path, so
    # its value changes every run by construction, exactly like repo_commit.
    # The field is _PROVENANCE (recorded, never compared), so excluding it
    # from the oracle diff drops no behavioural surface; the field's own
    # stamping/omission semantics are owned by the P1 lock tests.
    re.compile(r"^generated_library$"),
    re.compile(r"^duration.*"),
    re.compile(r".*_seconds$"),
)

#: NOT volatile, deliberately. ``health_config_sha256`` was measured stable
#: across runs (7a4debd6… at capture, matching the composed-config sha the
#: Step-08b work recorded; 8949578d… since the C2 aggregation flip,
#: operator-frozen 2026-08-26 — a DECLARED policy delta, recorded in the
#: oracle test's docstring), and design §19 invariants 3-4 make it a FROZEN
#: CONTRACT: a run-state refactor that changed the effective-config hash
#: would have changed what the run reads. Normalising it away would delete
#: the only signal.


#: Fields that identify the MACHINE, not the workflow. The hardware context is
#: resolved once at startup and threaded to the nodes; that it arrives, and with
#: which field set, is behaviour. Which GPU, driver, kernel and hostname
#: answered is environment — and this oracle must run on a CI runner with no GPU
#: as well as on a developer box with an RTX 5090.
_HARDWARE_MARKERS = ("device_name", "device_available")


def _is_hardware_context(value: dict) -> bool:
    return all(m in value for m in _HARDWARE_MARKERS)


def _normalise(value: Any, workspace: str, data_dir: str) -> Any:
    """Make a captured value comparable across runs and machines.

    Absolute paths are rewritten to ``<WS>`` / ``<DATA>`` placeholders so the
    snapshot does not encode a ``tmp_path``. Volatile keys are replaced by a
    sentinel rather than dropped, so a field *disappearing* is still visible.

    A hardware-context object is reduced to its sorted FIELD SET. That keeps
    everything this refactor could break — the object is resolved, complete and
    delivered — while dropping values that differ between an RTX 5090 box and a
    GPU-less CI runner. Pinning the values would make the oracle fail on every
    machine but one, which is how a guard gets re-baselined blind.
    """
    if isinstance(value, dict) and _is_hardware_context(value):
        return {"<hardware_context_fields>": sorted(value)}
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if any(p.match(k) for p in _VOLATILE_KEY_PATTERNS):
                out[k] = "<VOLATILE>" if v is not None else None
            else:
                out[k] = _normalise(v, workspace, data_dir)
        return out
    if isinstance(value, (list, tuple)):
        return [_normalise(v, workspace, data_dir) for v in value]
    if isinstance(value, str):
        s = value.replace(workspace, "<WS>").replace(data_dir, "<DATA>")
        # tmp_path itself may appear one level above the workspace
        return re.sub(r"/tmp/[^\s\"']*pytest[^\s\"']*", "<TMP>", s)
    return value


def _dump(obj: Any) -> Any:
    """Best-effort JSON projection of a node input/output object."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except Exception:  # pragma: no cover - defensive
            return {"<unserialisable>": type(obj).__name__}
    if isinstance(obj, dict):
        return {k: _dump(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_dump(v) for v in obj]
    return f"<{type(obj).__name__}>"


def _artifact_tree(root: Path, workspace: str, data_dir: str) -> dict[str, Any]:
    """Every persisted file under the run root: path -> normalised content.

    JSON is compared structurally (a key reordering is not a regression); any
    other file is recorded by size only, because this workflow writes no binary
    artifact whose bytes are a contract at this layer.

    ``memory_trace.jsonl`` is the one exception and is recorded by **event
    count**. Its payload is live RSS/VMS, which varies with whatever ran before
    in the same process — a run measured 393 vs 396 bytes purely because the
    interpreter was carrying more memory. The number of probe EVENTS is
    behaviour (start / end / post_gc per iteration); the measured megabytes are
    environment. Pinning the bytes would have made this oracle fail for a reason
    that has nothing to do with the refactor.
    """
    out: dict[str, Any] = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root))
        if p.name == "memory_trace.jsonl":
            events = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
            # Lists, not tuples: the golden round-trips through JSON, and a
            # tuple would come back a list and diff against itself forever.
            # Keys per `core/memory_probe.py:101` — "iter", not "iter_idx".
            out[rel] = {
                "<probe_events>": [[e.get("scope"), e.get("iter"), e.get("phase")] for e in events]
            }
        elif p.suffix == ".json":
            try:
                out[rel] = _normalise(json.loads(p.read_text()), workspace, data_dir)
            except json.JSONDecodeError:
                out[rel] = {"<invalid-json>": p.stat().st_size}
        else:
            out[rel] = {"<bytes>": p.stat().st_size}
    return out


#: The startup side-effect order the design freezes (§3.8, §18). Recording the
#: ORDER is the point: a run-state refactor is exactly the kind of change that
#: silently moves `build_run_invariants` after `ensure_run_invariants`.
_ORDER_PROBES = (
    "_snapshot_task_config",
    "get_or_create_hardware_context",
    "build_run_invariants",
    "run_launch_self_test",
    "ensure_run_invariants",
    "_get_reasoning_pipeline",
)


def capture_workflow_snapshot(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    """Run one bounded pseudo-mode workflow and return its observable envelope.

    All five agent classes are mocked, so no LLM call, no training and no
    subprocess occurs. ``overrides`` are merged into the ``run_workflow`` call so
    the caller can vary iteration count without duplicating the harness.
    """
    # Imported lazily: the factories live with the existing workflow tests, and
    # importing them at module scope would make this helper's import order
    # depend on that module's collection.
    from tests.unit.workflows.test_model_exploration import (
        _make_implementor_output,
        _make_interpretation_output,
        _make_proposal_output,
        _make_tune_output,
        _make_validator_output,
        _write_tuning_output,
    )
    from workflows import model_exploration as me

    _write_tuning_output(tmp_path, "punet")
    workspace = str(tmp_path / "workflow_output")
    data_dir = str(tmp_path / "data")
    run_name = "c0_oracle"

    order: list[str] = []

    def _probe(name: str, real: Any) -> Any:
        def wrapper(*a: Any, **kw: Any) -> Any:
            order.append(name)
            return real(*a, **kw)

        return wrapper

    with (
        patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
        patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
    ):
        MockInterp.return_value.run.return_value = _make_interpretation_output()
        MockPropose.return_value.run.return_value = _make_proposal_output()
        MockImpl.return_value.run.return_value = _make_implementor_output()
        MockValid.return_value.run.return_value = _make_validator_output(passed=True)
        MockTune.return_value.run.return_value = _make_tune_output()

        patches = []
        for name in _ORDER_PROBES:
            if hasattr(me, name):
                patches.append(patch.object(me, name, _probe(name, getattr(me, name))))
        for p in patches:
            p.start()
        try:
            # Step 09.5a C3: transit configuration is one carrier. The
            # overrides are split by ownership so callers keep passing a flat
            # bag and the snapshot surface is unchanged.
            from workflows.run_config import WorkflowLaunchConfig, launch_config_field_names

            launch_kwargs: dict[str, Any] = {
                "data_dir": data_dir,
                "model_types": ["punet"],
                "source_run_name": "v1",
            }
            call: dict[str, Any] = {"workspace": workspace, "run_name": run_name}
            launch_fields = launch_config_field_names()
            for key, value in overrides.items():
                (launch_kwargs if key in launch_fields else call)[key] = value
            results = me.run_workflow(launch=WorkflowLaunchConfig(**launch_kwargs), **call)
        finally:
            for p in patches:
                p.stop()

        def envelope(mock: Any, label: str) -> dict[str, Any]:
            ctor = mock.call_args
            runs = [c for c in mock.return_value.run.call_args_list]
            return {
                "constructed": ctor is not None,
                "ctor_kwargs": sorted((ctor.kwargs or {}).keys()) if ctor else [],
                "run_count": len(runs),
                "run_inputs": [
                    _normalise(_dump(c.args[0] if c.args else c.kwargs), workspace, data_dir)
                    for c in runs
                ],
                "label": label,
            }

        snapshot = {
            "node_calls": {
                "interpretation": envelope(MockInterp, "interpretation"),
                "proposal": envelope(MockPropose, "proposal"),
                "implementor": envelope(MockImpl, "implementor"),
                "validator": envelope(MockValid, "validator"),
                "tuner": envelope(MockTune, "tuner"),
            },
            "startup_side_effect_order": order,
            "results": _normalise(_dump(results), workspace, data_dir),
            "artifacts": _artifact_tree(Path(workspace), workspace, data_dir),
        }
    return snapshot


def load_or_write_golden(path: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the committed golden, writing it once when it does not exist.

    Regeneration is deliberately NOT automatic on mismatch: a golden that
    rewrites itself when the code changes records the change instead of catching
    it. Delete the file explicitly to re-baseline.
    """
    if os.environ.get("SIDERIUS_REWRITE_STEP095A_ORACLE") == "1" or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    return json.loads(path.read_text())
