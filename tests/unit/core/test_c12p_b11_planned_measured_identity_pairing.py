"""C12-P / B11 — the pinned identity must describe what the worker measured.

**Required before B11 closes** (operator ruling §V.5). W1's correction is
accepted *because* it moved a triad together; this is the falsifier that makes
that non-negotiable rather than a matter of the author's care.

The invariant, stated by production itself
------------------------------------------
``core/runtime_control/gpu_measurement_identity.py::build_planned_identity``
declares it in its own docstring:

    "The defaults for ``seg_size`` and ``batch_size`` are the same ones the
    measurement worker will apply, so the two sides cannot disagree because
    one of them filled a blank differently."

The parent PINS an identity for a candidate it has not built; the worker then
MEASURES that candidate in a subprocess. ``seg_size`` is hashed into the
parent's ``planned_config_hash``. If the two sides fill an omitted
``segmentation_size`` differently, the pinned identity stops describing the
thing that was measured — silently, because both halves still produce a
perfectly well-formed hash.

Why the naive B11 repair was a regression wearing a cleanup's clothes
---------------------------------------------------------------------
B11's brief named the parent site. Routing only it through
``resolve_model_field`` while the worker kept its ``40_000`` literal would have
made the two sides disagree for *every* model whose config class declares
something else — and would have looked like progress, because the census
offender list would have shrunk by one.

``TransformerConfig`` is that model: it declares ``segmentation_size = 20000``
(``ml_models/models_format_sandbox.py:122``) against the literal ``40000``. It
is used here as a REAL divergence witness rather than a synthetic one, so the
test cannot pass by agreeing on a value neither side would really produce.
"""

from __future__ import annotations

import pytest

#: A model whose DECLARED default differs from the literal both sides used to
#: hardcode. Hardcoded here, never read back from the config class: asserting
#: against the class would compare the schema to itself and pass for any value.
_DIVERGENT_MODEL = "transformer"
_ITS_DECLARED_DEFAULT = 20000
_THE_OLD_LITERAL = 40000


def _parent_seg_size(model_config: dict) -> int:
    """What the PARENT pins, through the production entry point."""
    from core.runtime_control.gpu_measurement_identity import build_planned_identity

    planned = build_planned_identity(
        model_type=_DIVERGENT_MODEL,
        model_config=model_config,
        train_config={"batch_size": 4},
    )
    return int(planned.seg_size)


def _worker_seg_size(model_config: dict) -> int:
    """What the WORKER would apply, resolved the same way its source does.

    The worker's own line runs deep inside a subprocess that needs CUDA and a
    dataset directory, so this calls the SAME authority the worker calls rather
    than booting it. The structural guard below is what keeps that honest: it
    fails if the worker ever stops going through that authority, which is the
    only way this stand-in could drift from the real thing.
    """
    from agent.skills.training_skill.estimator import resolve_model_field

    return int(
        resolve_model_field(
            _DIVERGENT_MODEL, model_config, "segmentation_size", safety_margin=_THE_OLD_LITERAL
        )
    )


class TestPlannedIdentityMatchesWhatIsMeasured:
    def test_an_omitted_seg_size_resolves_identically_on_both_sides(self) -> None:
        """The divergence case: the key is absent and the class declares 20000.

        DEFECT THIS TEST ALONE CATCHES
            The parent pinning an identity the worker's measurement does not
            correspond to. Every other B11 assertion looks at ONE side and is
            satisfied by the naive parent-only repair; this is the only one
            that compares them.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            Reverting either side to the literal makes the two integers differ
            and the assertion prints both, naming which side filled the blank
            differently.
        """
        omitted: dict = {}

        parent = _parent_seg_size(omitted)
        worker = _worker_seg_size(omitted)

        assert parent == worker, (
            f"the pinned identity ({parent}) and the value the worker would "
            f"measure at ({worker}) disagree for an omitted segmentation_size. "
            f"build_planned_identity's docstring declares these must be the "
            f"same; seg_size is hashed into planned_config_hash, so the parent "
            f"is now pinning an identity for something the worker did not "
            f"measure."
        )
        assert parent == _ITS_DECLARED_DEFAULT, (
            f"both sides agree on {parent}, but the transformer DECLARES "
            f"{_ITS_DECLARED_DEFAULT}. Agreeing on the old {_THE_OLD_LITERAL} "
            f"literal would satisfy the equality above while both sides remain "
            f"wrong — this pins WHICH value they agree on."
        )

    def test_a_declared_seg_size_is_honoured_by_both_sides(self) -> None:
        """The control: an explicit value still wins everywhere.

        DEFECT THIS TEST ALONE CATCHES
            An over-correction in which one side starts preferring the class
            default over the operator's / planner's explicit value. Without
            this, "always return the class default" would satisfy the case
            above.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            Either side stops returning the supplied 8000.
        """
        supplied = {"segmentation_size": 8000}
        assert _parent_seg_size(supplied) == 8000
        assert _worker_seg_size(supplied) == 8000


class TestBothSidesStillGoThroughTheOneAuthority:
    """Structural: the stand-in above stays faithful only while this holds."""

    @pytest.mark.parametrize(
        "rel",
        [
            "src/core/runtime_control/gpu_measurement_identity.py",
            "src/core/runtime_control/gpu_measurement_worker_main.py",
        ],
    )
    def test_the_site_resolves_through_resolve_model_field(self, rel: str) -> None:
        """DEFECT THIS TEST ALONE CATCHES
            A side reverting to its own literal. The behavioural comparison
            above would still catch a value divergence, but this names the
            cause at the exact file, and it also protects the stand-in in
            `_worker_seg_size` from silently ceasing to represent the worker.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            The named file stops calling the authority, or reintroduces the
            literal as a dict fallback.
        """
        import ast
        from pathlib import Path

        src = (Path(__file__).resolve().parents[3] / rel).read_text(encoding="utf-8")
        assert "resolve_model_field" in src, (
            f"{rel} no longer resolves segmentation_size through the single "
            f"authority; the planned/measured pairing is unguarded again."
        )

        # AST, not a substring. The first version of this guard asserted
        # `'"segmentation_size", 40000' not in src` and was VACUOUS: the
        # planted regression wrote `40_000`, and the two spellings are the same
        # integer to Python and different strings to `in`. That is the
        # "census matches a token exactly" blindness shape this repository has
        # already been burned by — so the check now reads the parsed call.
        offenders: list[int] = []
        for node in ast.walk(ast.parse(src)):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "get" or len(node.args) != 2:
                continue
            key, default = node.args
            if (
                isinstance(key, ast.Constant)
                and key.value == "segmentation_size"
                and isinstance(default, ast.Constant)
                and isinstance(default.value, int)
            ):
                offenders.append(node.lineno)

        assert offenders == [], (
            f"{rel} fills an omitted segmentation_size from a literal at "
            f"line(s) {offenders} instead of asking the single authority. If "
            f"only ONE of the two paired sides does this, the parent pins an "
            f"identity the worker did not measure — the exact regression the "
            f"behavioural case above exists to prevent."
        )
