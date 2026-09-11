"""Launch-critical surface parity — adjacent-layer contracts (V19 audit).

Gate 0 attempt 1 (2026-07-29) failed pre-LLM because run_one_iteration.py
forwarded a kwarg (``runtime_watchdog_safety_factor``) that run_workflow()
did not accept: a caller/callee gap invisible to every existing test. The
same class of gap exists at every layer boundary of the launch path:

    shell (build_app_args) → Python CLI (argparse)
    run_one_iteration → run_workflow          (tests/unit/core/
                                               test_watchdog_admission_split.py)
    run_workflow → protocol functions
    protocol functions → Pydantic input schemas

This module closes the remaining boundaries statically:

* every flag the shell can emit is accepted by the Python CLI (an
  unrecognized flag is an argparse hard error at chain start);
* every kwarg run_workflow passes to a protocol function is accepted by
  that function's signature (a stray kwarg is a TypeError at runtime);
* every kwarg a protocol passes to a Pydantic input constructor is a
  declared field (or alias) — CRITICAL because the schemas do not set
  ``extra="forbid"``, so Pydantic v2 SILENTLY DROPS unknown constructor
  kwargs and the downstream consumer reads the field default instead of
  the operator's value. That failure mode is worse than attempt 1: it
  does not crash.

All checks are AST/introspection-based: no LLM, no training, no GPU.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHAIN_LIB = REPO_ROOT / "sdsc_submission_scripts" / "_chain_common.sh"
RUN_ONE_ITERATION = REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py"
WORKFLOW = REPO_ROOT / "src/workflows" / "model_exploration.py"
PROTOCOL_DIR = REPO_ROOT / "src/agent" / "schemas" / "protocols"

# Protocol functions run_workflow calls (workflows/model_exploration.py
# imports, lines 87-90 + 533). Update when the workflow gains an edge.
WORKFLOW_PROTOCOL_FUNCS = [
    ("agent.schemas.protocols.ml_model_impl_to_ml_model_valid", "local_all_fields"),
    ("agent.schemas.protocols.ml_model_propose_to_ml_model_impl", "local_full_spec"),
    ("agent.schemas.protocols.ml_model_valid_to_ml_model_tune", "local_validated_model"),
    ("agent.schemas.protocols.ml_result_interp_to_ml_model_propose", "local_full_context"),
    ("agent.schemas.protocols.ml_literature_review_to_ml_model_propose", "local_all_channels"),
]


# --------------------------------------------------------------------------
# AST helpers
# --------------------------------------------------------------------------


def _call_kwargs(tree: ast.AST, func_name: str) -> list[set[str]]:
    """Explicit keyword names of every ``func_name(...)`` call. Fails the
    calling test if a call uses **expansion (opaque to the parity check)."""
    all_calls: list[set[str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == func_name
        ):
            assert all(kw.arg is not None for kw in node.keywords), (
                f"{func_name}(...) uses **expansion — parity check cannot "
                "see through it; pass explicit keywords"
            )
            all_calls.append({kw.arg for kw in node.keywords if kw.arg})
    return all_calls


def _cli_flags() -> set[str]:
    """All argparse flags of run_one_iteration.py, including the automatic
    ``--no-<name>`` negatives of BooleanOptionalAction arguments."""
    tree = ast.parse(RUN_ONE_ITERATION.read_text())
    flags: set[str] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            continue
        names = [
            a.value
            for a in node.args
            if isinstance(a, ast.Constant) and str(a.value).startswith("--")
        ]
        flags.update(names)
        is_bool_optional = any(
            kw.arg == "action"
            and isinstance(kw.value, ast.Attribute)
            and kw.value.attr == "BooleanOptionalAction"
            for kw in node.keywords
        )
        if is_bool_optional:
            flags.update(f"--no-{n[2:]}" for n in names)
    assert flags, "no argparse flags found — extraction broken"
    return flags


def _shell_emitted_flags() -> set[str]:
    """Every flag build_app_args can put into APP_ARGS: the initial
    ``APP_ARGS=( ... )`` literal plus all ``APP_ARGS+=(--flag ...)``
    conditional emissions."""
    src = CHAIN_LIB.read_text()
    flags: set[str] = set(re.findall(r"APP_ARGS\+=\((--[a-z0-9_-]+)", src))
    m = re.search(r"^\s*APP_ARGS=\(\n(.*?)^\s*\)\n", src, re.M | re.S)
    assert m, "APP_ARGS=( ... ) initial block not found — extraction broken"
    flags.update(re.findall(r"(--[a-z0-9_-]+)", m.group(1)))
    assert len(flags) > 20, f"implausibly few emitted flags: {sorted(flags)}"
    return flags


# --------------------------------------------------------------------------
# Layer boundary: shell → Python CLI
# --------------------------------------------------------------------------


class TestShellToCli:
    def test_every_emittable_shell_flag_is_accepted_by_the_cli(self):
        unknown = _shell_emitted_flags() - _cli_flags()
        assert not unknown, (
            f"build_app_args can emit flags run_one_iteration.py rejects "
            f"(argparse hard error at chain start): {sorted(unknown)}"
        )


# --------------------------------------------------------------------------
# Layer boundary: run_workflow → protocol functions
# --------------------------------------------------------------------------


class TestWorkflowToProtocols:
    def test_every_protocol_call_kwarg_is_accepted(self):
        import importlib

        tree = ast.parse(WORKFLOW.read_text())
        checked = 0
        for module_name, func_name in WORKFLOW_PROTOCOL_FUNCS:
            func = getattr(importlib.import_module(module_name), func_name)
            sig = inspect.signature(func)
            has_var_kw = any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values())
            for call_kwargs in _call_kwargs(tree, func_name):
                checked += 1
                if has_var_kw:
                    continue
                unknown = call_kwargs - set(sig.parameters)
                assert not unknown, (
                    f"run_workflow passes kwargs {sorted(unknown)} that "
                    f"{func_name}() does not accept (runtime TypeError)"
                )
        assert checked >= len(WORKFLOW_PROTOCOL_FUNCS), (
            "some listed protocol functions are never called by "
            "run_workflow — update WORKFLOW_PROTOCOL_FUNCS"
        )


# --------------------------------------------------------------------------
# Layer boundary: protocol functions → Pydantic input schemas
# --------------------------------------------------------------------------


def _schema_registry() -> dict[str, type]:
    """name → BaseModel class for every schema importable from the
    agent.schemas package modules used by the protocols."""
    import importlib
    import pkgutil

    from pydantic import BaseModel

    import agent.schemas as schemas_pkg

    registry: dict[str, type] = {}
    for info in pkgutil.iter_modules(schemas_pkg.__path__):
        if info.ispkg:
            continue
        mod = importlib.import_module(f"agent.schemas.{info.name}")
        for name, obj in vars(mod).items():
            if inspect.isclass(obj) and issubclass(obj, BaseModel):
                registry[name] = obj
    assert "HyperparamTuningInput" in registry
    return registry


def _accepted_names(model_cls: type) -> set[str]:
    names = set(model_cls.model_fields)
    for field in model_cls.model_fields.values():
        if field.alias:
            names.add(field.alias)
    return names


class TestProtocolsToSchemas:
    def test_no_silently_dropped_constructor_kwarg(self):
        """Every keyword passed to a schema constructor inside a protocol
        module (or the workflow itself) must be a declared field/alias.
        The schemas default to extra='ignore', so a typo'd kwarg would NOT
        crash — the consumer would silently read the field default."""
        registry = _schema_registry()
        targets = [*sorted(PROTOCOL_DIR.glob("*.py")), WORKFLOW]
        checked = 0
        for path in targets:
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in registry
                ):
                    continue
                model_cls = registry[node.func.id]
                explicit = {kw.arg for kw in node.keywords if kw.arg is not None}
                unknown = explicit - _accepted_names(model_cls)
                assert not unknown, (
                    f"{path.name}: {node.func.id}(...) passes unknown "
                    f"field(s) {sorted(unknown)} — Pydantic would silently "
                    "drop them and the consumer would read defaults"
                )
                checked += 1
        assert checked >= 5, "schema-constructor extraction found too few calls"

    def test_tuning_input_covers_gate_launch_critical_fields(self):
        """The fields Gate 0 depends on exist on HyperparamTuningInput —
        guards against a rename that the ignore-extras behavior would
        otherwise mask at the protocol boundary."""
        from agent.schemas.hyperparam_tuning import HyperparamTuningInput

        required = {
            "runtime_watchdog_enabled",
            "runtime_safety_factor",
            "runtime_trial_safety_factor",
            "runtime_formal_safety_factor",
            "runtime_watchdog_safety_factor",
            "runtime_watchdog_floor_seconds",
            "runtime_verification_max_wall_seconds",
            "enable_structured_health_feedback",
            "health_feedback_history_window_iterations",
            "health_feedback_history_max_entries_per_model",
            # V21 PR D — the declared scientific posture. Launch-critical
            # because without it every formal record stamps
            # `legacy_authority_unknown` and can neither become the chain
            # incumbent nor enter the scientific aggregate.
            "healthgate_mode",
            "result_authority",
        }
        missing = required - set(HyperparamTuningInput.model_fields)
        assert not missing, f"missing launch-critical fields: {sorted(missing)}"
