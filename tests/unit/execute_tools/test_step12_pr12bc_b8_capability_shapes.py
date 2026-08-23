"""Step 12 / PR-12bc — B8: four capability shapes through ONE transport path.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12bc_generic_task_boundary_closure.md`` §M / B8; ledger §Q.B8.

B1-B7 built the capability, the ABI and the transport against ONE real task.
B8's job is to prove the abstraction is not quietly shaped to it. Four shapes:

```text
TIDMAD     {partition: [segment indices]}   a mapping of index lists
Pets       rows: (PetsItem, ...)            a tuple of identity rows
DAVIS      rows: (DavisClip, ...)           a tuple of identity rows
ANONYMOUS  tiles: ((z, y, x), ...)          3-D coordinates, no `rows`,
                                            no partition indices, no 1-D
                                            index space at all
```

The anonymous shape is **deterministic stress evidence only** - it is not a
task package and is **not graduation evidence** (that is 12e's). It exists so
CAP-SCOPE is stressed by a shape nobody designed for BEFORE a fourth real task
arrives, rather than being quietly fitted to three known ones.

**No real Pets or DAVIS execution here** — that is 12d. These build,
serialize, round-trip and transport; nothing materializes a dataset.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest
from pydantic import BaseModel, ConfigDict, Field

from execute_tools.davis_data_path import DavisClip, DavisScope, DavisTaskDataPath
from execute_tools.pets_data_path import PetsItem, PetsScope, PetsTaskDataPath
from execute_tools.scope_artifact import (
    TRAINING_SCOPE_STEM,
    read_scope_artifact,
    scope_artifact_path,
    write_scope_artifact,
)
from execute_tools.task_data_path import (
    ScopeBuildRequest,
    declares_scope_capability,
    deserialize_rows_scope,
)
from execute_tools.tidmad_data_path import TidmadScope, TidmadTaskDataPath

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PETS_MANIFEST = (
    REPO_ROOT / "examples" / "oxford_iiit_pet" / "data" / "manifests" / "gate2_train.csv"
)
DAVIS_CLIPS = (
    REPO_ROOT / "examples" / "davis_future_prediction" / "data" / "manifests" / "clips.csv"
)


def _request(**kw) -> ScopeBuildRequest:
    base = {
        "round_kind": "trial",
        "selection_strategy": "snapshot",
        "portion": 0.5,
        "seed": 7,
        "task_parameters": {"seg_size": 10_000},
    }
    base.update(kw)
    return ScopeBuildRequest(**base)


# ======================================================================
# The ANONYMOUS fourth shape
# ======================================================================


class _Tile(BaseModel):
    """A 3-D coordinate. Deliberately not an index into anything."""

    model_config = ConfigDict(frozen=True)

    z: int = Field(ge=0)
    y: int = Field(ge=0)
    x: int = Field(ge=0)


class _VolumeScope(BaseModel):
    """A scope shaped like NONE of the three real tasks.

    No ``rows``. No ``{partition: [indices]}``. No 1-D index space at all —
    the selectable unit is a 3-D coordinate, so a framework that had quietly
    assumed "a scope is a list of things indexed by an integer" fails here.
    """

    model_config = ConfigDict(frozen=True)

    tiles: tuple[_Tile, ...] = Field(min_length=1)


class _VolumeTaskDataPath:
    """A synthetic implementation for the anonymous shape.

    Four-method seam + the optional capability. It materializes nothing: B8
    proves the abstraction TRANSPORTS an unfamiliar shape, not that a fictional
    task can train.
    """

    task_data_path_id = "b8_anonymous_volume"
    _SCOPE_KIND = "volume_scope_v1"

    def __init__(self, *, extent: tuple[int, int, int] = (2, 3, 4)) -> None:
        self._extent = extent

    def _scope(self, scope: object) -> _VolumeScope:
        if not isinstance(scope, _VolumeScope):
            raise TypeError(
                f"volume data path requires a _VolumeScope, got {type(scope).__name__} "
                "— the binding and the scope object must come from the same task."
            )
        return scope

    def training_dataset(self, scope, params):  # pragma: no cover - never materialized
        raise AssertionError("B8 materializes nothing")

    def validation_dataset(self, scope, params):  # pragma: no cover
        raise AssertionError("B8 materializes nothing")

    def write_deliverable(self, outputs, request):  # pragma: no cover
        raise AssertionError("B8 writes nothing")

    def read_evaluation_payload(self, request):  # pragma: no cover
        raise AssertionError("B8 reads nothing")

    def _select(self, request: ScopeBuildRequest) -> _VolumeScope:
        nz, ny, nx = self._extent
        every = tuple(_Tile(z=z, y=y, x=x) for z in range(nz) for y in range(ny) for x in range(nx))
        keep = max(1, round(request.portion * len(every)))
        return _VolumeScope(tiles=every[:keep])

    def build_training_scope(self, request):
        return self._select(request)

    def build_eval_scope(self, request):
        return self._select(request)

    def serialize_scope(self, scope):
        s = self._scope(scope)
        return json.dumps(
            {"kind": self._SCOPE_KIND, "tiles": [t.model_dump() for t in s.tiles]},
            sort_keys=True,
            separators=(",", ":"),
        )

    def deserialize_scope(self, payload):
        decoded = json.loads(payload)
        if not isinstance(decoded, dict) or decoded.get("kind") != self._SCOPE_KIND:
            raise ValueError(
                f"scope payload declares kind {decoded.get('kind') if isinstance(decoded, dict) else None!r}, "
                f"not {self._SCOPE_KIND!r}."
            )
        return _VolumeScope(tiles=tuple(_Tile.model_validate(t) for t in decoded["tiles"]))


# ======================================================================
# The four shapes
# ======================================================================


def _shapes():
    """`(name, implementation, request)` for each shape.

    Built lazily so a missing committed manifest skips its own row rather than
    failing collection for the others.
    """
    out = [
        ("tidmad", TidmadTaskDataPath(), _request()),
        ("anonymous", _VolumeTaskDataPath(), _request()),
    ]
    if PETS_MANIFEST.exists():
        out.append(("pets", PetsTaskDataPath(manifest_path=str(PETS_MANIFEST)), _request()))
    if DAVIS_CLIPS.exists():
        out.append(("davis", DavisTaskDataPath(clips_path=str(DAVIS_CLIPS)), _request()))
    return out


SHAPES = _shapes()
SHAPE_IDS = [n for n, _, _ in SHAPES]


class TestAllFourShapesUseTheSamePath:
    def test_every_shape_is_present(self):
        """A silently-skipped contrast task would make every test below pass
        while proving only that TIDMAD works.
        """
        assert set(SHAPE_IDS) == {"tidmad", "pets", "davis", "anonymous"}, (
            f"only {SHAPE_IDS} were exercised — a committed manifest is missing, "
            f"and the stress evidence is not what it claims"
        )

    @pytest.mark.parametrize(("name", "impl", "req"), SHAPES, ids=SHAPE_IDS)
    def test_it_declares_the_capability(self, name, impl, req):
        assert declares_scope_capability(impl) is True

    @pytest.mark.parametrize(("name", "impl", "req"), SHAPES, ids=SHAPE_IDS)
    def test_it_builds_serializes_and_round_trips(self, name, impl, req):
        built = impl.build_training_scope(req)
        payload = impl.serialize_scope(built)
        assert impl.deserialize_scope(payload) == built

    @pytest.mark.parametrize(("name", "impl", "req"), SHAPES, ids=SHAPE_IDS)
    def test_it_crosses_the_ONE_transport_path(self, name, impl, req, tmp_path):
        """The whole point: four unrelated payload shapes through the SAME
        artifact + digest ABI, which never looks inside any of them.
        """
        payload = impl.serialize_scope(impl.build_training_scope(req))
        path = scope_artifact_path(str(tmp_path), TRAINING_SCOPE_STEM, f"exp_{name}")
        digest = write_scope_artifact(path, payload)
        assert impl.deserialize_scope(read_scope_artifact(path, digest)) == impl.deserialize_scope(
            payload
        )

    @pytest.mark.parametrize(("name", "impl", "req"), SHAPES, ids=SHAPE_IDS)
    def test_its_serialization_is_canonical(self, name, impl, req):
        a = impl.serialize_scope(impl.build_training_scope(req))
        b = impl.serialize_scope(impl.build_training_scope(req))
        assert a == b
        assert " " not in a.replace(" ", "") or True  # compact separators
        assert a == json.dumps(json.loads(a), sort_keys=True, separators=(",", ":"))


class TestTheAnonymousShapeIsGenuinelyDifferent:
    def test_it_is_not_rows_shaped(self):
        """If the fixture drifted into a `rows` tuple it would stop stressing
        anything — it would just be a third copy of the contrast shape.
        """
        assert "rows" not in _VolumeScope.model_fields
        assert set(_VolumeScope.model_fields) == {"tiles"}

    def test_it_has_no_one_dimensional_index_space(self):
        """Its selectable unit is a 3-D coordinate. A framework that had
        assumed "a scope is a list indexed by an integer" fails here.
        """
        assert set(_Tile.model_fields) == {"z", "y", "x"}

    def test_it_is_not_registered_and_is_not_a_task_package(self):
        """Stress evidence only. Registering it would make it look like a
        fourth task, which is 12e's and is explicitly NOT claimed here.
        """
        from execute_tools.task_data_path import registered_task_data_path_ids

        assert "b8_anonymous_volume" not in registered_task_data_path_ids()


class TestCrossTaskScopeInjectionIsRefusedForEveryPair:
    """The pairing RULE, over all 12 ordered pairs.

    Closing the pairing GAP (B6) must not soften the RULE: a scope built by
    one task and handed to another is refused, whichever pair it is.
    """

    @pytest.mark.parametrize(("name", "impl", "req"), SHAPES, ids=SHAPE_IDS)
    def test_every_foreign_scope_object_is_refused(self, name, impl, req):
        foreign_objects = {
            "tidmad": TidmadScope(sample_set={0: [1]}, seg_size=64),
            "pets": PetsScope(
                rows=(PetsItem(image_id="x", class_index=0, official_class_id=1, scope="train"),)
            ),
            "davis": DavisScope(rows=(DavisClip(sequence_name="s", start_frame=0),)),
            "anonymous": _VolumeScope(tiles=(_Tile(z=0, y=0, x=0),)),
        }
        for other, scope in foreign_objects.items():
            if other == name:
                continue
            with pytest.raises(TypeError, match="same task"):
                impl.serialize_scope(scope)

    @pytest.mark.parametrize(("name", "impl", "req"), SHAPES, ids=SHAPE_IDS)
    def test_every_foreign_PAYLOAD_is_refused_by_kind(self, name, impl, req):
        payloads = {
            "tidmad": '{"kind":"tidmad_scope_v1","sample_set":{"0":[1]},"seg_size":64}',
            "pets": '{"kind":"pets_scope_v1","rows":[]}',
            "davis": '{"kind":"davis_scope_v1","rows":[]}',
            "anonymous": '{"kind":"volume_scope_v1","tiles":[]}',
        }
        for other, payload in payloads.items():
            if other == name:
                continue
            with pytest.raises(ValueError, match="kind"):
                impl.deserialize_scope(payload)


class TestTheContrastCapabilitiesTakeTaskInstanceConfig:
    """§D.1: an implementation that needs its own sources to BUILD scopes
    receives them at CONSTRUCTION — never by importing ``examples/``.
    """

    def test_a_regime_A_instance_refuses_to_BUILD_by_name(self):
        for impl, word in ((PetsTaskDataPath(), "manifest"), (DavisTaskDataPath(), "manifest")):
            with pytest.raises(ValueError, match=word):
                impl.build_training_scope(_request())

    def test_a_configured_instance_builds_from_its_OWN_manifest(self):
        pets = PetsTaskDataPath(manifest_path=str(PETS_MANIFEST))
        built = pets.build_training_scope(_request(portion=0.1, seed=3))
        assert isinstance(built, PetsScope)
        assert len(built.rows) >= 1

    def test_anchors_has_no_content_for_a_task_that_declares_none(self):
        """The framework NAMES the strategy; the TASK supplies the content.
        A task with no declared representatives says so, rather than
        inventing a set.
        """
        pets = PetsTaskDataPath(manifest_path=str(PETS_MANIFEST))
        with pytest.raises(ValueError, match="declares no anchor"):
            pets.build_training_scope(_request(selection_strategy="anchors"))

    def test_an_out_of_range_target_is_refused_against_the_TASKS_own_bound(self):
        pets = PetsTaskDataPath(manifest_path=str(PETS_MANIFEST))
        with pytest.raises(ValueError, match="outside this task's"):
            pets.build_training_scope(
                _request(selection_strategy="target", target_partitions=(10**9,))
            )

    def test_production_imports_no_examples_package(self):
        """The governance census's property, asserted where the contrast
        capabilities live: they read the task's own FILES, by path, at
        construction — which is never a framework import of `examples/`.
        """
        for rel in ("execute_tools/pets_data_path.py", "execute_tools/davis_data_path.py"):
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    assert not (node.module or "").startswith("examples")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        assert not alias.name.startswith("examples")


class TestTheSharedRowsCodecIsNotOverApplied:
    def test_tidmad_does_NOT_use_it(self):
        """Pets and DAVIS share a codec because they share a SHAPE. TIDMAD's
        scope is a mapping of index lists — a genuinely different shape — and
        forcing one codec over both would be an abstraction invented for
        symmetry rather than for a shared property.
        """
        src = (REPO_ROOT / "execute_tools" / "tidmad_data_path.py").read_text(encoding="utf-8")
        assert "deserialize_rows_scope" not in src

    def test_it_refuses_a_row_that_fails_the_tasks_own_model(self):
        with pytest.raises(ValueError, match="malformed"):
            deserialize_rows_scope(
                '{"kind":"davis_scope_v1","rows":[{"sequence_name":"s"}]}',
                "davis_scope_v1",
                DavisClip,
                DavisScope,
            )

    def test_it_names_a_missing_rows_key(self):
        with pytest.raises(ValueError, match=r"missing \['rows'\]"):
            deserialize_rows_scope('{"kind":"pets_scope_v1"}', "pets_scope_v1", PetsItem, PetsScope)
