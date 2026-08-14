"""No model-NAME may govern a dtype cast on a migrated surface — Step 03.

Design:
``docs/design/generic_framework_upgrade/step_03_model_loss_contract.md``
**§4a.1 AMENDMENT A-1**, §24.10 (guardrail coverage), §21; roadmap §15.1's
Step-3 A-cell, *"guardrail targets extended"*.

**Why a second guardrail module rather than a row in `_SCAN_TARGETS`.**
`test_no_model_name_branches.py` bans architecture-name TOKENS outright
across the estimation surface. Pointing it at
`execute_tools/train_engine_sandbox.py` and
`execute_tools/inference_single.py` would flag the three CONSTRUCTOR
branches that finding F-2 deliberately leaves in place — `fcnet` takes a
`loss_type` kwarg the others do not, a constructor-signature difference no
Model-I/O semantic backs. Clearing that would mean inventing a
consumer-less contract field, which §21 forbids. So the token ban is the
wrong instrument here.

What Step 03 actually has to prevent is narrower and exact: **a model name
deciding a dtype**. This module states that as a semantic property over
the AST — an ``if`` comparing against a model-name literal whose body
performs a dtype operation — rather than as a count or a line number
(§24.10: *"detect semantic reintroduction, not merely today's exact line
numbers"*).

That distinction is the whole point. A regression here would be
behaviourally INVISIBLE under TIDMAD: re-hardcoding
``input_seq.float() if model_cfg.model_type == "fcnet" else
input_seq.int()`` reproduces baseline A6 exactly, so no behavioural oracle
in the suite can see it. Only a structural claim can.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

#: The execution surfaces Step 03 migrated. Extending this list is how a
#: future step declares a surface contract-routed.
MIGRATED_SURFACES = (
    "execute_tools/train_engine_sandbox.py",
    "execute_tools/inference_single.py",
)

#: Architecture names, matching the sibling guardrail's vocabulary.
_MODEL_NAMES = frozenset({"wavenet", "punet", "fcnet", "rnn", "transformer", "cnn", "gated_fno"})

#: Attribute calls that UNAMBIGUOUSLY change a tensor's dtype.
#:
#: ``.to(...)`` is deliberately NOT here. It is overloaded — ``.to(device)``
#: moves a tensor between devices and ``.to(torch.int32)`` recasts it — and
#: treating the two alike flags the F-2 constructor branches, which really do
#: end in ``.to(device)``. ``.to`` is handled separately, by inspecting its
#: argument.
_DTYPE_CALLS = frozenset({"int", "long", "float", "double", "half", "bfloat16", "type"})

#: Names that identify a dtype when passed to ``.to()``.
_DTYPE_TOKENS = frozenset(
    {
        "int8",
        "int16",
        "int32",
        "int64",
        "long",
        "float16",
        "float32",
        "float64",
        "bfloat16",
        "double",
        "half",
        "bool",
        "complex64",
        "complex128",
    }
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _compares_a_model_name(node: ast.AST) -> bool:
    """True when the expression compares anything against a model-name."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Compare):
            operands = [sub.left, *sub.comparators]
            for operand in operands:
                if isinstance(operand, ast.Constant) and operand.value in _MODEL_NAMES:
                    return True
    return False


def _is_dtype_valued(node: ast.expr) -> bool:
    """True when an expression denotes a dtype rather than, say, a device."""
    if isinstance(node, ast.Attribute) and node.attr in _DTYPE_TOKENS:
        return True  # torch.int32
    if isinstance(node, ast.Name) and node.id.lower().endswith("dtype"):
        return True  # a local named `..._dtype`
    if isinstance(node, ast.Call):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        return "dtype" in name.lower()  # resolve_input_dtype(...)
    return False


def _performs_a_dtype_operation(nodes: list[ast.stmt]) -> bool:
    """True when any statement recasts a tensor's dtype.

    Device moves are excluded on purpose: ``.to(device)`` is not a dtype
    decision, and conflating them would flag the F-2 constructor branches
    that Step 03 deliberately leaves in place.
    """
    for stmt in nodes:
        for sub in ast.walk(stmt):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            if isinstance(func, ast.Attribute):
                if func.attr in _DTYPE_CALLS:
                    return True
                if func.attr == "to":
                    if any(kw.arg == "dtype" for kw in sub.keywords):
                        return True
                    if any(_is_dtype_valued(arg) for arg in sub.args):
                        return True
    return False


def _dtype_name_branches(source: str) -> list[str]:
    """Every place a model-name comparison governs a dtype operation.

    Covers both statement form (``if name == "fcnet": x = x.float()``) and
    the expression form the migrated code actually used
    (``x.float() if name == "fcnet" else x.int()``), because collapsing one
    into the other is a one-line edit.
    """
    tree = ast.parse(source)
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _compares_a_model_name(node.test):
            if _performs_a_dtype_operation(node.body + node.orelse):
                offenders.append(f"line {node.lineno}: if-statement on a model name casts a dtype")

        if isinstance(node, ast.IfExp) and _compares_a_model_name(node.test):
            if _performs_a_dtype_operation(
                [ast.Expr(value=node.body), ast.Expr(value=node.orelse)]
            ):
                offenders.append(
                    f"line {node.lineno}: conditional expression on a model name casts a dtype"
                )

    return offenders


@pytest.mark.parametrize("relative_path", MIGRATED_SURFACES)
def test_no_model_name_governs_a_dtype_on_a_migrated_surface(relative_path):
    """The Step-03 invariant, stated structurally."""
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    offenders = _dtype_name_branches(source)
    assert offenders == [], (
        f"{relative_path}: a model NAME decides a dtype again. Step 03 routes "
        "the model-boundary dtype through the declared admissibility "
        "(execute_tools/model_input_dtype.resolve_input_dtype); a name may key "
        f"a DECLARATION but must never be the condition. {offenders}"
    )


class TestTheGuardActuallyDetects:
    """Reachability — a guard nobody proved catches anything is decoration.

    The sibling guardrail's own history is the argument: while a label sat
    in its pending-cleanup dict, a REINTRODUCED name branch was reported as
    ``xfail`` instead of ``failed``, so the guard detected the regression
    and then tolerated it.
    """

    def test_it_catches_the_exact_expression_form_that_was_removed(self):
        """Verbatim from `train_engine_sandbox.py:660` before M5."""
        source = (
            "def f(model_cfg, input_seq):\n"
            '    input_seq = input_seq.float() if model_cfg.model_type == "fcnet" '
            "else input_seq.int()\n"
        )
        assert _dtype_name_branches(source)

    def test_it_catches_the_statement_form_that_was_removed(self):
        """Verbatim from `inference_single.py:213` before M5."""
        source = (
            "def f(args, input_seq, DEVICE):\n"
            '    if args.denoising_model == "fcnet":\n'
            "        input_seq = input_seq.float().to(DEVICE)\n"
            "    else:\n"
            "        input_seq = input_seq.long().to(DEVICE)\n"
        )
        assert _dtype_name_branches(source)

    def test_it_catches_a_dtype_kwarg_form_too(self):
        """A future reintroduction need not use the old spelling."""
        source = (
            "def f(model_cfg, x, torch):\n"
            '    if model_cfg.model_type == "punet":\n'
            "        x = x.to(dtype=torch.int32)\n"
        )
        assert _dtype_name_branches(source)

    def test_it_does_NOT_flag_the_f2_constructor_branches(self):
        """The branches Step 03 deliberately leaves alone, verbatim from
        `train_engine_sandbox.py:617`.

        A guard that flagged these would force a consumer-less contract
        field to clear it — which is why the token-ban guardrail is the
        wrong instrument for this surface, and why `.to()` is classified by
        its ARGUMENT rather than by its name.

        This case is the reason the first cut of this guard was wrong: it
        put `to` in the unambiguous-dtype set, flagged `.to(device)`, and
        reported a live violation that was not one.
        """
        source = (
            "def f(model_cfg, model_class, loss_cfg, device):\n"
            '    if model_cfg.model_type == "fcnet":\n'
            "        model = model_class(model_cfg, loss_type=loss_cfg.loss_type).to(device)\n"
            "    else:\n"
            "        model = model_class(model_cfg).to(device)\n"
            "    return model\n"
        )
        assert _dtype_name_branches(source) == []

    def test_it_catches_a_to_call_carrying_a_real_dtype(self):
        """The other side of that precision: `.to()` with a dtype argument
        IS a dtype decision and must still be caught."""
        source = (
            "def f(model_cfg, x, torch):\n"
            '    if model_cfg.model_type == "punet":\n'
            "        x = x.to(torch.int32)\n"
        )
        assert _dtype_name_branches(source)

    def test_the_real_files_are_actually_scanned(self):
        """A path typo would make every assertion above vacuous."""
        for relative_path in MIGRATED_SURFACES:
            path = REPO_ROOT / relative_path
            assert path.is_file(), path
            assert "resolve_input_dtype" in path.read_text(encoding="utf-8")

    def test_the_surface_list_cannot_be_silently_emptied(self):
        """Found by mutation D-M6, which SURVIVED the first cut of this guard.

        Emptying ``MIGRATED_SURFACES`` produced "6 passed, 1 skipped" rather
        than a failure: a parametrized test over an empty list simply does
        not run, so the guard stopped guarding while still reporting green.

        That is the same hole the sibling guardrail learned from — while a
        label sat in its ``_PENDING_CLEANUP`` dict, a reintroduced name
        branch was reported as ``xfail`` instead of ``failed``, so the guard
        detected the regression and then tolerated it.

        Both migrated surfaces are named explicitly here. Removing one is
        then a deliberate edit to a stated list, not an invisible
        disappearance.
        """
        assert set(MIGRATED_SURFACES) == {
            "execute_tools/train_engine_sandbox.py",
            "execute_tools/inference_single.py",
        }
