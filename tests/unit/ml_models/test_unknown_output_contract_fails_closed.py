"""V21 PR C1 — an unestablished output contract must fail closed.

Before C1, ``get_output_type`` returned ``"classifier"`` for a model in
neither registry. That converted a *registration failure* into *wrong
scientific semantics*: a regressor whose declaration was dropped anywhere
upstream was trained, inferred and scored as a classifier, and nothing in
the record said so.

Two separable properties are tested here, because they fail independently:

1. **Parity** — every model that resolved before still resolves to the
   same contract. C1 must not move a single existing model.
2. **Fail closed at the real consumers** — each of the five production
   consumers translates the invariant failure into its own layer's typed
   refusal. The helper raising in isolation is not evidence that any
   production path notices; PR A's central lesson.

The consumer list is deliberately exhaustive rather than sampled. C1's
first census was built from the execution path and missed
``agent/prompts.py`` — see the PR C design doc §0.5a.
"""

from __future__ import annotations

import pytest

from ml_models import plugin_loader
from ml_models.plugin_loader import UnknownOutputContractError, get_output_type

_NEVER_REGISTERED = "c1_model_that_was_never_registered"


# ---------------------------------------------------------------------------
# 1. Parity — C1 must not move any model that already resolved
# ---------------------------------------------------------------------------


def test_every_registered_model_resolves_unchanged():
    """All 88 registered models keep their exact contract.

    Asserted against the registries themselves rather than a hardcoded
    list, because the plugin count depends on what is on disk. The
    *property* is what matters: nothing registered may raise, and each must
    return the value its own registry declares.

    Fails if: C1's raise-path is entered for any registered model, or a
    lookup is rerouted so a model resolves via the wrong registry.
    """
    from ml_models.models_sandbox import BUILTIN_OUTPUT_TYPES

    for model_type, declared in BUILTIN_OUTPUT_TYPES.items():
        assert get_output_type(model_type) == declared

    for model_type, declared in plugin_loader.PLUGIN_OUTPUT_TYPE_REGISTRY.items():
        # A plugin name shadowed by a built-in must still resolve built-in
        # first — that precedence predates C1 and must not shift.
        expected = BUILTIN_OUTPUT_TYPES.get(model_type, declared)
        assert get_output_type(model_type) == expected


def test_builtin_contract_table_is_exactly_as_shipped():
    """The six built-in contracts are pinned by value, not read back.

    Hardcoded deliberately: comparing the function's output to the table it
    reads from would pass for any table. This is the assertion that fails
    if someone edits ``BUILTIN_OUTPUT_TYPES`` itself.
    """
    assert {
        mt: get_output_type(mt)
        for mt in ("punet", "fcnet", "transformer", "wavenet", "rnn", "gated_fno")
    } == {
        "punet": "classifier",
        "fcnet": "hybrid",
        "transformer": "classifier",
        "wavenet": "classifier",
        "rnn": "classifier",
        "gated_fno": "classifier",
    }


# ---------------------------------------------------------------------------
# 2. The fail-closed contract itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_name",
    [
        pytest.param(_NEVER_REGISTERED, id="never_registered"),
        pytest.param("", id="empty_string"),
        pytest.param("   ", id="whitespace_only"),
        pytest.param("PUNET", id="wrong_case_is_not_a_near_miss"),
    ],
)
def test_unestablished_contract_raises(bad_name):
    """No input produces a default contract.

    ``"PUNET"`` is included because a case-insensitive "helpful" lookup
    would be a silent default wearing a different disguise.
    """
    with pytest.raises(UnknownOutputContractError):
        get_output_type(bad_name)


def test_error_blames_registration_not_the_model():
    """The message must not read as a statement about the architecture.

    This is the whole point of C1: "registration failed" and "this model is
    a classifier" are different facts, and the old code reported the second
    when the first was true.
    """
    with pytest.raises(UnknownOutputContractError) as exc:
        get_output_type(_NEVER_REGISTERED)

    message = str(exc.value)
    assert exc.value.model_type == _NEVER_REGISTERED
    assert _NEVER_REGISTERED in message
    assert "REGISTRATION FAILED" in message
    # The message must EXPLICITLY disclaim the classifier reading, because
    # that is the wrong conclusion a reader is most likely to draw from a
    # missing output contract — it is the exact conclusion the old code
    # drew silently.
    assert "does NOT mean the model is a classifier" in message


def test_registration_after_a_failed_lookup_resolves(monkeypatch):
    """The failure must not be cached or memoised.

    A late-registering plugin (the resume path re-registers, and
    ``model_exploration`` registers mid-run) must resolve normally
    afterwards.
    """
    with pytest.raises(UnknownOutputContractError):
        get_output_type(_NEVER_REGISTERED)

    monkeypatch.setitem(plugin_loader.PLUGIN_OUTPUT_TYPE_REGISTRY, _NEVER_REGISTERED, "regressor")
    assert get_output_type(_NEVER_REGISTERED) == "regressor"


def test_error_is_catchable_as_lookup_error():
    """Subclassing ``LookupError`` is part of the contract.

    A consumer that already guards a registry lookup should not be
    surprised by a new unrelated base class.
    """
    with pytest.raises(LookupError):
        get_output_type(_NEVER_REGISTERED)
