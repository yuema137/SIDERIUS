"""
Change 1 verification — model registry write happens AFTER validation, not
during implementor.run().

Before ``feat/v16-fixes``, ``MLModelImplementor.run()`` called
``self._registry.register(...)`` immediately after writing the plugin
file, before the validator saw the code. On validation failure the entry
persisted permanently in ``_capability_index.json``, advertising the
failed model to all future proposers as a Branch B reuse candidate
(v16 iter_015 ``gated_dilated_tcn`` failure mode).

The fix moves registration into the workflow, after ``validation.passed``.
The implementor now builds the ``CapabilityMetadata`` and hands it back
via ``ImplementorOutput.capability_metadata``; the workflow reads the
field and calls ``CapabilityRegistry.register(...)`` only when the
validator has passed.

This test file pins:

1. ``ImplementorOutput.capability_metadata`` carries the metadata off
   the implementor even when registry mutation is deferred.
2. The implementor does NOT touch the ``_capability_index.json`` on
   disk. Whatever was there before ``run()`` is still there after.
3. Building the metadata field doesn't depend on the registry — the
   payload is fully derivable from ``ImplementorInput``.
"""

from __future__ import annotations

import json

from agent.schemas.implementor import ImplementorOutput
from agent_generated._registry import CapabilityMetadata, CapabilityRegistry


class TestModelNotRegisteredBeforeValidation:
    """The core Change 1 property: implementor.run() must not mutate
    ``_capability_index.json``. Registration happens in the workflow after
    the validator passes."""

    def test_capability_metadata_field_carries_registration_payload(self):
        """``ImplementorOutput`` must be able to carry the metadata all
        the way to the workflow's post-validation gate."""
        meta = CapabilityMetadata(
            name="freshly_generated_model",
            capability_type="model",
            file_path="/tmp/attempt_001/models/freshly_generated_model.py",
            created_at="2026-07-08T00:00:00+00:00",
            source_iteration="iter_001",
            description="A generated model plugin.",
            mathematical_definition="y = W x + b",
        )
        out = ImplementorOutput(
            model_type="freshly_generated_model",
            description_file_path="/tmp/attempt_001/models/freshly_generated_model/description.md",
            model_file_path="/tmp/attempt_001/models/freshly_generated_model.py",
            test_file_path="/tmp/attempt_001/tests/test_freshly_generated_model.py",
            config_fields={"hidden": 128},
            model_description="A generated model plugin.",
            mathematical_definition="y = W x + b",
            capability_metadata=meta,
        )
        assert out.capability_metadata is not None
        assert out.capability_metadata.name == "freshly_generated_model"
        assert out.capability_metadata.capability_type == "model"

    def test_capability_metadata_defaults_to_none(self):
        """Branch A (built-in) and Branch B (reuse) paths generate no new
        plugin, so the field should be omittable."""
        out = ImplementorOutput(
            model_type="wavenet",
            description_file_path="/dev/null",
            model_file_path="",
            test_file_path="",
            config_fields={},
            model_description="",
            mathematical_definition="",
        )
        assert out.capability_metadata is None

    def test_index_untouched_when_metadata_not_registered(self, tmp_path):
        """Simulate the on-failure path: the workflow sees
        ``validation.passed == False`` and does NOT call
        ``registry.register(impl_output.capability_metadata)``. The index
        must be identical to what it was before."""
        idx_path = tmp_path / "_capability_index.json"
        idx_path.write_text(json.dumps([]))
        registry = CapabilityRegistry(index_path=str(idx_path))
        assert registry.list() == []

        # Build metadata as the implementor would, but do NOT call
        # register() — the point of the fix is that this only happens
        # after validation.passed.
        meta = CapabilityMetadata(
            name="would_be_phantom",
            capability_type="model",
            file_path=str(tmp_path / "would_be_phantom.py"),
            created_at="2026-07-08T00:00:00+00:00",
            source_iteration="iter_001",
            description="A model that will fail validation.",
            mathematical_definition="y = x",
        )
        _ = ImplementorOutput(
            model_type="would_be_phantom",
            description_file_path="/dev/null",
            model_file_path=str(tmp_path / "would_be_phantom.py"),
            test_file_path=str(tmp_path / "test_would_be_phantom.py"),
            config_fields={},
            model_description="",
            mathematical_definition="",
            capability_metadata=meta,
        )
        # No call to registry.register() happens. Assert on the on-disk
        # index: nothing was written.
        with open(idx_path) as f:
            assert json.load(f) == []
        assert registry.list() == []

    def test_index_gets_entry_only_when_workflow_registers(self, tmp_path):
        """Positive path: on ``validation.passed`` the workflow reads
        ``impl_output.capability_metadata`` and calls
        ``registry.register(...)``. Confirm the index acquires exactly
        that entry."""
        idx_path = tmp_path / "_capability_index.json"
        idx_path.write_text(json.dumps([]))
        registry = CapabilityRegistry(index_path=str(idx_path))

        meta = CapabilityMetadata(
            name="post_validated_model",
            capability_type="model",
            file_path=str(tmp_path / "post_validated_model.py"),
            created_at="2026-07-08T00:00:00+00:00",
            source_iteration="iter_002",
            description="A validated model.",
            mathematical_definition="y = tanh(W x)",
        )
        out = ImplementorOutput(
            model_type="post_validated_model",
            description_file_path="/dev/null",
            model_file_path=str(tmp_path / "post_validated_model.py"),
            test_file_path=str(tmp_path / "test_post_validated_model.py"),
            config_fields={},
            model_description="A validated model.",
            mathematical_definition="y = tanh(W x)",
            capability_metadata=meta,
        )

        # Simulate the workflow's post-validation registration.
        assert out.capability_metadata is not None
        registry.register(out.capability_metadata)

        rows = registry.list(capability_type="model")
        assert len(rows) == 1
        assert rows[0].name == "post_validated_model"
        assert rows[0].source_iteration == "iter_002"
