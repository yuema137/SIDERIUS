"""C12-P / W3 — B2: the VRAM pre-flight's ``segmentation_size`` holdout.

Confirmed defect. ``agent/skills/evaluate_vram_skill/wrapper.py`` resolves the
value that drives its compute-intensity gate with a RAW dict read carrying a
TIDMAD literal::

    seg_size = int(model_cfg.get("segmentation_size", 40000))

while the same wrapper builds the model itself through the config CLASS
(``config_obj = config_cls(**model_cfg)`` in ``_build_model``), whose declared
default is what the run will ACTUALLY execute at — 20000 for the built-in
transformer, 144 for the Oxford-IIIT Pet pack, 128 for the DAVIS pack.

``seg_size`` is then the sole non-batch operand of
``compute_intensity.passes(batch_size, seg_size)`` against a cap of 800_000, so
under the substituted 40000 any ``batch_size >= 21`` is refused, ``feasible``
goes False, and the LLM is advised to "reduce segmentation_size" — a knob both
contrast packs declare as dead engine residue and that the planner therefore
cannot usefully move.

The correct authority already exists and needs ZERO threading:
``agent.skills.training_skill.estimator.resolve_model_field``. Four sibling
call sites use it; this is the one holdout.

The four cases the operator named are covered below: key present · key absent ·
foreign composed task · applicable TIDMAD case that is genuinely invalid and
must stay LOUD.
"""

from __future__ import annotations

import re

import pytest
from pydantic import Field, ValidationError

from agent.skills.evaluate_vram_skill import compute_intensity
from agent.skills.evaluate_vram_skill import wrapper as vram_wrapper
from ml_models.models_format_sandbox import BaseConfig


class _HardwareDiscoveryStopped(RuntimeError):
    """Sentinel: end the pre-flight the instant the resolution is observable.

    ``seg_size`` is resolved and printed BEFORE ``run_skill`` enters its
    ``try``, so stopping at the first statement inside the try makes this a
    hermetic CPU-only test — no GPU, no probe, no model instantiation — while
    still exercising the production entry point rather than a copy of its
    expression.
    """


def _resolved_seg_size(monkeypatch, capsys, *, model_type: str, model_config: dict) -> int:
    """The value ``run_skill`` actually priced the intensity gate with.

    Read from the production banner, which prints the same ``seg_size``
    variable the gate consumes. Nothing here reads a schema default back — the
    expectations in every test below are hardcoded literals.
    """

    def _stop():
        raise _HardwareDiscoveryStopped

    monkeypatch.setattr(vram_wrapper, "discover", _stop)

    # The sentinel is raised inside ``run_skill``'s first try block, which does
    # not carry a broad handler at that depth, so it propagates. Swallowing it
    # HERE keeps the probe independent of the wrapper's handler shape — the
    # banner has already been printed either way.
    with pytest.raises(_HardwareDiscoveryStopped):
        vram_wrapper.run_skill(
            sandbox=None,
            model_type=model_type,
            model_config=model_config,
            train_config={"batch_size": 21},
            loss_config={"loss_type": "ce"},
        )

    banner = capsys.readouterr().out
    match = re.search(r"\(B=\d+, T=(\d+),", banner)
    assert match is not None, f"the VRAM pre-flight banner changed shape: {banner!r}"
    return int(match.group(1))


class _ForeignPackConfig(BaseConfig):
    """A contrast-pack config class, shaped like the shipped Pets plugin.

    ``segmentation_size`` is dead engine residue for an image classifier, which
    is why the pack declares a small ``ge=1`` value rather than TIDMAD's
    ``ge=1000`` band. Declared here rather than imported from ``examples/`` so
    the property does not depend on any pack's current maturity, and so nothing
    in a test registers a plugin as an import side effect.
    """

    segmentation_size: int = Field(default=144, ge=1)


class TestTheIntensityGateIsPricedByTheDeclaration:
    def test_an_absent_key_resolves_to_the_class_default(self, monkeypatch, capsys):
        """The APPLICABLE TIDMAD case — the defect is not contrast-only.

        Defect this test alone catches: the VRAM wrapper prices its
        compute-intensity gate at a hardcoded 40000 whenever the planner omits
        ``segmentation_size``, even for a built-in TIDMAD architecture whose
        config class declares something else. The transformer declares 20000,
        so the wrapper gates a model that will run at 20000 as though it ran at
        40000 — a 2x overstatement of the intensity product, and the wrapper
        contradicts itself in one call, since ``_build_model`` instantiates the
        very same config and gets 20000.

        Four sibling call sites already resolve this through
        ``resolve_model_field``; the assertion pins that this one joins them.

        How it fails on regression: reverting to ``.get(..., 40000)`` makes the
        banner print T=40000 and this fails naming both numbers.
        """
        resolved = _resolved_seg_size(
            monkeypatch, capsys, model_type="transformer", model_config={}
        )

        assert resolved == 20000, (
            "the compute-intensity gate must be priced at the value the model "
            f"will actually run at (the transformer declares 20000); got {resolved}"
        )

    def test_an_explicitly_stated_key_still_wins(self, monkeypatch, capsys):
        """Parity pin — GREEN today and it must stay green.

        Defect this test alone catches: a fix that reaches for the class
        default unconditionally and discards a value the plan explicitly
        states. ``resolve_model_field``'s contract is caller's dict FIRST, and
        an explicit value equal to nothing in particular must survive.

        How it fails on regression: a resolution order that consults the
        declaration first returns 8000 -> 20000 and this fails.
        """
        resolved = _resolved_seg_size(
            monkeypatch,
            capsys,
            model_type="transformer",
            model_config={"segmentation_size": 8000},
        )

        assert resolved == 8000

    def test_a_foreign_pack_default_does_not_trip_the_intensity_cap(
        self, monkeypatch, capsys, historical_workload_rule
    ):
        """The FOREIGN COMPOSED TASK case, asserted at the harm.

        Defect this test alone catches: on a composed Pets or DAVIS run, an
        omitted ``segmentation_size`` is substituted with TIDMAD's 40000; at
        ``batch_size = 21`` the intensity product is 840_000 against an
        800_000 cap, so a perfectly runnable image-classification config is
        refused as infeasible and the planner is told to reduce a knob its
        pack documents as unused. The pack's own declaration is 144, whose
        product at the same batch is 3_024 — three orders of magnitude under
        the cap.

        The assertion is composed rather than value-only on purpose: it pins
        the CONSEQUENCE (the gate's verdict flips) and not merely the operand,
        and both the batch and the expected verdict are hardcoded.

        Observed frequency note (C12-P B2 evidence): across 1,844 deduplicated
        persisted planner configs the key was omitted 7 times and the joint
        with ``batch_size >= 21`` was 0 — but 5 of the 7 persisted Pets plans
        already carry ``batch_size >= 21``, so the joint is rare only because
        composed runs are new, not because the shapes are incompatible.

        How it fails on regression: reverting the resolution makes ``resolved``
        40000 and ``passes(21, 40000)`` False, and this fails.
        """
        import ml_models.models_format_sandbox as fmt

        monkeypatch.setattr(fmt, "get_config_class", lambda model_type: _ForeignPackConfig)

        resolved = _resolved_seg_size(
            monkeypatch, capsys, model_type="pets_reference_cnn", model_config={}
        )

        assert resolved == 144, (
            "a composed task's own declared segmentation_size must price the "
            f"intensity gate, not TIDMAD's 40000 literal; got {resolved}"
        )
        assert compute_intensity.passes(21, resolved) is True, (
            "the compute-intensity gate refused a contrast-task config that "
            "sits three orders of magnitude below its cap"
        )


class TestAnInvalidApplicableConfigStaysLoud:
    def test_a_declaration_violating_value_still_raises(self):
        """The fix must not convert a broken plan into a silent default.

        Defect this test alone catches: resolving an absent key from the
        declaration is correct; resolving a PRESENT BUT ILLEGAL key from the
        declaration would be the same reclassification error B1 falsifies one
        subsystem over — a plan that cannot run would be silently repaired into
        one that can, and the ``schema_violation`` record the wrapper owes the
        planner would never be emitted.

        ``_build_model`` reads the RAW ``model_cfg``, so the config class is
        what refuses. That refusal must survive the ``seg_size`` resolution
        change untouched: the transformer declares ``ge=1000``, and 0 is not a
        segmentation size no matter what the class default is.

        GREEN today; this is a parity pin on the loudness guarantee, not a
        falsifier.

        How it fails on regression: routing ``_build_model`` through a resolved
        value instead of the raw dict makes the call succeed at the class
        default and no ``ValidationError`` is raised.
        """
        with pytest.raises(ValidationError):
            vram_wrapper._build_model("transformer", {"segmentation_size": 0}, "ce")
