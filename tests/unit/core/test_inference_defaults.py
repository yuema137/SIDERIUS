"""
Tests for core/inference_defaults.py

Covers the split contract introduced in Phase K.2.5:

- ``inference_batch_for`` — executor-facing silent fallback to 25 for
  unknown model types (preserves pre-K.2.5 ``.get(model_type, 25)``
  behaviour in ``sandbox_executor.execute_inference``).
- ``assert_inference_batch_registered`` — estimator-facing loud raise
  on unknown model types, called by ``inference_skill/estimator.py``
  before forecasting VRAM/time for the inference phase.

See docs/resource_estimator_implement.md §10.5 + §10.14 Commit 1.
"""

import pytest

from core.inference_defaults import (
    assert_inference_batch_registered,
    inference_batch_for,
)


class TestInferenceBatchFor:
    """``inference_batch_for`` — silent fallback behaviour."""

    @pytest.mark.parametrize(
        "model_type,expected",
        [
            ("punet", 25),
            ("wavenet", 25),
            ("fcnet", 25),
            ("rnn", 10),
            ("transformer", 1),
        ],
    )
    def test_known_model_types_return_table_values(self, model_type, expected):
        """Each core model_type maps to the original TIDMAD-paper batch size."""
        assert inference_batch_for(model_type) == expected

    def test_unknown_model_type_returns_default(self):
        """Unknown types silently fall back to 25 — preserves pre-K.2.5
        plugin behaviour in ``sandbox_executor.execute_inference``."""
        assert inference_batch_for("some_plugin_model") == 25

    def test_empty_string_returns_default(self):
        """Edge case: empty string is not in the table, falls back to 25."""
        assert inference_batch_for("") == 25


class TestAssertInferenceBatchRegistered:
    """``assert_inference_batch_registered`` — loud raise on unknown."""

    @pytest.mark.parametrize(
        "model_type",
        [
            "punet",
            "wavenet",
            "fcnet",
            "rnn",
            "transformer",
        ],
    )
    def test_known_model_types_do_not_raise(self, model_type):
        """Registered types pass the assertion silently (returns None)."""
        assert assert_inference_batch_registered(model_type) is None

    def test_unknown_model_type_raises_value_error(self):
        """Planning-time callers must see a loud error so the VRAM/time
        gate never silently forecasts against a guessed batch size."""
        with pytest.raises(ValueError, match="no registered inference batch"):
            assert_inference_batch_registered("unregistered_plugin")

    def test_error_message_names_the_model_type(self):
        """The message must identify the offending model_type so the
        plugin author knows what to add to the table."""
        with pytest.raises(ValueError, match="'my_plugin'"):
            assert_inference_batch_registered("my_plugin")

    def test_error_message_points_to_defaults_file(self):
        """The message must point at ``core/inference_defaults.py`` so
        the reader knows exactly where to register the batch."""
        with pytest.raises(ValueError, match=r"core/inference_defaults.py"):
            assert_inference_batch_registered("another_plugin")
