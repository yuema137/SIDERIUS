"""arXiv #259 — the run-declared output-type constraint (fleet ruling 2026-08-25).

The X9 campaign runs `output_type: regressor` in both arms, but `output_type`
is LLM-authored on `ProposalOutput` and no operator knob existed (S9 audit).
This unit adds the knob as a THREE-LAYER contract, and each test below names
the defect only it can catch:

  declaration  `ProposalInput.allowed_output_types` (None = unconstrained)
  advisory     the prompt states the constraint ONLY when declared
  enforcement  `ProposalOutput.output_type` context-validator refuses
               out-of-set values deterministically — the guarantee never
               rests on the LLM reading the prompt.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.schemas.proposal import ProposalInput, ProposalOutput
from agent.schemas.task_config import ForwardContract
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    _default_output_type,
    _output_type_constraint_note,
    _render_commit_system_prompt,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

_MINIMAL_OUTPUT = {
    "model_name": "constraint_probe_model",
    "output_type": "classifier",
    "model_description": "d",
    "mathematical_definition": "m",
    "motivation": "mo",
    "expert_advice": {},
    "baseline_config": {},
}


def _validate(output_type: str, allowed):
    payload = dict(_MINIMAL_OUTPUT, output_type=output_type)
    return ProposalOutput.model_validate(payload, context={"allowed_output_types": allowed})


class TestDeterministicGate:
    def test_out_of_set_output_type_is_refused_with_the_constraint_named(self):
        """Defect only this catches: a campaign declaring `regressor` accepting
        a classifier proposal — the confound the constraint exists to prevent.
        Fails by: no ValidationError, or an error that does not name the
        declared set (the LLM feedback loop then cannot correct itself)."""
        with pytest.raises(ValidationError, match=r"allowed_output_types=\('regressor',\)"):
            _validate("classifier", ("regressor",))

    def test_in_set_value_passes(self):
        assert _validate("regressor", ("regressor",)).output_type == "regressor"

    def test_absent_context_is_unconstrained_legacy(self):
        """Defect only this catches: the gate accidentally becoming mandatory —
        every existing construction site (fixtures, fixed-candidate plans)
        passes no context and must validate exactly as before."""
        out = ProposalOutput.model_validate(dict(_MINIMAL_OUTPUT))
        assert out.output_type == "classifier"

    def test_none_in_context_is_unconstrained(self):
        assert _validate("classifier", None).output_type == "classifier"


class TestInputDeclaration:
    def test_empty_tuple_is_refused(self):
        """Defect only this catches: `()` silently forbidding every proposal —
        a configuration error surfacing as an infinite proposer retry loop."""
        with pytest.raises(ValidationError, match="non-empty"):
            ProposalInput.model_validate({"existing_model_types": [], "allowed_output_types": ()})


class TestOmittedKeyDefault:
    def test_single_constraint_becomes_the_default(self):
        """Defect only this catches: an LLM omitting `output_type` under a
        regressor-only constraint burning a retry on a refusal the constraint
        already resolves (default was hardcoded 'classifier')."""
        assert _default_output_type(("regressor",)) == "regressor"

    def test_unconstrained_and_multi_keep_the_legacy_default(self):
        assert _default_output_type(None) == "classifier"
        assert _default_output_type(("classifier", "regressor")) == "classifier"


class TestPromptAdvisory:
    def _fc(self) -> ForwardContract:
        return ForwardContract.model_validate(
            {
                "model_io": None,
                "input_shape": "[B, T] int64",
                "output_shape": "[B, 256, T] float32",
                "output_description": "per-timestep class logits",
            }
        )

    def test_unconstrained_prompt_is_byte_identical(self):
        """Defect only this catches: the constraint block leaking into
        UNCONSTRAINED prompts — a silent LLM-facing delta the PB-parity
        pins exist to forbid. Fails by: the two renders differing."""
        base = _render_commit_system_prompt(self._fc(), None)
        again = _render_commit_system_prompt(self._fc(), None, allowed_output_types=None)
        assert base == again
        assert "RUN CONSTRAINT" not in base

    def test_constrained_prompt_appends_the_note_and_only_appends(self):
        """Defect only this catches: the note replacing/reordering existing
        prompt content instead of appending (prefix must stay byte-identical)."""
        base = _render_commit_system_prompt(self._fc(), None)
        constrained = _render_commit_system_prompt(
            self._fc(), None, allowed_output_types=("regressor",)
        )
        assert constrained.startswith(base)
        note = constrained[len(base) :]
        assert note == _output_type_constraint_note(("regressor",))
        assert '"regressor"' in note and "## RUN CONSTRAINT — output_type" in note


class TestReachability:
    """The gate is only as real as the parse sites that pass the context key.

    Source census, count-exact: BOTH proposer parse sites (legacy and
    pipeline) must hand `allowed_output_types` to `model_validate`'s context,
    and both omitted-key defaults must route through `_default_output_type`.
    Defect only this catches: a refactor dropping the key at one site —
    every behavior test above keeps passing (they call the schema directly)
    while production silently unconstrains. Fails by: count != 2.
    """

    SRC = (
        REPO_ROOT / "nodes" / "ml_model_proposal_agent" / "ml_model_proposal_agent.py"
    ).read_text()

    def test_both_parse_sites_pass_the_constraint_context(self):
        assert self.SRC.count('"allowed_output_types": inp.allowed_output_types') == 2, (
            "expected exactly the legacy + pipeline model_validate context entries"
        )

    def test_both_omitted_key_defaults_are_constraint_aware(self):
        assert len(re.findall(r"_default_output_type\(inp\.allowed_output_types\)", self.SRC)) == 2


class TestCliParsing:
    def test_parse_round_trip_and_typo_refusal(self):
        """Defect only this catches: a typo'd launch value surviving to the
        proposer as a permanently-refusing constraint loop instead of failing
        at launch. Fails by: SystemExit not raised for an unknown name."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "run_one_iteration_under_test",
            REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.parse_allowed_output_types("regressor") == ("regressor",)
        assert mod.parse_allowed_output_types("classifier, regressor") == (
            "classifier",
            "regressor",
        )
        assert mod.parse_allowed_output_types(None) is None
        assert mod.parse_allowed_output_types("") is None
        with pytest.raises(SystemExit, match="unknown output type"):
            mod.parse_allowed_output_types("regresser")
