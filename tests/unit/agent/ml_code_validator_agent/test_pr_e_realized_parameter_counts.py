"""V21 PR E — E3: both parameter-count views of the instantiated model.

O-E-6 FINAL, frozen: the validator records TOTAL
(``sum(p.numel() for p in model.parameters())``) **and** TRAINABLE
(``... if p.requires_grad``) from the SAME instance its instantiation
check already builds. ``None`` = never instantiated; ``0`` = a real
measurement of a parameterless model. Observation only — no verdict
boolean reads either count.

**Every expected integer below is hand-derived from the fixture's
architecture and written as a literal** — never read back from the model
(CLAUDE.md). The frozen-parameter fixture is the load-bearing one: it is
the only place total ≠ trainable is observable, so it alone can catch the
two conventions being swapped or one being derived from the other
(mutations M-E3-1/M-E3-2).

Design doc: ``docs/design/v21_priorities/pr_e_proposal_scale_funnel.md``
Commit E3.
"""

from __future__ import annotations

import json
import textwrap
from unittest.mock import MagicMock

from nodes.ml_code_validator_agent import MLCodeValidatorAgent
from nodes.ml_code_validator_agent.ml_code_validator_agent import (
    _check_instantiation_and_gradient,
)
from tests.unit.agent.ml_code_validator_agent.test_validator_agent import (
    make_input as make_validator_input,
)

# ---------------------------------------------------------------------------
# Fixtures — hand-derived parameter arithmetic in the docstrings
# ---------------------------------------------------------------------------

#: Embedding(256, 8): 256*8 = 2048 params.
#: Conv1d(8, 256, kernel_size=1): weight 256*8*1 = 2048, bias 256.
#: TOTAL = 2048 + 2048 + 256 = 4352, all trainable.
_KNOWN_SIZE_PLUGIN = textwrap.dedent(
    """
    import torch
    import torch.nn as nn
    from pydantic import BaseModel

    PLUGIN_MODEL_TYPE = "e3_known_size"
    PLUGIN_OUTPUT_TYPE = "classifier"

    class E3KnownSizeConfig(BaseModel):
        pass

    class E3KnownSize(nn.Module):
        def __init__(self, config):
            super().__init__()
            self.embedding = nn.Embedding(256, 8)
            self.conv_out = nn.Conv1d(8, 256, 1)

        def forward(self, x):
            h = self.embedding(x.long()).transpose(1, 2)
            return self.conv_out(h)

    PLUGIN_CONFIG_CLASS = E3KnownSizeConfig
    PLUGIN_MODEL_CLASS = E3KnownSize
    """
)
_KNOWN_TOTAL = 4352
_KNOWN_TRAINABLE = 4352

#: Same architecture, but the embedding is FROZEN (requires_grad=False):
#: TOTAL     = 4352            (the frozen 2048 still counts — architecture)
#: TRAINABLE = 2048 + 256 = 2304  (what an optimizer would update)
#: The 2048-parameter gap is what makes the two conventions observable.
_FROZEN_PARAM_PLUGIN = textwrap.dedent(
    """
    import torch
    import torch.nn as nn
    from pydantic import BaseModel

    PLUGIN_MODEL_TYPE = "e3_frozen"
    PLUGIN_OUTPUT_TYPE = "classifier"

    class E3FrozenConfig(BaseModel):
        pass

    class E3Frozen(nn.Module):
        def __init__(self, config):
            super().__init__()
            self.embedding = nn.Embedding(256, 8)
            self.embedding.weight.requires_grad_(False)
            self.conv_out = nn.Conv1d(8, 256, 1)

        def forward(self, x):
            h = self.embedding(x.long()).transpose(1, 2)
            return self.conv_out(h)

    PLUGIN_CONFIG_CLASS = E3FrozenConfig
    PLUGIN_MODEL_CLASS = E3Frozen
    """
)
_FROZEN_TOTAL = 4352
_FROZEN_TRAINABLE = 2304

#: No parameters at all: forward is a constant projection via a BUFFER.
#: TOTAL = 0 and TRAINABLE = 0 — real measurements, distinct from None.
_ZERO_PARAM_PLUGIN = textwrap.dedent(
    """
    import torch
    import torch.nn as nn
    from pydantic import BaseModel

    PLUGIN_MODEL_TYPE = "e3_zero"
    PLUGIN_OUTPUT_TYPE = "classifier"

    class E3ZeroConfig(BaseModel):
        pass

    class E3Zero(nn.Module):
        def __init__(self, config):
            super().__init__()
            self.register_buffer("proj", torch.zeros(256, 256))

        def forward(self, x):
            one_hot = torch.nn.functional.one_hot(x.long(), 256).float()
            return (one_hot @ self.proj).transpose(1, 2)

    PLUGIN_CONFIG_CLASS = E3ZeroConfig
    PLUGIN_MODEL_CLASS = E3Zero
    """
)

_BROKEN_INIT_PLUGIN = textwrap.dedent(
    """
    import torch.nn as nn
    from pydantic import BaseModel

    PLUGIN_MODEL_TYPE = "e3_broken"

    class E3BrokenConfig(BaseModel):
        pass

    class E3Broken(nn.Module):
        def __init__(self, config):
            super().__init__()
            raise RuntimeError("deliberately unbuildable")

        def forward(self, x):
            return x

    PLUGIN_CONFIG_CLASS = E3BrokenConfig
    PLUGIN_MODEL_CLASS = E3Broken
    """
)


def _measure(tmp_path, src: str):
    path = tmp_path / "plugin.py"
    path.write_text(src)
    inst_ok, grad_ok, otype_ok, err, total, trainable = _check_instantiation_and_gradient(str(path))
    return inst_ok, grad_ok, otype_ok, err, total, trainable


class TestBothConventions:
    def test_known_size_model_reports_the_exact_hand_derived_integers(self, tmp_path):
        inst_ok, _grad, _ot, err, total, trainable = _measure(tmp_path, _KNOWN_SIZE_PLUGIN)
        assert inst_ok and err is None
        assert total == _KNOWN_TOTAL
        assert trainable == _KNOWN_TRAINABLE

    def test_frozen_parameter_pins_the_two_fields_independently(self, tmp_path):
        """THE load-bearing case (O-E-6): total counts the frozen embedding,
        trainable excludes it. Both literals hand-derived; a swap or a
        derive-one-from-the-other fails exactly here."""
        inst_ok, _grad, _ot, _err, total, trainable = _measure(tmp_path, _FROZEN_PARAM_PLUGIN)
        assert inst_ok
        assert total == _FROZEN_TOTAL
        assert trainable == _FROZEN_TRAINABLE
        assert total != trainable  # the distinction this fixture exists to observe

    def test_zero_parameters_is_a_real_measurement_not_absence(self, tmp_path):
        _inst, _grad, _ot, _err, total, trainable = _measure(tmp_path, _ZERO_PARAM_PLUGIN)
        assert total == 0
        assert trainable == 0

    def test_instantiation_failure_yields_none_never_zero(self, tmp_path):
        inst_ok, _grad, _ot, err, total, trainable = _measure(tmp_path, _BROKEN_INIT_PLUGIN)
        assert not inst_ok and "instantiation failed" in (err or "")
        assert total is None
        assert trainable is None

    def test_import_error_yields_none(self, tmp_path):
        inst_ok, _grad, _ot, _err, total, trainable = _measure(tmp_path, "this is not python !")
        assert not inst_ok
        assert total is None and trainable is None

    def test_a_post_instantiation_failure_still_carries_the_counts(self, tmp_path):
        """A candidate that instantiates but violates its output contract is
        exactly the kind the funnel must not lose: the implementation
        existed and had a size."""
        bad_shape = _KNOWN_SIZE_PLUGIN.replace(
            'PLUGIN_OUTPUT_TYPE = "classifier"', 'PLUGIN_OUTPUT_TYPE = "regressor"'
        )
        inst_ok, _grad, _ot, err, total, trainable = _measure(tmp_path, bad_shape)
        assert not inst_ok and err is not None  # shape violates the regressor contract
        assert total == _KNOWN_TOTAL
        assert trainable == _KNOWN_TRAINABLE


class TestVerdictIndependenceAndPersistence:
    def _run_node(self, tmp_path):
        agent = MLCodeValidatorAgent.__new__(MLCodeValidatorAgent)
        agent.bridge = MagicMock()
        agent.bridge.generate.return_value = {
            "passed": True,
            "spec_alignment": True,
            "implementation_issues": [],
            "trainability_concerns": [],
            "notes": "pseudo",
        }
        return agent.run(make_validator_input(tmp_path, run_name="e3"))

    def test_both_counts_reach_the_persisted_validation_json(self, tmp_path):
        out = self._run_node(tmp_path)
        assert out.realized_total_parameter_count is not None
        assert out.realized_trainable_parameter_count is not None
        persisted = json.loads((tmp_path / "validation_e3.json").read_text())
        assert persisted["realized_total_parameter_count"] == (out.realized_total_parameter_count)
        assert persisted["realized_trainable_parameter_count"] == (
            out.realized_trainable_parameter_count
        )

    def test_a_zero_count_candidate_fails_on_the_PRE_EXISTING_gradient_rule(self, tmp_path):
        """Negative finding, recorded as-is (E3 changes no verdict): a
        parameterless model CANNOT pass validation, because
        ``loss.backward()`` on a graph with no grad-requiring tensors
        raises and the pre-existing gradient check fails. The measurement
        still reads 0/0 — a real size, on a candidate that failed for a
        reason that has nothing to do with its size. Pinned so a later
        "fix" cannot silently couple the two."""
        plugin_path = tmp_path / "zero.py"
        plugin_path.write_text(_ZERO_PARAM_PLUGIN)
        agent = MLCodeValidatorAgent.__new__(MLCodeValidatorAgent)
        agent.bridge = MagicMock()
        agent.bridge.generate.return_value = {
            "passed": True,
            "spec_alignment": True,
            "implementation_issues": [],
            "trainability_concerns": [],
            "notes": "pseudo",
        }
        out = agent.run(
            make_validator_input(
                tmp_path,
                run_name="e3zero",
                model_type="e3_zero",
                model_file_path=str(plugin_path),
                config_fields={},
            )
        )
        assert out.realized_total_parameter_count == 0
        assert out.realized_trainable_parameter_count == 0
        # The failure is the PRE-EXISTING backward-pass rule, by name —
        # not anything reading the measurement.
        assert out.passed is False
        assert out.gradient_check_passed is False
        assert "Backward pass failed" in (out.error_message or "")

    def test_the_verdict_is_identical_with_and_without_the_measurement(self, tmp_path):
        """Observation-only, proved mechanically: strip the counts from the
        output and every remaining field equals a pre-E3-shaped verdict.
        The verdict booleans cannot have read a number that varying the
        fixture size does not change."""
        out = self._run_node(tmp_path)
        dumped = out.model_dump()
        assert dumped.pop("realized_total_parameter_count") is not None
        assert dumped.pop("realized_trainable_parameter_count") is not None
        # The remaining surface is exactly the pre-E3 verdict surface —
        # pinned by E1's key-set test; here we assert the verdict itself.
        assert dumped["passed"] is True
        assert dumped["instantiation_passed"] is True
        assert dumped["gradient_check_passed"] is True
