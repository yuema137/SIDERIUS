"""
Phantom Branch B model detection — v16 fix.

The implementor writes a ``CapabilityMetadata`` entry to
``agent_generated/_capability_index.json`` *before* the code validator
runs. If validation fails the entry stays in the index and the next
iteration's proposer would see the failed model as a Branch B reuse
candidate. The v16 iter_015 loss-chain failure was this exact pattern:
``gated_dilated_tcn`` was proposed in iter_009, its validator failed on
the pytest tmp-dir race, and iter_015's proposer then reused it (making
the implementor attempt to read a description from a stale pytest tmp
path).

Fix: the proposer supplies ``model_registry_names`` to the
``_validate_branch_b_model_registry_membership`` schema validator using
``_live_model_registry_names``, which returns the intersection of the
capability index and the live in-memory ``MODEL_REGISTRY``.
``MODEL_REGISTRY`` is populated only by ``register_model_in_memory``,
which the workflow calls after successful validation from
``_promote_model_to_global``. So the intersection filters out phantom
entries whose plugin has not actually validated.

These tests pin down that filtering behavior.
"""

from __future__ import annotations

from unittest.mock import patch

from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    _live_model_registry_names,
)


class _StubMeta:
    """Duck-typed ``CapabilityMetadata`` stand-in."""

    def __init__(self, name: str, capability_type: str = "model") -> None:
        self.name = name
        self.capability_type = capability_type


class _StubRegistry:
    """Duck-typed ``CapabilityRegistry`` returning fixed metadata."""

    def __init__(self, metas: list[_StubMeta]) -> None:
        self._metas = list(metas)

    def list(self, capability_type=None):
        if capability_type is None:
            return list(self._metas)
        return [m for m in self._metas if m.capability_type == capability_type]


class TestLiveModelRegistryFilter:
    def test_returns_intersection_of_index_and_live_registry(self):
        """Names in BOTH the index AND ``MODEL_REGISTRY`` are returned."""
        registry = _StubRegistry(
            [
                _StubMeta("wavenet_baseline_v16"),
                _StubMeta("mamba_v1"),
                _StubMeta("phantom_model"),
            ]
        )
        with patch(
            "ml_models.models_sandbox.MODEL_REGISTRY",
            new={"wavenet_baseline_v16": object(), "mamba_v1": object()},
        ):
            names = _live_model_registry_names(registry)
        assert names == ["mamba_v1", "wavenet_baseline_v16"]

    def test_phantom_in_index_but_not_registry_is_filtered_out(self):
        """The core Bug 2 case: a name in the capability index but NOT in
        the runtime ``MODEL_REGISTRY`` (because validation failed after
        implementor registration) must be excluded."""
        registry = _StubRegistry(
            [
                _StubMeta("real_model"),
                _StubMeta("gated_dilated_tcn"),  # v16 iter_015 phantom
            ]
        )
        with patch(
            "ml_models.models_sandbox.MODEL_REGISTRY",
            new={"real_model": object()},  # gated_dilated_tcn missing
        ):
            names = _live_model_registry_names(registry)
        assert names == ["real_model"]
        assert "gated_dilated_tcn" not in names

    def test_empty_registry_returns_empty(self):
        """No indexed models, empty ``MODEL_REGISTRY`` — returns []."""
        with patch("ml_models.models_sandbox.MODEL_REGISTRY", new={}):
            names = _live_model_registry_names(_StubRegistry([]))
        assert names == []

    def test_empty_intersection_returns_empty(self):
        """Index is populated but nothing in it has actually validated —
        all entries are phantoms, so the filtered list is empty."""
        registry = _StubRegistry([_StubMeta("only_phantom")])
        with patch("ml_models.models_sandbox.MODEL_REGISTRY", new={}):
            names = _live_model_registry_names(registry)
        assert names == []

    def test_loss_entries_are_ignored(self):
        """Only ``capability_type="model"`` rows are considered — a loss
        entry with the same name as a model in ``MODEL_REGISTRY`` must
        not sneak into the model registry names."""
        registry = _StubRegistry(
            [
                _StubMeta("wavenet_baseline_v16", capability_type="model"),
                _StubMeta("wavenet_baseline_v16", capability_type="loss"),
            ]
        )
        with patch(
            "ml_models.models_sandbox.MODEL_REGISTRY",
            new={"wavenet_baseline_v16": object()},
        ):
            names = _live_model_registry_names(registry)
        # deduped through the set() → sorted() pipeline; only one occurrence.
        assert names == ["wavenet_baseline_v16"]

    def test_live_only_names_are_filtered_out(self):
        """A defensive check: a name that is in ``MODEL_REGISTRY`` but NOT
        in the index (should not happen in practice — the workflow always
        registers before promoting — but the intersection semantics keep
        the guarantee explicit)."""
        registry = _StubRegistry([_StubMeta("indexed_model")])
        with patch(
            "ml_models.models_sandbox.MODEL_REGISTRY",
            new={
                "indexed_model": object(),
                "live_only_stray": object(),
            },
        ):
            names = _live_model_registry_names(registry)
        assert names == ["indexed_model"]
        assert "live_only_stray" not in names
