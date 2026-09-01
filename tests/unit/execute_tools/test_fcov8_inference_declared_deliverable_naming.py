"""F-COV-8 — the inference child never bound the run's DECLARED deliverable
naming, so any composed task using the framework's naming capability died in
inference.

**The defect, from a REAL composed run:**

```text
DeliverableNamingNotApplicableError: this composed run declared no deliverable
naming capability, so it has no indexed filename template
```

...raised while the run's manifest DID declare ``deliverable: {prefix,
extension, index_width}``. The message was accurate about the ContextVar and
wrong about the run.

**Mechanism.** ``bind_deliverable_naming`` had exactly two production call
sites — ``workflows/task_composition.py:2407`` (the parent) and
``execute_tools/denoising_score_single.py:509`` (the scoring child).
``execute_tools/inference_single.py`` never bound it, though ``--task_manifest``
reaches all three children (``core/sandbox_executor.py:1444, 1831, 2181``).
The manifest arrived; the child simply never used it to bind naming. An
asymmetry between two sibling children, not a missing transport — the
``F-12d-28`` shape one capability over.

**Why no Gate caught it.** Every in-tree pack HAND-ROLLS its deliverable name
(``tidmad_data_path.py``, ``pets_data_path.py``, ``davis_data_path.py`` have
zero ``resolve_deliverable_naming`` calls between them), so the framework
shipped a documented naming declaration with no consumer, and its transport to
the inference child was never exercised. The fixture task in
``tests/fixtures/fcov8_declared_naming_task.py`` is the missing consumer.

Each test names a defect only it can catch.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
FIXTURE_PLUGIN = REPO_ROOT / "tests" / "fixtures" / "fcov8_declared_naming_task.py"

#: Deliberately NOT the shipped TIDMAD template (``abra_validation_denoised`` /
#: ``.h5`` / width 4). A fixture that declared the defaults would pass whether
#: the declaration was read or silently ignored.
DECLARED = {"prefix": "fcov8_pred", "extension": ".json", "index_width": 3}

EXPECTED_NAME = "fcov8_pred_tinymodel_run1_exp1_000.json"

#: What the SHIPPED TIDMAD template produces for the same identity. Hardcoded,
#: never read back from `DeliverableNaming`, so a change to the shipped
#: template is a visible test failure rather than a silently-tracking one.
SHIPPED_NAME = "abra_validation_denoised_tinymodel_run1_exp1_0000.h5"


# ======================================================================
# Harness — drives the REAL child entry point
# ======================================================================


def _tiny_model_classes():
    """A minimal registered model, so ``main`` reaches the generic route.

    The model is scaffolding: this file asserts on the deliverable's NAME.
    Heavy subsystems stay mocked per the repository's unit-test contract, but
    the ENTRY POINT is real — the missing binding lives in ``main``, so a test
    against ``run_generic_inference`` would pass both before and after the fix
    and prove nothing.
    """
    import torch
    from torch import nn

    class TinyModel(nn.Module):
        def __init__(self, cfg=None):
            super().__init__()
            self.lin = nn.Linear(4, 2)

        def forward(self, x):
            return self.lin(x)

    class TinyConfig:
        segmentation_size = 4

        def __init__(self, **kwargs):
            pass

    return TinyModel, TinyConfig, torch


def _run_inference_child(tmp_path, monkeypatch, *, deliverable):
    """Drive ``inference_single.main()`` for a composed run of the fixture task.

    Args:
        deliverable: the manifest's ``deliverable:`` section, or ``None`` to
            OMIT it (the "task declares no naming capability" case).

    Returns:
        The output directory the child wrote into.
    """
    from execute_tools import inference_single
    from tests.fixtures import fcov8_declared_naming_task as fixture
    from tests.helpers.composed_manifest import write_complete_manifest

    TinyModel, TinyConfig, torch = _tiny_model_classes()

    manifest = write_complete_manifest(
        tmp_path,
        task_data_path={
            "file": str(FIXTURE_PLUGIN),
            "symbol": "DeclaredNamingTaskDataPath",
            "id": fixture.TASK_ID,
        },
        deliverable=deliverable,
    )

    # A REAL transported scope, serialized by the task's OWN codec — the bytes
    # the parent writes and the child must read. Hand-writing the payload would
    # test a fiction.
    impl = fixture.DeclaredNamingTaskDataPath()
    raw = impl.serialize_scope(impl.build_eval_scope(None)).encode("utf-8")
    scope_ref = tmp_path / "eval_scope.json"
    scope_ref.write_bytes(raw)

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    model_path = model_dir / "model.pth"
    torch.save(TinyModel().state_dict(), model_path)
    (model_dir / "_OK_exp1").write_text("ok", encoding="utf-8")

    model_cfg = tmp_path / "model.json"
    model_cfg.write_text(json.dumps({"segmentation_size": 4}), encoding="utf-8")
    loss_cfg = tmp_path / "loss.json"
    loss_cfg.write_text(json.dumps({"loss_type": "ce"}), encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    # CPU regardless of host: the assertion is about a filename, and a
    # GPU-dependent unit test is not portable to CI.
    monkeypatch.setattr(inference_single, "DEVICE", torch.device("cpu"))
    monkeypatch.setitem(inference_single.MODEL_REGISTRY, "tinymodel", TinyModel)
    monkeypatch.setattr(inference_single, "get_config_class", lambda model_type: TinyConfig)
    monkeypatch.setattr(
        "sys.argv",
        [
            "inference_single.py",
            "--denoising_model", "tinymodel",
            "--mode", "agent",
            "--model_cfg", str(model_cfg),
            "--loss_cfg", str(loss_cfg),
            "--model_path", str(model_path),
            "--exp_id", "exp1",
            "--run_name", "run1",
            "--output_dir", str(out_dir),
            "--data_dir", str(tmp_path),
            "--task_manifest", str(manifest),
            "--task_data_path_id", fixture.TASK_ID,
            "--task_eval_scope_ref", str(scope_ref),
            "--task_eval_scope_digest", hashlib.sha256(raw).hexdigest(),
        ],
    )  # fmt: skip

    inference_single.main()
    return out_dir


# ======================================================================
# (a) THE regression — the case that fails today
# ======================================================================


class TestADeclaredNamingReachesTheWrittenDeliverable:
    def test_composed_inference_writes_under_the_declared_template(self, tmp_path, monkeypatch):
        """Before the fix this raised ``DeliverableNamingNotApplicableError``
        at ``generic_inference.py:133``, after a successful forward pass —
        the run trained, inferred, and then could not name its own output.

        Fails as: the child either raises that error again (binding removed)
        or writes ``abra_validation_denoised_*.h5`` (binding present but the
        DECLARATION ignored in favour of the shipped template).
        """
        out_dir = _run_inference_child(tmp_path, monkeypatch, deliverable=dict(DECLARED))

        written = sorted(path.name for path in out_dir.iterdir())
        assert written == [EXPECTED_NAME], (
            f"the composed run must write its DECLARED indexed name; got {written}"
        )

    def test_the_declared_template_is_not_the_shipped_one(self):
        """Guards the FIXTURE, not the code: if someone 'tidies' DECLARED to
        the shipped defaults, the test above would pass without the
        declaration ever being read."""
        from execute_tools.deliverable_spec import DeliverableNaming

        shipped = DeliverableNaming()
        assert (shipped.prefix, shipped.extension, shipped.index_width) != (
            DECLARED["prefix"],
            DECLARED["extension"],
            DECLARED["index_width"],
        )


# ======================================================================
# (b) A legitimate ABSENCE must stay a refusal, not become a silent default
# ======================================================================


class TestATaskThatDeclaresNoNamingIsStillRefused:
    def test_no_deliverable_section_still_raises_not_applicable(self, tmp_path, monkeypatch):
        """The other half of the contract. A task that names its artifacts
        itself and declares NO ``deliverable:`` section has no indexed
        template, and ``resolve_deliverable_naming`` must still REFUSE.

        Fails as: the fix converted an honest absence into the shipped TIDMAD
        template — which is F-A4-1 restored, and a ``--cleanup_denoised`` glob
        addressing files the run never wrote.
        """
        from execute_tools.deliverable_spec import DeliverableNamingNotApplicableError

        with pytest.raises(DeliverableNamingNotApplicableError):
            _run_inference_child(tmp_path, monkeypatch, deliverable=None)


# ======================================================================
# (c) Un-composed runs are byte-identical — differential
# ======================================================================


class TestAnUncomposedRunIsUnchanged:
    def test_no_manifest_composes_no_naming(self):
        """An un-composed child has nothing to compose and binds nothing."""
        from execute_tools.inference_single import _declared_deliverable_naming

        assert _declared_deliverable_naming(None) is None

    def test_no_declaration_binds_a_nullcontext(self):
        """``None`` must be a NO-OP, never a default. If this returned a
        binding, an un-composed run would acquire a naming it never had."""
        import contextlib

        from execute_tools.deliverable_spec import declared_naming_binding

        assert isinstance(declared_naming_binding(None), contextlib.nullcontext)

    def test_the_spec_derivation_is_identical_with_no_declaration(self):
        """THE differential: with no declaration the derived spec must equal
        what the pre-fix child produced — a bare
        ``derive_run_deliverable_spec(profile)`` with nothing bound.

        Fails as: the fix changed legacy TIDMAD deliverable names.
        """
        from execute_tools.dataset_config import TIDMAD_PROFILE
        from execute_tools.deliverable_spec import derive_run_deliverable_spec
        from execute_tools.inference_single import _derive_spec_under_declared_naming

        profile = TIDMAD_PROFILE
        assert _derive_spec_under_declared_naming(profile, None) == derive_run_deliverable_spec(
            profile
        )


# ======================================================================
# Reachability — production must go THROUGH the boundary
# ======================================================================


class TestTheChildActuallyBindsOnEveryNamingRoute:
    """A helper nothing calls is not a fix. Each of these fails when ``main``
    stops routing a naming consumer through the binding."""

    @pytest.mark.parametrize(
        "consumer",
        [
            "_derive_spec_under_declared_naming(dataset_profile, _declared_naming)",
            "with declared_naming_binding(_declared_naming), _binding_cm:",
            "with bind_dataset_profile(dataset_profile), declared_naming_binding(_declared_naming):",
        ],
    )
    def test_main_routes_each_naming_consumer_through_the_binding(self, consumer):
        import inspect

        from execute_tools import inference_single

        source = inspect.getsource(inference_single.main)
        assert consumer in source, (
            f"a naming consumer in `main` is no longer inside the declared-naming "
            f"binding: {consumer!r}. The TIDMAD implementation re-derives its spec "
            f"INSIDE write_deliverable (tidmad_data_path.py:537), so it reads the "
            f"ContextVar live — an unbound write silently uses the shipped template."
        )

    def test_the_declaration_is_composed_exactly_once(self):
        """One composition, four use sites. A second
        ``compose_deliverable_naming_from_manifest`` CALL in this child would
        be a second authority for one value — and two manifest reads that
        could disagree.

        Counts CALLS (``name(``), so the import statement is not miscounted as
        a second site.
        """
        source = (REPO_ROOT / "execute_tools" / "inference_single.py").read_text(encoding="utf-8")
        assert source.count("compose_deliverable_naming_from_manifest(") == 1


class TestTheScoringChildStillOwnsItsOwnBinding:
    """F-COV-8 RESTORES symmetry; it must not later be 'consolidated' by
    deleting the sibling that already had a binding."""

    def test_scoring_still_composes_and_binds_its_declared_naming(self):
        source = (REPO_ROOT / "execute_tools" / "denoising_score_single.py").read_text(
            encoding="utf-8"
        )
        assert "compose_deliverable_naming_from_manifest" in source
        assert "declared_naming_binding" in source


# ======================================================================
# The SCORING child — its binding existed but its SCOPE was one statement
# ======================================================================


def _score_task_owned(tmp_path, *, deliverable):
    """Drive the scoring child's task-owned route.

    ``_emit_task_owned_score`` is the function ``main`` delegates the whole
    composed route to, and it OWNS the two naming consumers at issue — the
    deliverable SCAN (``read_evaluation_payload``) and the reported name
    (``task_declared_deliverable_name``). Driving it is driving production.

    Returns the parsed ``--output_json`` the child emitted.
    """
    from execute_tools import denoising_score_single
    from tests.fixtures import fcov8_declared_naming_task as fixture
    from tests.helpers.composed_manifest import write_complete_manifest
    from workflows.task_composition import compose_metric_from_manifest

    declaration = tmp_path / "metric_scan.json"
    declaration.write_text(
        json.dumps(
            {
                "aggregation": "declared_naming_scan_samples",
                "direction": "higher",
                "id": "fcov8_scan_samples",
                "references": [],
                "scoreability": {"contract_id": "deliverable_presence"},
                "transform": None,
                "transform_params": {},
            }
        ),
        encoding="utf-8",
    )

    manifest = write_complete_manifest(
        tmp_path,
        task_data_path={
            "file": str(FIXTURE_PLUGIN),
            "symbol": "DeclaredNamingTaskDataPath",
            "id": fixture.TASK_ID,
        },
        metric={
            "declaration": str(declaration),
            "implementation": {
                "file": str(FIXTURE_PLUGIN),
                "symbol": "DeclaredNamingScanMetric",
            },
        },
        deliverable=deliverable,
    )

    impl = fixture.DeclaredNamingTaskDataPath()
    raw = impl.serialize_scope(impl.build_eval_scope(None)).encode("utf-8")
    scope_ref = tmp_path / "eval_scope.json"
    scope_ref.write_bytes(raw)

    # The deliverable the INFERENCE child would have written. Under the
    # DECLARED template when the run declares one; under the SHIPPED template
    # when it does not — which is the pre-existing documented behaviour for a
    # composed run whose task declares no `deliverable:` section.
    deliverable_dir = tmp_path / "deliverables"
    deliverable_dir.mkdir()
    written_name = EXPECTED_NAME if deliverable is not None else SHIPPED_NAME
    (deliverable_dir / written_name).write_text(json.dumps({"samples": 3}), encoding="utf-8")

    # The parent pre-creates `--output_json`; `_merge_output_json_for` writes
    # ONLY into a file that already exists.
    out_json = tmp_path / "score.json"
    out_json.write_text("{}", encoding="utf-8")
    args = denoising_score_single.build_parser().parse_args(
        [
            "--mode", "agent",
            "--denoising_model", "tinymodel",
            "--exp_id", "exp1",
            "--run_name", "run1",
            "--data_dir", str(deliverable_dir),
            "--raw_data_dir", str(tmp_path),
            "--task_manifest", str(manifest),
            "--task_data_path_id", fixture.TASK_ID,
            "--task_eval_scope_ref", str(scope_ref),
            "--task_eval_scope_digest", hashlib.sha256(raw).hexdigest(),
            "--output_json", str(out_json),
        ]
    )  # fmt: skip

    declared = None
    if deliverable is not None:
        from workflows.task_composition import compose_deliverable_naming_from_manifest

        declared = compose_deliverable_naming_from_manifest(str(manifest))

    from workflows.task_composition import compose_run_task_bindings

    denoising_score_single._emit_task_owned_score(
        args,
        compose_run_task_bindings(str(manifest)).dataset_profile,
        compose_metric_from_manifest(str(manifest)),
        declared_naming=declared,
    )
    return json.loads(out_json.read_text(encoding="utf-8"))


class TestTheScoringChildScanUsesTheDeclaredTemplate:
    """Finding 1 — the scoring child's binding wrapped exactly ONE statement
    (``derive_run_deliverable_spec``) and was already unwound by the time the
    deliverable SCAN ran. So the child's SPEC carried the DECLARED template
    while its SCAN used the SHIPPED one: two answers inside one child."""

    def test_the_scan_resolves_the_declared_deliverable(self, tmp_path):
        """THE regression, asserted on the SCAN's OUTPUT.

        The score IS the payload the scan returned (`{"samples": 3}` -> 3.0),
        so this passes only if `read_evaluation_payload` opened the artifact
        written under the DECLARED template.

        Fails as: `DeliverableNamingNotApplicableError` (the task resolves its
        name through the framework and nothing is bound), or a scoreability
        refusal / empty-payload `ValueError` when the scan looked for the
        shipped `abra_validation_denoised_*` template instead.
        """
        emitted = _score_task_owned(tmp_path, deliverable=dict(DECLARED))

        assert emitted["denoising_score"] == 3.0, (
            "the deliverable scan did not resolve this task's artifact under "
            f"its declared template; emitted={emitted}"
        )

    def test_no_declaration_still_scans_the_shipped_template(self, tmp_path):
        """The scoring child's differential: a run declaring no ``deliverable:``
        must scan under the SHIPPED template, exactly as before this fix.

        The deliverable here is written under ``SHIPPED_NAME``; a score of 3.0
        proves the scan looked for that and not for a template the run never
        declared. Fails as: the fix started binding something when there was
        nothing to bind.

        NOTE this route does NOT raise ``NotApplicable`` for an absent
        declaration. The task-data-path binding covers scope deserialization
        and, separately, metric arithmetic; the deliverable scan remains
        outside it so the naming behavior tested here stays unchanged. The
        metric-scoped binding is covered by its own focused regression.
        """
        emitted = _score_task_owned(tmp_path, deliverable=None)

        assert emitted["denoising_score"] == 3.0, (
            f"an un-declaring run must scan the shipped template; emitted={emitted}"
        )


class TestTheScoringChildBindsEveryNamingConsumer:
    """Reachability for the two scoring-child sites, including the LEGACY
    route's scan, which has no cheap behavioural witness (it needs real HDF5
    validation data) but is the same live-ContextVar read."""

    @pytest.mark.parametrize(
        "consumer",
        [
            # the task-owned route: SCAN and reported NAME under one binding
            "with bind_dataset_profile(dataset_profile), declared_naming_binding(declared_naming):",
        ],
    )
    def test_each_scoring_naming_consumer_is_inside_the_binding(self, consumer):
        source = (REPO_ROOT / "execute_tools" / "denoising_score_single.py").read_text(
            encoding="utf-8"
        )
        assert consumer in source, (
            f"a scoring-child naming consumer is outside the declared-naming "
            f"binding: {consumer!r}. read_evaluation_payload re-derives its "
            f"spec inside the call (tidmad_data_path.py:571), so an unbound "
            f"scan silently uses the SHIPPED template while the child's own "
            f"deliverable_spec carries the DECLARED one."
        )

    def test_the_scoring_declaration_is_composed_exactly_once(self):
        """One compose, three bindings. Two composes could read a manifest
        that changed underneath the run — the disagreement class itself."""
        source = (REPO_ROOT / "execute_tools" / "denoising_score_single.py").read_text(
            encoding="utf-8"
        )
        assert source.count("compose_deliverable_naming_from_manifest(") == 1


class TestTheNoOpRuleHasOneOwner:
    """Both children apply *"an absent declaration binds nothing"*. Two inline
    copies of that rule is what let the scoping diverge in the first place."""

    def test_absent_declaration_is_a_nullcontext(self):
        import contextlib

        from execute_tools.deliverable_spec import declared_naming_binding

        assert isinstance(declared_naming_binding(None), contextlib.nullcontext)

    def test_both_children_use_the_shared_factory(self):
        for child in ("inference_single.py", "denoising_score_single.py"):
            source = (REPO_ROOT / "execute_tools" / child).read_text(encoding="utf-8")
            assert "declared_naming_binding" in source, child
            assert "bind_deliverable_naming(" not in source, (
                f"{child} re-inlined the bind/no-op rule instead of calling the "
                "shared factory — that is how the two children diverged before."
            )
