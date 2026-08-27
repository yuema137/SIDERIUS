"""`R-OBS-1` C1 — the observable DECLARATION surface and its TYPED semantics.

Levels 1 and 2 of the row's five-level required contract:

  level 1  declarable by task — a manifest key the task owns
  level 2  typed dynamic vs static semantics — a TYPE, not a convention

Families, each naming the defect only it catches:

  (a) the two keys are declarable AND the closed-allowlist refusal still
      refuses — the property that must survive adding a key;
  (b) the acquisition is DERIVED from the implementation's type, and a
      declaration that puts an implementation in the wrong section is
      refused — the difference between a type and a convention;
  (c) an undeclared manifest's semantic fingerprint is byte-unchanged, and a
      declared one moves — including when the SAME implementation moves
      between the two sections;
  (d) names are unique across BOTH sections, because every downstream
      carrier joins on them;
  (e) an out-of-tree `file:` implementation's content digest reaches the
      fingerprint's plugin set, so editing an observable moves run identity.
"""

from __future__ import annotations

import os
import shutil

import pytest
import yaml

from execute_tools.observables import (
    OBSERVABLE_ACQUISITION_DYNAMIC,
    OBSERVABLE_ACQUISITION_STATIC,
    DynamicObservable,
    ObservableError,
    RunObservables,
    StaticObservable,
    acquisition_of,
)
from workflows.task_composition import (
    _MANIFEST_KEYS,
    _REQUIRED_KEYS,
    TaskCompositionError,
    compose_observables_from_manifest,
    compose_run_task_bindings,
    compute_semantic_fingerprint,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SHIPPED_MANIFESTS = ("tidmad", "pets", "davis", "quickstart")
PLUGIN_FIXTURE = os.path.join(REPO_ROOT, "tests", "fixtures", "robs1", "_observable_plugins.py")


# ---------------------------------------------------------------------------
# A composable manifest under tmp_path, so a test may edit it freely
# ---------------------------------------------------------------------------


@pytest.fixture
def manifest(tmp_path):
    """The shipped quickstart manifest, copied so its refs still resolve.

    Copied rather than rewritten: composing a hand-invented manifest would
    test this module against a task that does not exist, and the point of
    these tests is that a REAL composition still resolves.
    """
    src_dir = os.path.join(REPO_ROOT, "configs", "task_composition")
    dst_dir = tmp_path / "configs" / "task_composition"
    dst_dir.mkdir(parents=True)
    shutil.copy(os.path.join(src_dir, "quickstart.yaml"), dst_dir / "quickstart.yaml")
    # The manifest's refs are `../../examples/...`, resolved against the
    # manifest's own directory — so the pack must sit at the same depth.
    os.symlink(
        os.path.join(REPO_ROOT, "examples"),
        tmp_path / "examples",
        target_is_directory=True,
    )
    return dst_dir / "quickstart.yaml"


def _write(manifest_path, mutate) -> str:
    raw = yaml.safe_load(manifest_path.read_text())
    mutate(raw)
    manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return str(manifest_path)


def _entry(symbol: str, name: str) -> dict:
    return {"name": name, "implementation": {"file": PLUGIN_FIXTURE, "symbol": symbol}}


# ---------------------------------------------------------------------------
# (a) Level 1 — declarable, and the refusal that must survive the addition
# ---------------------------------------------------------------------------


class TestTheKeysAreDeclarable:
    def test_both_sections_are_manifest_keys_and_neither_is_required(self):
        """A task may declare observables, and a task with none stays valid.

        Both halves matter. Without the first, level 1 does not exist at all.
        Without the second, every existing manifest would fail to compose the
        moment this family landed.
        """
        assert "dynamic_observables" in _MANIFEST_KEYS
        assert "static_observables" in _MANIFEST_KEYS
        assert "dynamic_observables" not in _REQUIRED_KEYS
        assert "static_observables" not in _REQUIRED_KEYS

    def test_a_declared_manifest_composes_both_families_in_manifest_order(self, manifest):
        path = _write(
            manifest,
            lambda raw: raw.update(
                {
                    "dynamic_observables": [
                        _entry("OutputMeanObservable", "output_mean"),
                        _entry("MeanTargetObservable", "mean_target"),
                    ],
                    "static_observables": [
                        _entry("ParameterCountObservable", "trainable_parameters")
                    ],
                }
            ),
        )
        composition = compose_run_task_bindings(path)
        observables = composition.observables
        assert isinstance(observables, RunObservables)
        # Manifest order is semantic; nothing sorts.
        assert [d.name for d in observables.dynamic] == ["output_mean", "mean_target"]
        assert [s.name for s in observables.static] == ["trainable_parameters"]
        assert isinstance(observables.dynamic[0].implementation, DynamicObservable)
        assert isinstance(observables.static[0].implementation, StaticObservable)

    def test_an_undeclared_manifest_carries_no_observables(self, manifest):
        """The un-declared state, which every shipped manifest is in today."""
        assert compose_run_task_bindings(str(manifest)).observables is None

    @pytest.mark.parametrize(
        "misspelling",
        ["dynamic_observable", "static_observable", "observables", "dynamicobservables"],
    )
    def test_a_misspelled_section_key_is_still_REFUSED_not_dropped(self, manifest, misspelling):
        """The closed-allowlist property, preserved across the addition.

        This is the specific regression the addition could cause: widening
        `_MANIFEST_KEYS` by relaxing the check instead of extending the set
        would leave a misspelled section silently dropped, and the family
        would resolve as though nothing had been declared.
        """
        path = _write(
            manifest,
            lambda raw: raw.update({misspelling: [_entry("MeanTargetObservable", "x")]}),
        )
        with pytest.raises(TaskCompositionError, match="unknown key"):
            compose_run_task_bindings(path)

    def test_an_unknown_key_INSIDE_an_entry_is_refused(self, manifest):
        path = _write(
            manifest,
            lambda raw: raw.update(
                {
                    "dynamic_observables": [
                        {
                            "name": "x",
                            "implementaton": {  # codespell:ignore
                                "file": PLUGIN_FIXTURE,
                                "symbol": "MeanTargetObservable",
                            },
                        }
                    ]
                }
            ),
        )
        with pytest.raises(TaskCompositionError, match="unknown key"):
            compose_run_task_bindings(path)

    def test_a_non_list_section_is_refused_because_order_is_semantic(self, manifest):
        path = _write(manifest, lambda raw: raw.update({"dynamic_observables": {"a": 1}}))
        with pytest.raises(TaskCompositionError, match="must be a LIST"):
            compose_run_task_bindings(path)


# ---------------------------------------------------------------------------
# (b) Level 2 — the distinction is a TYPE
# ---------------------------------------------------------------------------


class TestAcquisitionIsAType:
    def test_acquisition_is_derived_from_the_object_not_from_a_declared_string(self):
        """`acquisition_of` reads the TYPE.

        If the acquisition were ever stored as a declared string, this
        function would be the place it was read back from — and it would then
        be possible for the label and the object to disagree. Deriving it
        makes that state unrepresentable.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location("_robs1_fixture_plugins", PLUGIN_FIXTURE)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert acquisition_of(mod.MeanTargetObservable()) == OBSERVABLE_ACQUISITION_DYNAMIC
        assert acquisition_of(mod.ParameterCountObservable()) == OBSERVABLE_ACQUISITION_STATIC
        with pytest.raises(ObservableError, match="neither a DynamicObservable"):
            acquisition_of(mod.NotAnObservable())
        with pytest.raises(ObservableError, match="both"):
            acquisition_of(mod.BothKinds())

    def test_a_static_implementation_declared_as_dynamic_is_REFUSED(self, manifest):
        """The refusal that makes this a type rather than a convention.

        A convention would accept this and run the arithmetic at whichever
        point the section implied, silently. Here the section says WHEN, the
        type decides WHEN, and a disagreement is a composition failure.
        """
        path = _write(
            manifest,
            lambda raw: raw.update(
                {"dynamic_observables": [_entry("ParameterCountObservable", "params")]}
            ),
        )
        with pytest.raises(TaskCompositionError, match="is a STATIC observable"):
            compose_run_task_bindings(path)

    def test_a_dynamic_implementation_declared_as_static_is_REFUSED(self, manifest):
        path = _write(
            manifest,
            lambda raw: raw.update({"static_observables": [_entry("MeanTargetObservable", "mt")]}),
        )
        with pytest.raises(TaskCompositionError, match="is a DYNAMIC observable"):
            compose_run_task_bindings(path)

    def test_an_implementation_that_is_neither_kind_is_refused_at_composition(self, manifest):
        path = _write(
            manifest,
            lambda raw: raw.update({"dynamic_observables": [_entry("NotAnObservable", "nope")]}),
        )
        with pytest.raises(TaskCompositionError, match="not a usable observable"):
            compose_run_task_bindings(path)

    def test_the_two_bases_declare_DIFFERENT_abstract_methods(self):
        """The structural reason the two cannot be satisfied interchangeably.

        If both bases ever declared the same method set, an implementation
        would satisfy either by accident and `isinstance` would stop
        discriminating — the type would collapse back into a convention
        without any test that asserts a refusal going red.
        """
        assert DynamicObservable.__abstractmethods__ == frozenset({"reset", "update", "value"})
        assert StaticObservable.__abstractmethods__ == frozenset({"compute"})
        assert not (DynamicObservable.__abstractmethods__ & StaticObservable.__abstractmethods__)


# ---------------------------------------------------------------------------
# (c) The fingerprint: byte-unchanged when undeclared, moving when declared
# ---------------------------------------------------------------------------


class TestFingerprintAdditivity:
    @pytest.mark.parametrize("name", SHIPPED_MANIFESTS)
    def test_every_shipped_manifest_declares_no_observables(self, name):
        """The precondition the byte-identity claim rests on.

        Stated as its own assertion so that a future manifest which DOES
        declare observables makes the digest test below fail informatively
        rather than mysteriously.
        """
        raw = yaml.safe_load(
            open(os.path.join(REPO_ROOT, "configs", "task_composition", f"{name}.yaml")).read()
        )
        assert "dynamic_observables" not in raw
        assert "static_observables" not in raw

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("tidmad", "9b497798a13a5cea3733f189b1dd69b5a61469fea4a63474d4b3e2906684486d"),
            ("pets", "3ab1128a3d5d425568b74642c9cd6857d16a5c64904c1befe3731ecfc11a2672"),
            ("davis", "396e767d5621390163e7ba0b16df401811379e758d7211e763eef50f5563ac43"),
            ("quickstart", "1330d3991a98c48b0f5a5f181ea4c838e7080bbe9029264097ea298074271921"),
        ],
    )
    def test_an_undeclared_manifest_fingerprint_is_the_PRE_ROBS1_value(self, name, expected):
        """Recorded at `origin/master` 3995400b, BEFORE this family existed.

        Hardcoded, never read back from the composition: the claim is that
        these four runs' identities did not move, and only a literal recorded
        outside the code under test can say that. An unconditional fingerprint
        key turns all four red at once.
        """
        path = os.path.join(REPO_ROOT, "configs", "task_composition", f"{name}.yaml")
        assert compose_run_task_bindings(path).semantic_fingerprint == expected

    def test_the_fingerprint_key_is_absent_for_none_and_for_an_empty_list(self):
        """The additive-when-non-empty idiom, at the authority itself.

        A structural companion to the four digests above: those prove the
        four shipped manifests did not move, this proves WHY, and stays green
        when an unrelated declaration legitimately moves a shipped digest.
        """
        base = _fingerprint_kwargs()
        undeclared = compute_semantic_fingerprint(**base)
        assert compute_semantic_fingerprint(**base, observable_declarations=None) == undeclared
        assert compute_semantic_fingerprint(**base, observable_declarations=[]) == undeclared
        declared = compute_semantic_fingerprint(
            **base, observable_declarations=[{"acquisition": "dynamic", "name": "x"}]
        )
        assert declared != undeclared

    def test_acquisition_reaches_the_fingerprint_THROUGH_the_composition(self, manifest, tmp_path):
        """Acquisition is part of run identity, not decoration — end to end.

        Driven through `compose_run_task_bindings`, not by handing
        `compute_semantic_fingerprint` a payload this test built: a test that
        constructs the declaration itself cannot see the composition dropping
        `acquisition` from it, and a name-only payload passed that version of
        this test unchanged.

        The `module:` form is load-bearing here. A `file:` implementation
        contributes a plugin ref whose `symbol` already differs between the
        two sections, so the fingerprint would move for a reason that has
        nothing to do with acquisition. `module:` pins no plugin ref, which
        isolates the one value under test.
        """
        module = "tests.fixtures.robs1._observable_plugins"
        second = tmp_path / "configs" / "task_composition" / "second.yaml"

        def _module_manifest(path, section: str, symbol: str) -> str:
            return _write(
                path,
                lambda raw: raw.update(
                    {
                        section: [
                            {
                                "name": "same_name",
                                "implementation": {"module": module, "symbol": symbol},
                            }
                        ]
                    }
                ),
            )

        shutil.copy(manifest, second)
        as_dynamic = compose_run_task_bindings(
            _module_manifest(manifest, "dynamic_observables", "MeanTargetObservable")
        ).semantic_fingerprint
        as_static = compose_run_task_bindings(
            _module_manifest(second, "static_observables", "ParameterCountObservable")
        ).semantic_fingerprint
        assert as_dynamic != as_static

    def test_the_fingerprint_payload_records_acquisition_alongside_the_name(self):
        """The authority's own contract for the key's shape.

        Paired with the end-to-end test above: this one pins WHAT the payload
        must contain, that one pins that the composition actually puts it
        there.
        """
        base = _fingerprint_kwargs()
        as_dynamic = compute_semantic_fingerprint(
            **base, observable_declarations=[{"acquisition": "dynamic", "name": "x"}]
        )
        as_static = compute_semantic_fingerprint(
            **base, observable_declarations=[{"acquisition": "static", "name": "x"}]
        )
        assert as_dynamic != as_static

    def test_declaring_an_observable_moves_a_real_manifest_fingerprint(self, manifest):
        before = compose_run_task_bindings(str(manifest)).semantic_fingerprint
        path = _write(
            manifest,
            lambda raw: raw.update(
                {"dynamic_observables": [_entry("MeanTargetObservable", "mean_target")]}
            ),
        )
        assert compose_run_task_bindings(path).semantic_fingerprint != before


def _fingerprint_kwargs() -> dict:
    """A minimal, valid argument set for the fingerprint authority.

    Deliberately synthetic: these tests assert how the function COMBINES its
    arguments, so binding them to a real task's values would couple them to
    that task's declarations for no gain.
    """
    import json

    from agent.schemas.task_config import ForwardContract
    from execute_tools.dataset_config import DatasetProfile

    profile_path = os.path.join(
        REPO_ROOT, "examples", "quickstart", "declared", "dataset_profile.json"
    )
    with open(profile_path) as handle:
        profile = DatasetProfile.model_validate(json.load(handle))

    return {
        "task_data_path_id": "probe_task",
        "dataset_profile": profile,
        "metric_declaration": {"id": "probe"},
        # A str reaches the "explicit config" branch, so no private Health
        # module is imported here just to name a binding kind.
        "task_health_binding": "/probe/health.yaml",
        "task_health_content": None,
        "interpretation_blocks": None,
        "task_description": "probe",
        "forward_contract": ForwardContract(),
        "plugins": (),
    }


# ---------------------------------------------------------------------------
# (d) Names are the join key
# ---------------------------------------------------------------------------


class TestNameUniqueness:
    def test_a_duplicate_name_within_one_section_is_refused(self, manifest):
        path = _write(
            manifest,
            lambda raw: raw.update(
                {
                    "dynamic_observables": [
                        _entry("MeanTargetObservable", "dup"),
                        _entry("OutputMeanObservable", "dup"),
                    ]
                }
            ),
        )
        with pytest.raises(TaskCompositionError, match="already declared"):
            compose_run_task_bindings(path)

    def test_a_name_reused_ACROSS_the_two_sections_is_refused(self, manifest):
        """The cross-section case a per-section check would miss.

        Both families land in carriers keyed by name — a per-epoch series and
        a static mapping — and the report joins them into one table. A shared
        name makes "which one is this" unanswerable at exactly the site that
        displays them.
        """
        path = _write(
            manifest,
            lambda raw: raw.update(
                {
                    "dynamic_observables": [_entry("MeanTargetObservable", "shared")],
                    "static_observables": [_entry("ParameterCountObservable", "shared")],
                }
            ),
        )
        with pytest.raises(TaskCompositionError, match="already declared"):
            compose_run_task_bindings(path)


# ---------------------------------------------------------------------------
# (e) Out-of-tree identity, and the child-side entrypoint
# ---------------------------------------------------------------------------


class TestOutOfTreeIdentityAndChildResolution:
    def test_editing_an_observable_plugin_moves_the_run_identity(self, manifest, tmp_path):
        """The reason the plugin digest must join the fingerprint.

        Without it, an edited observable would leave run identity unchanged
        and a resume would accept a run measuring something different from
        the one it is resuming.
        """
        local = tmp_path / "_local_obs.py"
        shutil.copy(PLUGIN_FIXTURE, local)
        path = _write(
            manifest,
            lambda raw: raw.update(
                {
                    "dynamic_observables": [
                        {
                            "name": "mean_target",
                            "implementation": {
                                "file": str(local),
                                "symbol": "MeanTargetObservable",
                            },
                        }
                    ]
                }
            ),
        )
        before = compose_run_task_bindings(path).semantic_fingerprint
        local.write_text(local.read_text() + "\n# an edit that changes nothing observable\n")
        assert compose_run_task_bindings(path).semantic_fingerprint != before

    def test_the_child_entrypoint_composes_the_same_declaration(self, manifest):
        """The training child resolves observables through this authority.

        It must agree with the parent's composition: a child that composed a
        different set would execute arithmetic the run's identity does not
        pin.
        """
        path = _write(
            manifest,
            lambda raw: raw.update(
                {
                    "dynamic_observables": [_entry("MeanTargetObservable", "mean_target")],
                    "static_observables": [
                        _entry("ParameterCountObservable", "trainable_parameters")
                    ],
                }
            ),
        )
        parent = compose_run_task_bindings(path).observables
        child = compose_observables_from_manifest(path)
        assert [d.name for d in child.dynamic] == [d.name for d in parent.dynamic]
        assert [s.name for s in child.static] == [s.name for s in parent.static]
        assert type(child.dynamic[0].implementation).__name__ == "MeanTargetObservable"

    def test_the_child_entrypoint_on_an_undeclared_manifest_is_empty(self, manifest):
        observables = compose_observables_from_manifest(str(manifest))
        assert observables.dynamic == ()
        assert observables.static == ()
        assert not observables
