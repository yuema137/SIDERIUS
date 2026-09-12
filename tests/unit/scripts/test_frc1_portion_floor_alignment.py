"""F-RC-1 — every operator-facing portion control honours ONE executable floor.

Gate-discovered generic prerequisite fix (runtime input validation). **Not
P5+P6 lifecycle semantics** — this module is filed with the launch surface it
guards, and the P5+P6 ledger records only its provenance.

**The defect.** `--validation_max_portion` is applied as
`min(planned, ceiling)` to `trial_portion`, `train_portion` and `eval_portion`
(`nodes/ml_hyperparameter_tune_agent/planning.py:310-312`), each of which
declares `ge=0.01`. A ceiling BELOW that floor therefore cannot produce a legal
`TrialConfig` for any plan — the clamp manufactures a violation the planner
cannot avoid, because the planner never chose the value.

Two boundaries admitted what a third refuses:

    --trial_portion            type=_portion_floor   guarded
    --eval_portion             type=_portion_floor   guarded
    --validation_max_portion   type=float            UNGUARDED   <- the gap
    HyperparamTuningInput.validation_max_portion  gt=0.0         <- and here

**What it cost.** A real Gate run passed `0.002`; it was accepted at both
boundaries and rejected 17 times inside the tuner's retry budget
(3 fail-rounds x 5 formal attempts per iteration), each rejection costing a
real LLM planning call, before the run was terminated. The theoretical
uninterrupted cost was 30.

**The defect class only this module catches**: a portion control whose ADMITTING
boundary disagrees with its CONSUMING boundary. Every individual schema is
self-consistent, so nothing short of comparing them can see it — which is
exactly why it survived.

The floor is deliberately NOT re-implemented here. `_portion_floor` and the
Pydantic `ge=0.01` declarations are the two authorities; this module asserts
they AGREE and that no operator-facing portion flag escapes them.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import HyperparamTuningInput

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "src" / "workflows" / "run_one_iteration.py"

#: The canonical executable floor, hand-written. Every assertion below compares
#: a real boundary against THIS, never one boundary against another — so two
#: boundaries drifting together cannot pass.
FLOOR = 0.01

#: Operator-facing flags whose value is clamped onto, or becomes, a field
#: declaring `ge=0.01`.
PORTION_FLAGS = ["--trial_portion", "--eval_portion", "--validation_max_portion"]


def _portion_floor_fn():
    """The production parser authority, imported rather than reimplemented."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_frc1_runner", RUNNER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._portion_floor


# ---------------------------------------------------------------------------
# 1. The parser authority
# ---------------------------------------------------------------------------


class TestTheParserFloor:
    @pytest.mark.parametrize("value", ["0.002", "0.009", "0.0"])
    def test_below_the_floor_is_refused_at_argv_time(self, value):
        """Refused BEFORE any LLM or GPU spend — the whole point."""
        with pytest.raises(argparse.ArgumentTypeError) as excinfo:
            _portion_floor_fn()(value)
        assert "0.01" in str(excinfo.value)

    @pytest.mark.parametrize("value", ["0.01", "0.5", "1.0"])
    def test_the_legal_range_is_preserved(self, value):
        assert _portion_floor_fn()(value) == float(value)

    @pytest.mark.parametrize("value", ["1.5", "2.0"])
    def test_above_one_is_refused(self, value):
        with pytest.raises(argparse.ArgumentTypeError):
            _portion_floor_fn()(value)

    def test_a_non_numeric_value_is_refused(self):
        with pytest.raises(argparse.ArgumentTypeError):
            _portion_floor_fn()("not-a-float")


# ---------------------------------------------------------------------------
# 2. EVERY portion flag uses it — the structural guard
# ---------------------------------------------------------------------------


class TestNoPortionFlagBypassesTheParserAuthority:
    """The guard that prevents a FOURTH flag repeating this defect.

    **It tests a CONTRACT, not a naming pattern.** The rule is NOT "every flag
    whose name ends in `_portion` must use `_portion_floor`" — that is a
    convention rule, and it would wrongly reject a future flag whose target
    legitimately declares `ge=0.0`. The rule is:

        an operator-facing flag must not be LOOSER at argv time than the
        executable floor of the schema field it populates.

    So the guard reads each flag's target bound out of the LIVE schema and
    requires `_portion_floor` exactly when that target declares ``ge=0.01``.
    Today the two sets coincide; when they stop coinciding, this keeps testing
    the thing that matters.

    Asserting the three originally-known flags by name would have carried the
    same blind spot that produced F-RC-1 — `--validation_max_portion` was
    simply forgotten — so the flags are DISCOVERED from the parser's AST.
    """

    @staticmethod
    def _portion_flag_types(source: str | None = None) -> dict[str, str | None]:
        """Every `*_portion` operator flag and the `type=` callable it uses.

        `source` defaults to the real runner. It is a parameter ONLY so the
        anti-vacuity plant below can run THIS function over planted text
        instead of re-implementing the scan — a re-implementation would prove
        that a copy of the detector bites while the real one could be broken.
        """
        tree = ast.parse(RUNNER.read_text(encoding="utf-8") if source is None else source)
        found: dict[str, str | None] = {}
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
            ):
                continue
            flag = next(
                (
                    a.value
                    for a in node.args
                    if isinstance(a, ast.Constant) and str(a.value).startswith("--")
                ),
                None,
            )
            if not flag or not str(flag).endswith("_portion"):
                continue
            type_kw = next((kw for kw in node.keywords if kw.arg == "type"), None)
            found[str(flag)] = (
                type_kw.value.id if type_kw and isinstance(type_kw.value, ast.Name) else None
            )
        return found

    @staticmethod
    def _schema_floor(field_name: str) -> float | None:
        """The target field's declared floor, read from the LIVE schema."""
        field = HyperparamTuningInput.model_fields.get(field_name)
        if field is None:
            return None
        return next((m.ge for m in field.metadata if hasattr(m, "ge")), None)

    def test_no_flag_is_looser_at_argv_than_its_schema_floor(self):
        """THE contract assertion.

        A flag whose target declares ``ge=0.01`` must be refused at argv time;
        a flag whose target allows less is free to use a plain ``float``.
        """
        offenders: dict[str, str] = {}
        for flag, parser_type in self._portion_flag_types().items():
            floor = self._schema_floor(flag.lstrip("-"))
            if floor == FLOOR and parser_type != "_portion_floor":
                offenders[flag] = f"target declares ge={floor} but argv accepts {parser_type}"
        assert not offenders, (
            f"these operator flags are LOOSER at argv time than the executable "
            f"floor they resolve to: {offenders}. A value admitted here and "
            f"refused downstream is the F-RC-1 defect class."
        )

    def test_the_guard_is_reading_real_targets(self):
        """Anti-vacuity, two ways.

        The discovery must find the known flags, AND at least one of them must
        actually resolve to a ``ge=0.01`` target — otherwise the contract
        assertion above would be vacuously true for every flag.
        """
        discovered = self._portion_flag_types()
        assert set(PORTION_FLAGS) <= set(discovered)
        floors = {f: self._schema_floor(f.lstrip("-")) for f in discovered}
        assert FLOOR in floors.values(), (
            f"no discovered portion flag resolves to a ge={FLOOR} target — the "
            f"contract assertion would pass vacuously. Floors seen: {floors}"
        )

    def test_a_planted_looser_flag_would_be_caught(self):
        """Prove THE detector bites, without touching the real parser.

        Runs the same `_portion_flag_types` the contract assertion uses, over
        planted source. A previous revision re-implemented the scan inline and
        then asserted the literal it had just written was not
        ``"_portion_floor"`` — trivially true, and blind to a broken or
        mis-scoped real detector.
        """
        planted = (
            'parser.add_argument("--made_up_portion", type=float, default=0.1)\n'
            'parser.add_argument("--guarded_portion", type=_portion_floor, default=0.1)\n'
            'parser.add_argument("--not_a_portion_flag", type=float, default=0.1)\n'
        )
        types = self._portion_flag_types(planted)

        # Both portion flags are discovered; the non-portion flag is not.
        assert types == {"--made_up_portion": "float", "--guarded_portion": "_portion_floor"}
        # The bare `float` flag is exactly the F-RC-1 shape: an admitting
        # boundary looser than the schema floor it feeds.
        assert types["--made_up_portion"] != "_portion_floor"


# ---------------------------------------------------------------------------
# 3. The executable schema boundary agrees with the parser
# ---------------------------------------------------------------------------


class TestTheSchemaBoundaryAgrees:
    """The parser is a convenience; the SCHEMA is the executable contract.

    A caller that bypasses argparse — the workflow module CLI, a test, a future
    launcher — must still be refused, which is why the fix is at both layers
    rather than only the one that happened to be hit.
    """

    @staticmethod
    def _metadata_bounds():
        field = HyperparamTuningInput.model_fields["validation_max_portion"]
        ge = next((m.ge for m in field.metadata if hasattr(m, "ge")), None)
        le = next((m.le for m in field.metadata if hasattr(m, "le")), None)
        return ge, le

    def test_the_ceiling_declares_the_canonical_floor(self):
        ge, le = self._metadata_bounds()
        assert ge == FLOOR, (
            f"validation_max_portion declares ge={ge}; it is clamped onto "
            f"fields declaring ge={FLOOR}, so anything lower can only produce "
            "an invalid TrialConfig"
        )
        assert le == 1.0

    @pytest.mark.parametrize("value", [0.002, 0.009])
    def test_a_sub_floor_ceiling_is_refused_by_the_schema(self, value):
        with pytest.raises(ValidationError) as excinfo:
            HyperparamTuningInput(model_type="punet", data_dir="/tmp", validation_max_portion=value)
        assert "validation_max_portion" in str(excinfo.value)

    @pytest.mark.parametrize("value", [0.01, 0.5, 1.0])
    def test_the_legal_range_still_passes(self, value):
        inp = HyperparamTuningInput(
            model_type="punet", data_dir="/tmp", validation_max_portion=value
        )
        assert inp.validation_max_portion == value

    def test_none_still_means_no_ceiling(self):
        """The default must be untouched — every ordinary campaign relies on
        it."""
        inp = HyperparamTuningInput(model_type="punet", data_dir="/tmp")
        assert inp.validation_max_portion is None


# ---------------------------------------------------------------------------
# 4. The clamp targets share the floor — the reason any of this is true
# ---------------------------------------------------------------------------


def test_the_clamp_targets_all_declare_the_same_floor():
    """`validation_max_portion` is `min()`-ed onto exactly these three fields
    (`planning.py:310-312`). The ceiling's floor is correct only because
    theirs is — so their floor is asserted here rather than assumed.
    """
    from agent.schemas.hyperparam_tuning import TrialConfig

    for name in ("trial_portion", "train_portion", "eval_portion"):
        field = TrialConfig.model_fields[name]
        ge = next((m.ge for m in field.metadata if hasattr(m, "ge")), None)
        assert ge == FLOOR, f"TrialConfig.{name} declares ge={ge}, expected {FLOOR}"


def test_no_duplicate_validation_authority_was_introduced():
    """Operator constraint: do NOT add a third authority.

    `validate_runtime_config` is dataset-RESOLVED startup validation; portion
    bounds are dataset-independent and belong to the typed boundary. It must
    not grow a portion check that would drift from the schema.
    """
    import inspect as _inspect

    from agent.schemas import hyperparam_tuning as ht

    source = _inspect.getsource(ht.validate_runtime_config)
    assert "validation_max_portion" not in source, (
        "validate_runtime_config gained a validation_max_portion check — the "
        "Pydantic boundary already owns this property; a second authority "
        "would drift"
    )


# ---------------------------------------------------------------------------
# 5. FORMAL mode feeds TrialConfig from OPERATOR input — the same defect class
# ---------------------------------------------------------------------------


class TestFormalModeOperatorPortions:
    """Found BY the structural guard above, not by inspection.

    `_resolve_sample_set_cfg` (`policy.py:1164-1170`) builds the formal-mode
    config straight from operator input::

        TrialConfig.trial_portion  <- formal_portion
        TrialConfig.train_portion  <- formal_train_portion
        TrialConfig.eval_portion   <- formal_eval_portion

    All three targets declare ``ge=0.01``. Two of the three sources declared
    ``ge=0.0`` / ``gt=0.0`` — the identical mismatch
    ``validation_max_portion`` had, and reachable the same way: an operator
    value admitted at the boundary, then fatal at ``TrialConfig``.

    Trial mode is unaffected: it feeds from ``plan.*`` (``ExperimentPlan``,
    already ``ge=0.01``), so the planner cannot author an illegal portion.
    """

    @pytest.mark.parametrize(
        "field", ["formal_portion", "formal_train_portion", "formal_eval_portion"]
    )
    def test_every_formal_portion_declares_the_canonical_floor(self, field):
        meta = HyperparamTuningInput.model_fields[field].metadata
        ge = next((m.ge for m in meta if hasattr(m, "ge")), None)
        assert ge == FLOOR, (
            f"{field} declares ge={ge}; it becomes a TrialConfig portion "
            f"(ge={FLOOR}) in formal mode, so a lower value can only fail later"
        )

    @pytest.mark.parametrize(
        "field", ["formal_portion", "formal_train_portion", "formal_eval_portion"]
    )
    def test_a_sub_floor_formal_portion_is_refused_at_the_boundary(self, field):
        with pytest.raises(ValidationError) as excinfo:
            HyperparamTuningInput(model_type="punet", data_dir="/tmp", **{field: 0.005})
        assert field in str(excinfo.value)

    def test_the_formal_defaults_are_still_legal(self):
        """Anti-regression: tightening the floor must not invalidate the
        shipped defaults, which every ordinary campaign uses."""
        inp = HyperparamTuningInput(model_type="punet", data_dir="/tmp")
        assert inp.formal_portion >= FLOOR
        assert inp.formal_train_portion >= FLOOR
        assert inp.formal_eval_portion >= FLOOR
        assert inp.formal_eval_portion == 1.0
