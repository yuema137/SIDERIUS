"""C12-P / F-C12P-B11-2 — operator ruling 1A: the ``0`` sentinel must not escape.

The repair resolves ``segmentation_size`` through the one model-field authority
and passes ``safety_margin=0``. That ``0`` means **no authority declared a
usable value** — it is an internal sentinel of this call site, and the ruling is
explicit that it may never surface as a real ``segmentation_size``, runtime
identity, fingerprint, argv value, or persisted config semantic.

There are exactly three production sites that pass ``safety_margin=0``, and they
are protected by two different mechanisms. Both are proven here, because
"unreachable" and "converted" are different claims and only one of them is
visible at the call site.

    planning.py   CONVERTED   `_resolve_declared_segmentation_size` returns
                              `<resolved> or None`, turning 0 back into the
                              absence that keeps the task's refusal reachable.
                              Proven BEHAVIOURALLY, through production.

    bootstrap.py  UNREACHABLE `production_probe_executors` refuses a model with
    runtime.py                no registered config class BEFORE any observation
                              exists, so a 0 workload can never be recorded.
                              Proven by REACHABILITY, not by assertion.

Why this file exists at all: a sentinel that is only *documented* as unreachable
is a comment, and comments do not fail. F-12bc-7 in this repository was exactly
a pinned value that production recomputed — the lesson being that a claim about
production must be asserted through production.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

#: Every production site permitted to pass ``safety_margin=0``, and the
#: mechanism that stops the sentinel escaping. A NEW site is a new place the
#: sentinel can leak, so the set is pinned rather than counted.
SANCTIONED_ZERO_SENTINEL_SITES = {
    "src/nodes/ml_hyperparameter_tune_agent/planning.py",
    "src/nodes/ml_hyperparameter_tune_agent/runtime.py",
    "src/core/runtime_control/bootstrap.py",
}


def _sites_passing_zero_margin() -> set[str]:
    """Production files that call anything with ``safety_margin=0``.

    AST, not grep: ``safety_margin=0`` and ``safety_margin=0x0`` are the same
    integer to Python and different strings to ``in``. This repository has
    already been burned by a census that matched a token exactly.
    """
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.split()
    found: set[str] = set()
    for rel in tracked:
        if rel.startswith("tests/"):
            continue
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        if "safety_margin" not in src:
            continue
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if (
                    kw.arg == "safety_margin"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value == 0
                ):
                    found.add(rel)
    return found


class TestTheSentinelSurfaceIsPinned:
    def test_only_sanctioned_sites_pass_a_zero_margin(self):
        """DEFECT THIS TEST ALONE CATCHES
            A NEW call site adopting the ``0`` sentinel without either
            converting it away or being provably unreachable — i.e. a fourth
            place the sentinel can escape as a real value.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            The new file appears in the diff and is named.
        """
        assert _sites_passing_zero_margin() == SANCTIONED_ZERO_SENTINEL_SITES, (
            "the set of production sites passing safety_margin=0 changed. Each "
            "one must either convert the 0 away immediately (planning.py) or be "
            "provably unable to record it (the probe sites). Add it here with "
            "its mechanism, and prove that mechanism below."
        )


class TestTheProbeSitesAreUnreachableForAnUndeclaredModel:
    """The mechanism protecting ``bootstrap.py`` and ``runtime.py``.

    Their ``0`` would land in a probe observation's ``workload``, which D4
    buckets and C7 applicability ranges are keyed on. It never does, because a
    model with no registered config class cannot get as far as an observation.
    """

    def test_the_probe_refuses_a_model_with_no_config_class(self):
        """DEFECT THIS TEST ALONE CATCHES
            The probe's guard being removed or reordered, which would let a
            model with no config class reach observation-building — and the
            ``0`` workload be persisted as a real ``segment_length``, dragging
            ``ApplicabilityEnvelope.observed_min`` to zero. (B11's comments say
            ``0`` "cannot even be read back as a sentinel, because the request
            side declares ``Field(gt=0)``". That is NOT true of
            ``ProbeRequest`` -- see the correction on the last test in this
            file -- which is exactly why this refusal, not that constraint, is
            what protects the two probe sites.)

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            The guard stops raising, and the assertion below reports that the
            unreachability claim protecting two ``safety_margin=0`` sites no
            longer holds.

        Asserted STRUCTURALLY rather than by invoking the probe: the real call
        needs CUDA and a live MODEL_REGISTRY, so a runtime attempt would skip
        on this host and prove nothing. What matters is that the refusal
        precedes the construction, which is a property of the source.
        """
        src = (REPO_ROOT / "src/core" / "runtime_control" / "probe_production.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(src)
        guards = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.If) and ast.unparse(n.test) == "config_cls is None"
        ]
        constructors = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "config_cls"
        ]
        assert len(guards) == len(constructors) == 1
        assert guards[0].lineno < constructors[0].lineno
        assert any(isinstance(n, ast.Raise) for n in ast.walk(guards[0])), (
            "the no-config-class guard must refuse before constructing or recording a probe"
        )


class TestPlanningConvertsTheSentinelAway:
    """The mechanism protecting ``planning.py`` — behavioural, not structural.

    ``prepare_attempt`` is exercised end-to-end for the regime that produces a
    ``0`` resolution in
    ``tests/unit/nodes/ml_hyperparameter_tune_agent/
    test_c12p_b11_composed_seg_size_authoring.py``
    (``test_the_task_gets_to_refuse_a_seg_size_no_authority_declares``): the
    task's refusal fires, which is only possible if ``seg_size`` arrived as
    ``None``. A ``0`` would have arrived as ``0`` and been refused with a
    DIFFERENT message, so that test already discriminates.

    What is added here is the narrower fact that the conversion is not
    accidental — that ``0`` is treated as absence at the source, rather than
    surviving as an integer that merely happens to be falsy downstream.
    """

    def test_the_resolved_size_is_converted_to_absence_not_left_as_zero(self):
        """DEFECT THIS TEST ALONE CATCHES
            The conversion being dropped, so a ``0`` travels into
            ``task_parameters['seg_size']`` as a real integer. Downstream the
            task refuses either way TODAY -- so no behavioural test fails --
            but the value has already entered an OPAQUE channel the framework
            promised never to author into, and a task whose own check is
            ``is not None`` rather than ``> 0`` would accept it.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            ``or None`` disappears from the resolution and the assertion names
            the line.
        """
        src = (REPO_ROOT / "src/nodes" / "ml_hyperparameter_tune_agent" / "planning.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(src)

        # The conversion lives in the extracted boundary's RETURN, not at the
        # call site: `prepare_attempt` is a phase orchestrator and the
        # decomposition rule keeps this decision out of it. Anchoring on the
        # function by NAME is deliberate -- it is stronger than the previous
        # anchor on a local variable, which any refactor could rename.
        owner = [
            fn
            for fn in ast.walk(tree)
            if isinstance(fn, ast.FunctionDef) and fn.name == "_resolve_declared_segmentation_size"
        ]
        assert len(owner) == 1, (
            "`_resolve_declared_segmentation_size` is gone or duplicated. It is "
            "the single boundary that converts the safety_margin=0 sentinel to "
            "absence; without exactly one, this proof has no subject."
        )

        converted = [
            node
            for node in ast.walk(owner[0])
            if isinstance(node, ast.Return)
            and isinstance(node.value, ast.BoolOp)
            and isinstance(node.value.op, ast.Or)
            and isinstance(node.value.values[-1], ast.Constant)
            and node.value.values[-1].value is None
        ]
        assert len(converted) == 1, (
            "`_resolve_declared_segmentation_size` no longer returns "
            "`<resolved> or None`. The safety_margin=0 sentinel now travels "
            "into task_parameters as the integer 0 -- a value the framework "
            "invented, in a channel it declared itself unable to interpret."
        )


def test_zero_is_not_a_usable_segment_length_where_the_type_system_can_see_it():
    """The premise the whole sentinel choice rests on, asserted not assumed.

    DEFECT THIS TEST ALONE CATCHES
        ``0`` becoming a legitimate ``segment_length``, which would make it a
        terrible sentinel: the resolver could then return a real 0 and
        ``planning.py``'s ``or None`` would silently discard a DECLARED value.

    HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
        The ``gt=0`` constraint is relaxed and the construction succeeds.

    A CORRECTION worth recording. B11's own comments justify the sentinel by
    saying "the request side declares ``Field(gt=0)``". That is NOT true of
    ``ProbeRequest``, whose ``workload`` is an unconstrained
    ``dict[str, Any]`` -- a 0 placed there is accepted. The constraint is real
    but lives one layer further on, in the typed carriers below. So the
    sentinel is safe for the stated reason, at a DIFFERENT boundary than the
    comment names, and the probe sites' actual protection is the
    unreachability proven above -- not this constraint.
    """
    from pydantic import ValidationError

    from core.runtime_control.gpu_measurement_data import BoundedReadEvidence

    ok = {
        "source_file": "f.h5",
        "channel": "c",
        "segment_count": 1,
        "segment_length": 1,
        "first_sample": 0,
        "last_sample": 1,
        "bytes_read": 1,
        "file_sample_count": 1,
    }
    BoundedReadEvidence(**ok)  # control: the shape is otherwise valid

    with pytest.raises(ValidationError, match="segment_length"):
        BoundedReadEvidence(**{**ok, "segment_length": 0})
