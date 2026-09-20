"""The tuner NODE's source, as one text — for structural / reachability tests.

Step 07 PR 07b, C7. Before the decomposition the node was one file, so a test
asking *"does the tuner call X?"* could read
``nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`` and be
right. After it, the node is a main module plus five node-local submodules, and
that same question is still about the NODE — not about which of its files
happens to hold the call today.

So the scanning tests read this instead. Two consequences worth stating:

* **The property under test is unchanged.** A call site that moved from the
  main module into ``runtime.py`` is still a call the node makes; a helper that
  must NOT appear on a failure path must not appear on it in any of the files.
  Concatenating preserves both the presence and the *count* assertions those
  tests make.
* **The scan got STRICTER, not looser.** A forbidden pattern can no longer hide
  by moving one file sideways, which is exactly the failure mode a refactor
  invites.

Tests that genuinely care about ONE file (for example "this literal is not in
the prompt template") should keep reading that file directly — this helper is
for claims about the node as a unit.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: The node's package directory.
TUNER_PACKAGE = Path(__file__).resolve().parents[2] / "src/nodes" / "ml_hyperparameter_tune_agent"

#: The main module — still the node's entrypoint and orchestrator.
TUNER_MAIN = TUNER_PACKAGE / "ml_hyperparameter_tune_agent.py"

#: The node-local submodules, in dependency order (leaves first).
TUNER_SUBMODULES = (
    TUNER_PACKAGE / "contracts.py",
    TUNER_PACKAGE / "policy.py",
    TUNER_PACKAGE / "records.py",
    TUNER_PACKAGE / "runtime.py",
    TUNER_PACKAGE / "feedback.py",
    TUNER_PACKAGE / "planning.py",
    TUNER_PACKAGE / "external_evaluation.py",
    TUNER_PACKAGE / "execution.py",
    TUNER_PACKAGE / "cli.py",
)

#: The functions the run loop executes, in lifecycle order. Together with
#: ``run()`` itself these ARE the production path of one round: planning, the
#: three execution phases, the record it builds, and the output it finalizes.
#:
#: Reachability tests use this rather than the node as a whole. The distinction
#: matters: "the node contains this call" is satisfied by dead code, whereas
#: "the lifecycle contains this call" still fails when the call is deleted from
#: the path — which is the property those tests were written to defend.
TUNER_LIFECYCLE = (
    ("ml_hyperparameter_tune_agent", "HyperparamTuningAgent.run"),
    ("planning", "prepare_attempt"),
    ("execution", "run_admission_preflight"),
    ("execution", "run_training"),
    ("execution", "run_inference_scoring_health"),
    ("execution", "_run_evaluation_phase"),
    ("execution", "_run_local_evaluation_phase"),
    ("external_evaluation", "run_external_evaluation"),
    ("records", "build_attempt_record"),
    ("records", "finalize_run_output"),
)


def tuner_node_files() -> tuple[Path, ...]:
    """Every file that makes up the tuner node."""
    return (TUNER_MAIN, *TUNER_SUBMODULES)


def tuner_node_source() -> str:
    """The whole node's source as one string.

    Files are joined with a newline so a pattern cannot accidentally match
    across a file boundary.
    """
    return "\n".join(p.read_text(encoding="utf-8") for p in tuner_node_files())


def tuner_lifecycle_source() -> str:
    """The source of ``run()`` and every phase it executes, as one text.

    The successor to ``inspect.getsource(HyperparamTuningAgent.run)`` for tests
    that assert the run loop reaches a boundary. Before C7d the whole lifecycle
    was inlined in ``run()``, so reading that one function was the same thing;
    it no longer is, and reading only ``run()`` would now pass a test whose
    subject had been deleted from the path.
    """
    import importlib
    import inspect

    out: list[str] = []
    for module_name, qualname in TUNER_LIFECYCLE:
        mod = importlib.import_module(f"nodes.ml_hyperparameter_tune_agent.{module_name}")
        obj = mod
        for part in qualname.split("."):
            obj = getattr(obj, part)
        out.append(inspect.getsource(obj))
    return "\n".join(out)


def tuner_node_tree() -> ast.Module:
    """The whole node parsed as one tree, for AST-level structural claims.

    The counterpart to :func:`tuner_node_source` for tests that walk nodes
    rather than match strings. Concatenated module sources parse cleanly —
    repeated imports are legal — and every definition keeps its own body, so
    call-site and definition scans are unaffected by which file now holds them.
    """
    return ast.parse(tuner_node_source())
