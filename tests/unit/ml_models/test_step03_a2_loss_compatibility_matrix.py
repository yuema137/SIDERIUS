"""Step 03 Checkpoint 0 — baseline **A2**: the loss-compatibility matrix.

Design:
``docs/design/generic_framework_upgrade/step_03_model_loss_contract.md``
§5 (A2 — "capture first"), §8a (loss authority is RE-KEYED, never
re-declared), §15 (Checkpoint 0), §21 (a changed accept/reject cell is a
STOP), §24.3.

**Why capture-first.** §8a re-keys ``validate_output_loss_compatibility``
so legality stops being inferred from the legacy string ``"classifier"``
and derives from the canonical output semantics instead. A re-key is only
an AUTHORITY change if **every verdict survives it** — the moment one
cell flips it is a policy change, which §21 makes a STOP. That claim is
unfalsifiable without the whole matrix pinned first, so this module has
**zero production diff** and lands before the re-key.

**The unique failure class.** *The re-key silently flips a verdict in a
cell nothing asserts.* The existing oracles are real but partial, and
their gaps are exactly where a re-key is most likely to slip:

==========================================  ================================
existing oracle                             what it leaves unasserted
==========================================  ================================
``test_plugin_loss_compatibility.py``        ``hybrid`` entirely;
  the two error branches + two              ``custom`` entirely
  accepts-its-own-family cases
``test_output_contract_end_to_end.py``       one legal + one illegal pair
  :122-131                                  per output type, so 15 cells
                                            are covered by 4 assertions
==========================================  ================================

``hybrid`` is asserted **nowhere** against this authority, and it is the
one output type whose arm is an unconditional early ``return`` — the
cheapest thing in the function for a re-key to drop. ``custom`` is the
deliberately permissive value (§8a), so a re-key that starts deriving
legality from tensor semantics would most plausibly break it first.

Delete this module and either regression ships green.

Verdicts are HARDCODED from the source at
``ml_models/models_format_sandbox.py:374-437``, cell by cell. Nothing is
computed from the frozensets, because deriving the expectation from the
same data the function reads would make the test pass for any consistent
mutation of both.
"""

from __future__ import annotations

import pytest

from ml_models.models_format_sandbox import (
    CLASSIFICATION_LOSSES,
    REGRESSION_LOSSES,
    validate_output_loss_compatibility,
)

#: The declared output-semantic alphabet (``plugin_loader.py:82``).
OUTPUT_TYPES = ("classifier", "regressor", "hybrid")

#: The declared loss alphabet (``LossConfig.loss_type``,
#: ``models_format_sandbox.py:458``).
LOSS_TYPES = ("ce", "focal", "focal_cw", "smooth_l1", "custom")

ACCEPT = "accept"
REJECT = "reject"

#: THE BASELINE — all 3 x 5 = 15 cells, hardcoded.
#:
#: ``custom`` is accepted by every contract on purpose: the plugin's own
#: forward raises at training time if its shape contract is violated,
#: which ``LossConfig`` cannot know in advance (§8a).
#: ``hybrid`` accepts everything via an unconditional early return.
MATRIX: dict[tuple[str, str], str] = {
    ("classifier", "ce"): ACCEPT,
    ("classifier", "focal"): ACCEPT,
    ("classifier", "focal_cw"): ACCEPT,
    ("classifier", "smooth_l1"): REJECT,
    ("classifier", "custom"): ACCEPT,
    ("regressor", "ce"): REJECT,
    ("regressor", "focal"): REJECT,
    ("regressor", "focal_cw"): REJECT,
    ("regressor", "smooth_l1"): ACCEPT,
    ("regressor", "custom"): ACCEPT,
    ("hybrid", "ce"): ACCEPT,
    ("hybrid", "focal"): ACCEPT,
    ("hybrid", "focal_cw"): ACCEPT,
    ("hybrid", "smooth_l1"): ACCEPT,
    ("hybrid", "custom"): ACCEPT,
}


@pytest.mark.parametrize(("output_type", "loss_type"), sorted(MATRIX))
def test_every_matrix_cell(output_type: str, loss_type: str):
    """Each of the 15 cells, asserted individually so a failure names it."""
    expected = MATRIX[(output_type, loss_type)]
    if expected is ACCEPT:
        validate_output_loss_compatibility(output_type, loss_type, model_type="a2_probe")
        return
    with pytest.raises(ValueError):
        validate_output_loss_compatibility(output_type, loss_type, model_type="a2_probe")


def test_the_matrix_covers_the_declared_alphabets_completely():
    """No cell may be quietly dropped from the baseline itself.

    Without this, deleting a row from ``MATRIX`` would silently shrink the
    oracle and every remaining test would still pass — the failure mode
    that makes a parametrized baseline look stronger than it is.
    """
    assert set(MATRIX) == {(o, m) for o in OUTPUT_TYPES for m in LOSS_TYPES}
    assert len(MATRIX) == 15


class TestTheShapeOfTheRule:
    """Properties of the rule the cell-by-cell table cannot express."""

    def test_hybrid_accepts_every_declared_loss(self):
        """``hybrid``'s arm is an unconditional early return — the whole row
        is ACCEPT. Asserted as one claim so a re-key that special-cases
        ``hybrid`` per loss family reds here, not just in a scattered cell."""
        assert {MATRIX[("hybrid", m)] for m in LOSS_TYPES} == {ACCEPT}

    def test_custom_is_permitted_by_every_output_type(self):
        """§8a: deliberately permissive for every contract."""
        assert {MATRIX[(o, "custom")] for o in OUTPUT_TYPES} == {ACCEPT}

    def test_the_only_rejections_are_the_two_cross_family_pairs(self):
        """Exactly four cells reject: a classifier fed the regression loss,
        and a regressor fed each of the three classification losses."""
        rejected = {k for k, v in MATRIX.items() if v is REJECT}
        assert rejected == {
            ("classifier", "smooth_l1"),
            ("regressor", "ce"),
            ("regressor", "focal"),
            ("regressor", "focal_cw"),
        }

    def test_the_frozensets_still_partition_the_family_losses(self):
        """The two frozensets are the authority's data (§8a). Pinned so a
        re-key cannot move a loss between families while leaving the
        verdicts coincidentally intact for the pairs above."""
        assert CLASSIFICATION_LOSSES == frozenset({"ce", "focal", "focal_cw"})
        assert REGRESSION_LOSSES == frozenset({"smooth_l1"})
        assert not (CLASSIFICATION_LOSSES & REGRESSION_LOSSES)

    def test_the_rejection_diagnostic_names_the_offending_pair(self):
        """A re-key must not degrade the message into an opaque refusal.

        Only the identifying content is pinned — the model, the contract it
        has, and the loss it may use instead. The exact prose is NOT pinned:
        it is not an LLM-visible byte surface, and over-pinning it would
        turn a wording improvement into a false failure.
        """
        with pytest.raises(ValueError) as exc:
            validate_output_loss_compatibility("classifier", "smooth_l1", model_type="a2_probe")
        message = str(exc.value)
        assert "a2_probe" in message
        assert "classifier" in message
        assert "smooth_l1" in message

        with pytest.raises(ValueError) as exc:
            validate_output_loss_compatibility("regressor", "focal", model_type="a2_probe")
        message = str(exc.value)
        assert "a2_probe" in message
        assert "regressor" in message
        assert "smooth_l1" in message


def test_an_output_type_outside_the_alphabet_is_currently_TOLERATED():
    """Current behaviour, pinned as behaviour rather than endorsed.

    Neither guard branch matches an unrecognised ``output_type``, so the
    function returns without raising. Recorded because §8a re-keys this
    authority to canonical output semantics, and a natural implementation
    of that re-key would begin failing closed here — which would be a
    changed verdict, i.e. a §21 STOP requiring an operator decision, not
    a free improvement to make in passing.

    If this test reds during the re-key, that is the design working: stop
    and decide, do not update the expectation.
    """
    validate_output_loss_compatibility("no_such_output_type", "ce", model_type="a2_probe")
    validate_output_loss_compatibility("no_such_output_type", "smooth_l1", model_type="a2_probe")
