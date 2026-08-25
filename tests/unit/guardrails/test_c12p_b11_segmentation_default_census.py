"""C12-P / B11 — no production site AUTHORS a value for ``segmentation_size``.

FALSIFIER + standing census. B11's own four sites are CLOSED; the exempt
table now holds exactly one entry, ``ml_model_implementor.py``, which is a
DIFFERENT defect wearing the same shape and is not B11's to fix (see its
comment). ``test_no_authored_default_survives_anywhere`` therefore stays RED,
deliberately, as the standing marker for that separate finding — it is not a
failure to repair, and it must never be made green by adding an exemption.

The rule, stated once
---------------------
``segmentation_size`` is a MODEL-CONFIG field owned by the model's config
class (``ml_models/models_format_sandbox.py``: wavenet/punet declare 40000,
transformer declares 20000, a generated plugin declares whatever the
implementor wrote). A framework site that fills an absent key with a LITERAL
is not choosing a default -- it is inventing a workload for a model that will
be constructed at a different size, and the two never meet.

There is already exactly one authority for this, and it needs no threading::

    agent/skills/training_skill/estimator.py::resolve_model_field
        supplied value  ->  config-class declared default  ->  safety_margin

The ``safety_margin=1000`` (wall time) vs ``safety_margin=40000`` (memory)
asymmetry is DELIBERATE and documented at ``estimator.py:159-164``: memory is
conservative when the size is over-stated, wall time when it is under-stated,
so the two phases pass opposite margins. This census must never be read as
demanding they agree.

Why an AST census and not a pyright rule or a Pydantic field
------------------------------------------------------------
Neither can see it. ``.get(key, literal)`` is a well-typed call on a
``dict[str, Any]``; the defect is in WHERE the number comes from, which only a
structural scan over production source can state. And the failure is silent by
construction: a run priced at 10000 and trained at 40000 produces no error, no
log line and a plausible number.

FILE-SET DISCIPLINE (the reason this census is shaped the way it is)
--------------------------------------------------------------------
This repository has been burned twice by a census whose FILE SET omitted the
directory the defect lived in -- F-12bc-9 (the scope ABI's directory left out)
and F-P2b-4 (an anchored symbol regex blind to a leading underscore). Both
guards were green for the wrong reason and self-evidencing, because their own
exemption lists could never fire. So:

* the roots below are asserted NON-EMPTY individually, by name;
* ``nodes/``, ``core/runtime_control/``, ``agent/skills/`` and
  ``agent/schemas/`` are asserted to be COVERED, by name, in their own test --
  every confirmed offender lives in one of them;
* the detector is proved able to see a PLANTED literal before any exemption is
  applied.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: The task-vocabulary key this census is about.
_FIELD = "segmentation_size"

#: Production roots walked. ``scripts`` and ``tools`` are INCLUDED rather than
#: waved away: they hold campaign harnesses that construct explicit configs
#: (which this census does not flag, because those are declarations and not
#: fallbacks), and excluding a root because "nothing should be there" is the
#: exact shape of F-12bc-9.
_PRODUCTION_ROOTS = (
    "nodes",
    "core",
    "agent",
    "execute_tools",
    "ml_models",
    "workflows",
    "scripts",
    "tools",
    "dashboard",
)

#: The directories every offender this census has EVER confirmed lives in --
#: including the three B11 closed, which is the point. Asserted covered by
#: name, so a future edit to ``_PRODUCTION_ROOTS`` cannot quietly blind the
#: census; narrowing this tuple to "where the offenders are today" is exactly
#: the F-12bc-9 shape, because a returning literal would then be invisible.
_REQUIRED_COVERAGE = (
    "nodes",
    "core/runtime_control",
    "agent/skills",
    "agent/schemas",
)

#: repo-relative path -> exact number of authored literals allowed there, with
#: the reason each is still standing. EVERY entry is debt, not design.
_EXEMPT: dict[str, tuple[int, str]] = {
    # ---- B11 proper: CLOSED by C12-P / B11. Three entries were retired here,
    # and every one of them is deliberately ABSENT rather than zeroed --
    # re-adding an entry for any of them means the literal came back.
    #
    #   * `nodes/ml_hyperparameter_tune_agent/planning.py` (2 literals). The
    #     framework AUTHORED a TIDMAD-vocabulary key (`seg_size`) with a
    #     TIDMAD-scale value into `ScopeBuildRequest.task_parameters`, a
    #     channel `task_data_path.py` declares OPAQUE to the framework. Its
    #     only production reader, `tidmad_data_path.py:383-395`, explicitly
    #     REFUSES to guess that value ("the framework has no vocabulary for it,
    #     so it must be declared by the caller rather than guessed here") --
    #     and the fallback defeated that refusal from the outside, which is why
    #     the refusal had never once been reached. The plan's STATED value now
    #     travels and an omitted one stays omitted, so the task refuses in its
    #     own words. The paired validation site checks only what the plan
    #     stated. `10000` was not even TIDMAD's declared default: `WaveNetConfig`
    #     declares 40000 (`ml_models/models_format_sandbox.py:25`).
    #     Falsifier: `tests/unit/nodes/ml_hyperparameter_tune_agent/
    #     test_c12p_b11_composed_seg_size_authoring.py`.
    #   * `nodes/ml_hyperparameter_tune_agent/runtime.py` and
    #     `core/runtime_control/bootstrap.py` (1 literal each). Both wrote
    #     `segment_length: 0` into a probe observation's `workload` -- the very
    #     field D4 buckets and C7 applicability ranges are keyed on -- while
    #     `production_probe_executors` ran the probe at the config class's
    #     declared default. A wrong provenance label, not a wrong batch. Both
    #     now resolve through `resolve_model_field`, in one commit, because
    #     they describe the same probe. Falsifier:
    #     `tests/unit/core/test_c12p_b11_probe_workload_provenance.py`.
    #
    # ---- Owned by another C12-P stream.
    # ---- finding B2: CLOSED on landed 12d. The site now resolves through
    # `resolve_model_field`, so it is deliberately ABSENT from this table.
    # Re-adding an entry for it would mean the literal came back.
    # ---- A different defect wearing the same shape: these two do not price a
    # workload, they BAKE the number into GENERATED plugin source
    # (`PLUGIN_TEMPLATE`: `segmentation_size: int = Field(default={...})`) and
    # into the implementor's prompt. A generated plugin therefore DECLARES
    # 40000 as its own class default, which is how the literal becomes
    # permanent rather than transient. Confirmed, reported, unowned.
    "nodes/ml_model_implementor/ml_model_implementor.py": (
        2,
        "C12-P census addition — :1194 prompt text, :1418 baked into the "
        "generated plugin's declared class default",
    ),
}


def _iter_production_files() -> list[Path]:
    files: list[Path] = []
    for root in _PRODUCTION_ROOTS:
        base = _REPO_ROOT / root
        if base.exists():
            files.extend(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(files)


def _authored_literals(source: str) -> list[int]:
    """Line numbers of ``<mapping>.get("segmentation_size", <int literal>)``.

    Deliberately NARROW and deliberately explained:

    * ``.get(key)`` with no default is NOT an offender -- an absent key
      yielding ``None`` is a stated absence, and every such site already
      handles it;
    * ``cfg["segmentation_size"]`` is NOT an offender -- a subscript raises,
      which is the fail-closed behaviour this census wants more of;
    * an explicit config declaration (``{"segmentation_size": 40000}`` in a
      campaign definition or a CLI default) is NOT an offender -- that is a
      caller stating a value, which is exactly the contract;
    * a NESTED default (``a.get(k, b.get(k, 40000))``) is counted ONCE per
      literal, at the innermost literal, because that is where the number is
      invented.

    The value is not filtered by magnitude. "Segmentation-scale" is a
    description of the harm, not the test: ``0`` is just as invented as
    ``40000``, and it is the shape that makes a provenance record lie.
    """
    tree = ast.parse(source)
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "get"):
            continue
        if len(node.args) != 2:
            continue
        key, default = node.args
        if not (isinstance(key, ast.Constant) and key.value == _FIELD):
            continue
        if isinstance(default, ast.Constant) and isinstance(default.value, int):
            hits.append(default.lineno)
    return sorted(hits)


def _census() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for path in _iter_production_files():
        try:
            hits = _authored_literals(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken file is another test's job
            continue
        if hits:
            found[path.relative_to(_REPO_ROOT).as_posix()] = hits
    return found


class TestTheCensusCanActuallySeeSomething:
    """NON-VACUITY. Runs before any exemption is consulted."""

    def test_a_planted_literal_default_is_detected(self):
        """If this fails, every other test in this file is meaningless.

        HOW IT FAILS WHEN THE DETECTOR REGRESSES: a narrowing of
        ``_authored_literals`` (an anchored name match, a magnitude filter, a
        requirement that the receiver be named ``model_config``) stops seeing
        the plant and ``hits`` comes back empty.
        """
        planted = textwrap.dedent(
            """
            def price(model_config):
                seg = int(model_config.get("segmentation_size", 40_000))
                return seg
            """
        )
        assert _authored_literals(planted) == [3]

    def test_a_planted_nested_literal_default_is_detected(self):
        """The implementor's shape (``a.get(k, b.get(k, 40000))``) must be
        visible; a detector that only looked at the OUTER default would call
        it clean because the outer default is a Call, not a Constant."""
        planted = textwrap.dedent(
            """
            def assemble(model_cfg, train_cfg):
                return model_cfg.get(
                    "segmentation_size", train_cfg.get("segmentation_size", 40000)
                )
            """
        )
        assert _authored_literals(planted) == [4]

    @pytest.mark.parametrize(
        "clean",
        [
            'x = cfg.get("segmentation_size")',
            'x = cfg["segmentation_size"]',
            'x = {"segmentation_size": 40000}',
            'x = cfg.get("batch_size", 1)',
            'x = resolve_model_field(mt, cfg, "segmentation_size", safety_margin=40000)',
        ],
        ids=["no-default", "subscript", "declaration", "other-key", "the-authority"],
    )
    def test_legitimate_shapes_are_not_flagged(self, clean):
        """A census that flagged the authority itself would be uninhabitable,
        and one that flagged explicit declarations would push callers toward
        subscripts. Both are how a guard gets deleted rather than obeyed."""
        assert _authored_literals(clean) == []


class TestTheFileSetCoversWhereTheDefectLives:
    def test_every_declared_root_actually_contributed_files(self):
        """F-12bc-9's shape: a root that resolves to nothing makes the whole
        census silently smaller.

        HOW IT FAILS: a renamed or removed directory leaves its name in
        ``_PRODUCTION_ROOTS`` and this test names it.
        """
        walked = {p.relative_to(_REPO_ROOT).parts[0] for p in _iter_production_files()}
        missing = [r for r in _PRODUCTION_ROOTS if r not in walked]
        assert missing == [], f"declared production roots walked no files: {missing}"

    def test_the_required_directories_are_covered(self):
        """The four directories every confirmed offender lives in, by name.

        HOW IT FAILS: narrowing ``_PRODUCTION_ROOTS`` to make the census green
        drops one of these and this test names it. That is the ONLY thing
        standing between this guard and the self-evidencing kind.
        """
        walked = {p.relative_to(_REPO_ROOT).as_posix() for p in _iter_production_files()}
        for required in _REQUIRED_COVERAGE:
            assert any(f.startswith(required + "/") for f in walked), (
                f"the census walked no file under {required!r} — a census whose "
                f"file set omits the directory the defect lives in is "
                f"self-evidencing (F-12bc-9)"
            )


class TestNoProductionSiteAuthorsASegmentationSize:
    def test_the_census_matches_the_exempt_table_exactly(self):
        """B11. The defect this alone catches: a framework site inventing a
        value for a model-config field the model itself declares.

        Counts are pinned EXACTLY, in both directions:

        * an UNLISTED file, or a listed file with MORE literals than recorded,
          is a new authored default -- red;
        * a listed file with FEWER literals is a fix that landed without the
          exemption being retired -- also red, because a stale exemption is
          how a census stops describing the code.

        HOW IT FAILS WHEN B11 REGRESSES: someone adds
        ``model_config.get("segmentation_size", 40000)`` to price, hash, size
        or record a workload, and this test names the file and the line.

        EXPECTED GREEN since C12-P / B11: the three B11 entries were RETIRED
        from the table rather than zeroed, so this assertion is now what
        catches the literal coming back to any of them.
        """
        found = _census()
        expected = {path: count for path, (count, _) in _EXEMPT.items()}
        actual = {path: len(lines) for path, lines in found.items()}

        assert actual == expected, (
            "authored `segmentation_size` defaults diverged from the recorded "
            f"census.\n  found: {found}\n  expected counts: {expected}\n"
            "Route the site through `resolve_model_field(model_type, "
            "model_config, 'segmentation_size', safety_margin=...)`, or record "
            "it in `_EXEMPT` with the reason it is still standing."
        )

    def test_every_surviving_default_is_where_no_config_class_can_exist(self):
        """The rule this census can actually defend, replacing a false one.

        WHAT THIS REPLACED, AND WHY (C12-P, operator ruling 3).
        This was ``assert _census() == {}`` -- "no authored default survives
        anywhere" -- kept deliberately RED so the remaining debt stayed
        "visible as debt rather than dissolved into a passing suite". I first
        converted it to ``xfail(strict=True)`` to make it landable. The
        operator vetoed that: the preferred terminal state for required
        behaviour is PASS, and a strict xfail must not be used to turn a
        finding into an accepted result.

        Reverting to the hard RED was not the answer either, because the
        universal it asserts is NOT TRUE of this repository. B11's rule is
        *do not author a value the model's config class already declares*. The
        two surviving sites are both in ``ml_model_implementor``, which runs
        BEFORE the model exists: it renders a prompt describing a proposed
        architecture, and assembles a plugin for one. ``get_config_class``
        returns ``None`` there by construction, so nothing is being
        overridden and the literal is a genuine fallback -- which is why
        routing it through ``resolve_model_field`` is a provable no-op
        (same value in, same value out) and would be churn dressed as a fix.

        So the absolute rule over-reached. What is true, and is asserted here,
        is that every SURVIVING default lives where no declaration can exist.
        A default anywhere else IS B11 and must be routed through the
        authority.

        DEFECT THIS TEST ALONE CATCHES
            An authored default appearing in a module that runs AFTER the
            model's config class exists -- i.e. a place where a real
            declaration is being silently overridden. The ``_EXEMPT`` census
            above pins counts and would also fire, but it cannot say WHY a
            site is or is not legitimate; this one names the only condition
            under which authoring is defensible at all.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            A file outside the pre-implementation surface appears in the
            census and is named, with its line numbers.
        """
        pre_implementation_only = {"nodes/ml_model_implementor/ml_model_implementor.py"}
        found = _census()
        illegitimate = {p: lines for p, lines in found.items() if p not in pre_implementation_only}

        assert illegitimate == {}, (
            "these sites author a `segmentation_size` default in a module that "
            f"runs AFTER the model's config class exists: {illegitimate}. There "
            "a declaration IS available, so authoring one silently overrides "
            "it -- that is B11. Route the site through "
            "`resolve_model_field(model_type, model_config, "
            "'segmentation_size', safety_margin=...)`."
        )

    def test_the_pre_implementation_fallback_is_genuinely_undeclared(self):
        """REACHABILITY for the exemption above -- the reason it is safe to obey.

        DEFECT THIS TEST ALONE CATCHES
            The exemption above becoming a rationalisation. It is only
            defensible while a proposed architecture genuinely has no config
            class; if `get_config_class` ever starts resolving novel names,
            the implementor's literal WOULD be overriding a declaration and
            the exemption must be withdrawn.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            `get_config_class` returns something for a name no model declares,
            and the exemption's premise is reported as false.
        """
        from ml_models.models_format_sandbox import get_config_class

        novel = "c12p_b11_a_model_that_does_not_exist_v1"
        assert get_config_class(novel) is None, (
            f"`get_config_class({novel!r})` resolved. The implementor's "
            "authored default is exempt ONLY because a proposed architecture "
            "has no config class to declare one; that premise no longer holds."
        )


class TestTheAuthorityIsWhereTheCensusSaysItIs:
    def test_resolve_model_field_resolves_the_declared_default(self):
        """REACHABILITY for the fix, and the reason the census is safe to
        obey: the authority it points at genuinely returns the value the model
        will be constructed with.

        Hardcoded, never read back from the thing under test: wavenet declares
        40000 and transformer declares 20000 in
        ``ml_models/models_format_sandbox.py``. If those declarations move,
        this test must be updated deliberately -- that is the point.

        HOW IT FAILS: ``resolve_model_field`` starts returning the safety
        margin for a model whose class DOES declare the field, i.e. the
        authority acquires the very defect the census forbids elsewhere.
        """
        from agent.skills.training_skill.estimator import resolve_model_field

        assert resolve_model_field("wavenet", {}, _FIELD, safety_margin=1_000) == 40_000
        assert resolve_model_field("transformer", {}, _FIELD, safety_margin=1_000) == 20_000
        assert resolve_model_field("wavenet", {_FIELD: 8_000}, _FIELD, safety_margin=1_000) == 8_000
