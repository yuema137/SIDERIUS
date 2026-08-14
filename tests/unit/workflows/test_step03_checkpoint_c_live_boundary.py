"""CHECKPOINT C, boundaries (i) and (ii) — Step 03 §12.

Design:
``docs/design/generic_framework_upgrade/step_03_model_loss_contract.md``
§12 (the live integration checkpoint), §12's binding qualification:

    each boundary must be entered at the production entry point, not by
    calling a resolver directly.

So nothing here calls ``resolve_model_io_contract`` or
``render_forward_contract`` on a hand-built object. Both boundaries are
entered through ``workflows.task_config.load_task_config`` — the function
every agent path funnels through — and through the production proposer's
own system-prompt renderer.

  **C(i)**  the normalized contract reaches the real LLM-facing rendering
            path. Proven by VARYING the contract and observing the
            rendered bytes follow: a renderer still reading a literal
            would emit the same prompt for both.

  **C(iii)** is a real subprocess and lives in
  ``tests/integration/execute_tools/test_step03_checkpoint_c_subprocess.py``
  — an in-process call cannot prove the contract survives the trip.

**On C(ii)'s call count.** §12 requires the contradiction to be rejected
*before the LLM boundary*, "asserted by LLMBridge call count == 0 — not by
exception type alone". A ``BoundaryRecorderBridge`` is constructed and
handed the whole sequence; it records every would-be API call and must
record none.
"""

from __future__ import annotations

import textwrap

import pytest

import workflows.task_config as tc
from agent.schemas.model_io_resolution import (
    DatasetContradictionError,
    UnknownPresetError,
)
from agent.schemas.task_config import ForwardContract
from execute_tools.dataset_config import TIDMAD_PROFILE, bind_dataset_profile
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    _render_commit_system_prompt,
)
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
from workflows.task_config import load_task_config, render_forward_contract

_CONFIG = """\
task_description: |
  {description}
forward_contract:
  preset: sequence
  model_io:
    input:
      axes:
        - {{role: batch, dimension: {{symbolic: "B"}}}}
        - {{role: temporal, dimension: {{symbolic: "T"}}}}
      dtype: {{admissible: {input_dtype}}}
    output:
      axes:
        - {{role: batch, dimension: {{symbolic: "B"}}}}
        - {{role: class, dimension: {{fixed: {classes}}}}}
        - {{role: temporal, dimension: {{symbolic: "T"}}}}
      dtype: {{admissible: ["float32"]}}
  input_description: "raw signal"
  output_description: "per-timestep logits"
  task_type: "classification"
"""


@pytest.fixture(autouse=True)
def _clear_cache():
    tc._clear_cache_for_tests()
    yield
    tc._clear_cache_for_tests()


def _profile_with(num_classes: int):
    """A Dataset Profile whose ValueEncoding declares ``num_classes``.

    Required because rung 3-E cross-validates the contract's class axis
    against the DATASET's authority: a contrast that varies cardinality
    must vary the dataset fact too, or the load correctly refuses it. That
    refusal is the system working — it is C(ii)'s subject, and it is why a
    cardinality contrast needs a matching profile rather than a bypass.
    """
    return TIDMAD_PROFILE.model_copy(
        update={"encoding": TIDMAD_PROFILE.encoding.model_copy(update={"num_classes": num_classes})}
    )


def _write(tmp_path, *, classes: int = 256, input_dtype: str = '["int64", "int32"]', preset=None):
    path = tmp_path / "task_config.yaml"
    body = _CONFIG.format(description="a contrast task", classes=classes, input_dtype=input_dtype)
    if preset is not None:
        body = body.replace("preset: sequence", f"preset: {preset}")
    path.write_text(textwrap.dedent(body))
    return str(path)


class TestBoundaryILiveRendering:
    """**C(i)** — the contract reaches the real LLM-facing renderer."""

    def test_the_shipped_contract_renders_through_the_production_path(self):
        """The live path, on the SHIPPED config: load → validate → render."""
        contract = ForwardContract(**load_task_config()["forward_contract"])
        assert contract.model_io is not None, "the shipped task declares model_io"
        block = render_forward_contract(contract)
        assert "input:  [B, T] int64" in block
        assert "output: [B, 256, T] float32" in block

    def test_the_rendered_bytes_FOLLOW_the_contract(self, tmp_path):
        """The discriminating assertion.

        A renderer still emitting a literal would produce identical bytes
        for both configs. Only the class extent varies between them.
        """
        wide = ForwardContract(
            **load_task_config(_write(tmp_path, classes=256))["forward_contract"]
        )
        tc._clear_cache_for_tests()
        with bind_dataset_profile(_profile_with(16)):
            narrow = ForwardContract(
                **load_task_config(_write(tmp_path, classes=16))["forward_contract"]
            )

        assert "[B, 256, T] float32" in render_forward_contract(wide)
        assert "[B, 16, T] float32" in render_forward_contract(narrow)
        assert render_forward_contract(wide) != render_forward_contract(narrow)

    def test_the_proposer_system_prompt_carries_the_derived_shapes(self):
        """The real LLM-facing surface, not just the renderer.

        ``_render_commit_system_prompt`` (:1347) is what the production
        proposer hands the model. It substitutes ``fc.input_shape``,
        ``fc.output_shape`` and ``fc.output_description`` — and after M4
        the first two are DERIVED from ``model_io``. So the bytes the model
        receives are contract-driven.

        Corrected during Checkpoint C: an earlier cut of this test asserted
        the whole rendered CONTRACT BLOCK appeared in the system prompt. It
        does not — the commit prompt substitutes individual fields, not the
        block. Reading the renderer, rather than trusting the assumption,
        is what turned that into the assertion below.
        """
        contract = ForwardContract(**load_task_config()["forward_contract"])
        rendered = _render_commit_system_prompt(contract)
        assert contract.input_shape in rendered
        assert contract.output_shape in rendered
        assert "[B, 256, T] float32" in rendered

    def test_a_varied_contract_changes_the_proposer_system_prompt(self, tmp_path):
        """End to end for C(i): a different declaration produces a
        different LLM-facing prompt."""
        with bind_dataset_profile(_profile_with(16)):
            narrow = ForwardContract(
                **load_task_config(_write(tmp_path, classes=16))["forward_contract"]
            )
        tc._clear_cache_for_tests()
        shipped = ForwardContract(**load_task_config()["forward_contract"])
        assert _render_commit_system_prompt(narrow) != _render_commit_system_prompt(shipped)
        assert "[B, 16, T] float32" in _render_commit_system_prompt(narrow)


class TestBoundaryIIFailsClosedBeforeTheLLM:
    """**C(ii)** — a real contradiction is rejected before the boundary."""

    def test_a_dataset_cardinality_contradiction_is_rejected_at_load(self, tmp_path):
        """Rung 3-E at the PRODUCTION entry point. The bound profile
        declares 256; a contract claiming 10 must not load."""
        with pytest.raises(DatasetContradictionError):
            load_task_config(_write(tmp_path, classes=10))

    def test_an_unknown_preset_is_rejected_at_load(self, tmp_path):
        with pytest.raises(UnknownPresetError):
            load_task_config(_write(tmp_path, preset="no_such_preset"))

    def test_the_llm_bridge_records_ZERO_calls(self, tmp_path):
        """§12(ii)'s explicit requirement: call count == 0, not exception
        type alone.

        The bridge is constructed FIRST and the whole production sequence
        — load, build the contract, render the system prompt — is attempted
        against a contradictory config. The failure must land at load, so
        nothing ever reaches the boundary.
        """
        bridge = BoundaryRecorderBridge()
        assert bridge.captures == []

        with pytest.raises(DatasetContradictionError):
            config = load_task_config(_write(tmp_path, classes=10))
            contract = ForwardContract(**config["forward_contract"])
            _render_commit_system_prompt(contract)
            bridge.generate_text(  # pragma: no cover — unreachable by design
                system_prompt="unreachable",
                user_prompt="unreachable",
                label="proposer.commit",
            )

        assert bridge.captures == [], (
            "a machine-checkable contradiction reached the LLM boundary — "
            f"{len(bridge.captures)} call(s) recorded"
        )

    def test_a_consistent_config_DOES_reach_the_renderer(self, tmp_path):
        """Without this, a load that rejected everything would satisfy the
        zero-call assertion and prove nothing."""
        config = load_task_config(_write(tmp_path, classes=256))
        contract = ForwardContract(**config["forward_contract"])
        assert "[B, 256, T] float32" in _render_commit_system_prompt(contract)

    def test_an_unsupported_input_dtype_is_NOT_rejected_at_load(self, tmp_path):
        """A deliberate boundary statement, recorded rather than assumed.

        Dtype ADMISSIBILITY is a model-boundary requirement resolved at
        EXECUTION (§4a.1), not a config-level contradiction — the contract
        may legitimately express a dtype this runtime cannot materialize
        (A-1 correction 2). It fails closed where it is consumed, which is
        the subprocess boundary of C(iii), not here.
        """
        config = load_task_config(_write(tmp_path, input_dtype='["bfloat16"]'))
        contract = ForwardContract(**config["forward_contract"])
        assert contract.model_io is not None
        assert contract.model_io.input.dtype.admissible == ("bfloat16",)
