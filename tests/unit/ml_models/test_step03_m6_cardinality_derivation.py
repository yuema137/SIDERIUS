"""Cardinality derivation — Step 03 M6 (Phase B), rung **3-C**.

Design:
``docs/design/generic_framework_upgrade/step_03_model_loss_contract.md``
§4b (ONE cardinality authority: derive or cross-validate), §11 rung
**3-C**, §21.

§11's failure criterion for 3-C is *"``256`` surviving in any resolved
path"*, and §11.1 requires the rung to red **if its consumer re-hardcodes
its literal**. So the rung asserts the class count that actually reaches a
CONSTRUCTED MODEL — the embedding table it builds and the logits it emits
— not the config field that was set. A test asserting
``cfg.num_classes == 10`` would pass with every builtin still hardcoding
256.

**One axis varies.** Every contract below differs from TIDMAD's only in
the class axis extent: same rank, same axis roles, same input dtype
admissibility, same output semantic (still categorical). A consumer that
reacted to anything else would red on the unchanged surfaces.
"""

from __future__ import annotations

import pytest
import torch

from agent.schemas.model_io_contract import (
    AxisRole,
    Dimension,
    DtypeAdmissibility,
    ModelIOContract,
    TensorAxis,
    TensorContract,
)
from execute_tools.model_input_dtype import (
    ContractCardinalityConflictError,
    apply_contract_cardinality,
)
from ml_models.models_format_sandbox import get_config_class
from ml_models.models_sandbox import BUILTIN_OUTPUT_TYPES, MODEL_REGISTRY

SEG = 1024

#: Minimal-but-valid architecture parameters. Only SIZE is reduced; nothing
#: that could influence the class count is touched.
_TINY: dict[str, dict] = {
    "punet": {"multi": 8, "depth": 2, "embedding_dim": 8, "kernel_size": 3},
    "fcnet": {"latent_dims": [64, 16]},
    "transformer": {"embedding_dim": 8, "nhead": 2, "num_layers": 1, "dim_feedforward": 64},
    "wavenet": {
        "input_channels": 4,
        "residual_channels": 8,
        "gate_channels": 8,
        "skip_channels": 8,
        "kernel_size": 2,
        "num_blocks": 1,
    },
    "rnn": {"embedding_dim": 8, "hidden_dim": 16, "num_layers": 1},
    "gated_fno": {},
}

BUILTINS = tuple(BUILTIN_OUTPUT_TYPES)


def _axis(role: AxisRole | None = None, **dim) -> TensorAxis:
    return TensorAxis(dimension=Dimension(**dim), role=role)


def _contract(class_dim: int | None) -> ModelIOContract:
    """TIDMAD's contract with ONLY the class extent varied."""
    output_axes = [_axis(AxisRole.BATCH, symbolic="B")]
    if class_dim is not None:
        output_axes.append(_axis(AxisRole.CLASS, fixed=class_dim))
    output_axes.append(_axis(AxisRole.TEMPORAL, symbolic="T"))
    return ModelIOContract(
        input=TensorContract(
            axes=(_axis(AxisRole.BATCH, symbolic="B"), _axis(AxisRole.TEMPORAL, symbolic="T")),
            dtype=DtypeAdmissibility(admissible=("int64", "int32")),
        ),
        output=TensorContract(
            axes=tuple(output_axes),
            dtype=DtypeAdmissibility(admissible=("float32",)),
        ),
    )


def _build(model_type: str, contract: ModelIOContract | None):
    """Construct a builtin exactly as the engines do."""
    payload = dict(_TINY[model_type], segmentation_size=SEG)
    resolved = apply_contract_cardinality(payload, contract)
    cfg = get_config_class(model_type)(**resolved)
    cls = MODEL_REGISTRY[model_type]
    model = cls(cfg, loss_type="focal") if model_type == "fcnet" else cls(cfg)
    model.eval()
    return model


class TestRung3CCardinality:
    """The class count reaching a real model derives from the contract."""

    @pytest.mark.parametrize("model_type", BUILTINS)
    @pytest.mark.parametrize("class_dim", [10, 64])
    def test_the_emitted_logit_count_follows_the_contract(self, model_type, class_dim):
        """Observed at the model's OUTPUT, which is what a hardcoded literal
        would betray. With 256 still baked in, every one of these reds."""
        model = _build(model_type, _contract(class_dim))
        with torch.no_grad():
            out = model(torch.zeros(1, SEG, dtype=torch.int64))
        assert out.shape == (1, class_dim, SEG)

    @pytest.mark.parametrize("model_type", BUILTINS)
    def test_tidmads_own_cardinality_is_unchanged(self, model_type):
        """The compatibility half of the same rung: the shipped 256 still
        produces 256 — derived now, but identical."""
        model = _build(model_type, _contract(256))
        with torch.no_grad():
            out = model(torch.zeros(1, SEG, dtype=torch.int64))
        assert out.shape == (1, 256, SEG)

    @pytest.mark.parametrize("model_type", BUILTINS)
    def test_regime_a_keeps_todays_behaviour(self, model_type):
        """No contract — a caller predating Step 03 — still gets 256."""
        model = _build(model_type, None)
        with torch.no_grad():
            out = model(torch.zeros(1, SEG, dtype=torch.int64))
        assert out.shape == (1, 256, SEG)

    def test_the_embedding_table_is_sized_by_the_contract_too(self):
        """Not just the head: an input embedding still sized 256 would accept
        indices the contract says cannot exist, and would only fail on data
        that never appears in a small test."""
        model = _build("wavenet", _contract(10))
        assert model.embedding.num_embeddings == 10


class TestOneCardinalityAuthority:
    """§4b — derive or cross-validate; never a second configurable count."""

    def test_a_config_contradicting_the_contract_fails_closed(self):
        with pytest.raises(ContractCardinalityConflictError) as exc:
            apply_contract_cardinality({"num_classes": 999}, _contract(256))
        message = str(exc.value)
        assert "999" in message
        assert "256" in message

    def test_an_agreeing_config_is_accepted(self):
        """Restating the derived value is redundant, not wrong — so a
        migration can proceed incrementally."""
        assert (
            apply_contract_cardinality({"num_classes": 256}, _contract(256))["num_classes"] == 256
        )

    def test_neither_side_is_silently_adopted(self):
        """The two failure modes §4b forbids: the config silently winning
        (a second authority) or being silently overwritten (an author
        believing a value that never took effect)."""
        with pytest.raises(ContractCardinalityConflictError):
            apply_contract_cardinality({"num_classes": 10}, _contract(256))

    def test_an_output_without_class_semantics_injects_nothing(self):
        """§4b's deliberate asymmetry — where cardinality is not meaningful,
        the model config is not given one."""
        payload = {"segmentation_size": SEG}
        assert apply_contract_cardinality(payload, _contract(None)) == payload

    def test_the_callers_payload_is_not_mutated(self):
        """The engines reuse the loaded config dict; mutating it in place
        would leak a derived value into an unrelated read."""
        payload = {"segmentation_size": SEG}
        apply_contract_cardinality(payload, _contract(10))
        assert "num_classes" not in payload


class TestNoConstructionLiteralSurvives:
    """§11's 3-C criterion: no ``256`` in a resolved construction path."""

    def test_no_builtin_constructs_a_layer_from_a_class_count_literal(self):
        """Source-level, because a literal that happens to equal the derived
        value is behaviourally invisible under TIDMAD — which is exactly the
        state this rung exists to leave behind."""
        import pathlib
        import re

        # Derived from THIS file, not from the cwd: a cwd-relative read passes
        # only when pytest happens to run from the repo root, and CLAUDE.md's
        # portability rule exists because a test that reads a different tree
        # than the one under test is worse than no test.
        repo_root = pathlib.Path(__file__).resolve().parents[3]
        source = (repo_root / "src/ml_models" / "models_sandbox.py").read_text()
        offenders = []
        for lineno, line in enumerate(source.splitlines(), start=1):
            code = line.split("#", 1)[0]
            if "256" not in code:
                continue
            if re.search(r"(nn\.Embedding|nn\.Linear|nn\.Conv1d|adc_channel\s*=)", code):
                offenders.append(f"{lineno}: {line.strip()}")
        assert offenders == [], (
            "a class-count literal survives in a construction path — 3-C's "
            f"failure criterion: {offenders}"
        )
