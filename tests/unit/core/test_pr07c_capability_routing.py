"""Dataset availability is decided by the TASK, not by generic runtime-control.

Step 07 / PR 07c C4. Two `TIDMAD_DATA_DIR` fallbacks lived inside
`core/runtime_control/`:

    bootstrap.py:513-520      `_dataset_check` imported it to decide readiness
    probe_production.py:210   filled in for an absent `data_dir`

Both are gone. What they were is worth stating precisely, because the fix is
easy to over-claim: before D14, `probe_available=False` is still the CORRECT
answer for Oxford-IIIT Pet and DAVIS. What changes is *who decides and whether
they say why*.

    BAD  (before):  non-TIDMAD -> core sees no TIDMAD_DATA_DIR
                               -> silently unavailable
    GOOD (07c):     non-TIDMAD -> the task's capability resolver
                               -> available, OR explicitly unavailable
                                  for a task-owned, stated reason

So every assertion below is on the REASON and the task identity. Asserting
`probe_available is False` alone would pass equally for the silent fallback
this commit removes — which is exactly how the defect survived.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_CONTROL = REPO_ROOT / "core" / "runtime_control"


class TestGenericRuntimeControlNamesNoTaskDataset:
    """Checkpoint D. The mutation this guards is re-adding the import."""

    @staticmethod
    def _imported_names(path: Path) -> set[str]:
        """Every module and symbol this file IMPORTS, at any nesting depth.

        Over the AST rather than the text: three of these modules DOCUMENT the
        removed fallback in a docstring so a future reader knows what changed,
        and a substring scan cannot tell an explanation from an instruction.
        A comment is not an import; an import is what makes generic code
        depend on one task's data layer.
        """
        names: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names.add(module)
                names.update(f"{module}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
        return names

    def test_no_module_under_runtime_control_imports_the_task_data_layer(self):
        offenders: dict[str, set[str]] = {}
        for path in sorted(RUNTIME_CONTROL.rglob("*.py")):
            hits = {
                name
                for name in self._imported_names(path)
                if name == "execute_tools.data_paths"
                or name.startswith("execute_tools.data_paths.")
                or name.endswith(".TIDMAD_DATA_DIR")
            }
            if hits:
                offenders[str(path.relative_to(REPO_ROOT))] = hits
        assert offenders == {}, (
            "generic runtime-control imports a task's data layer: "
            f"{offenders}. Availability must be decided by a task-owned "
            "ResolvedMeasurementCapability the caller passes in."
        )

    def test_the_guard_would_notice_the_import_coming_back(self, tmp_path):
        """Non-vacuity. A scan that found nothing because it was looking in
        the wrong place would pass this module forever."""
        planted = tmp_path / "regressed.py"
        planted.write_text("from execute_tools.data_paths import TIDMAD_DATA_DIR\n")
        hits = {
            name
            for name in self._imported_names(planted)
            if name.endswith(".TIDMAD_DATA_DIR") or name == "execute_tools.data_paths"
        }
        assert hits


class TestTheTaskAwareLauncherSuppliesTheCapability:
    """The other half: a parameter nobody passes is a boundary, not a fix."""

    def test_the_bootstrap_script_resolves_and_passes_one(self):
        source = (REPO_ROOT / "scripts" / "runtime_bootstrap.py").read_text(encoding="utf-8")
        assert "resolve_tidmad_measurement_capability" in source
        assert "measurement_capability=resolve_tidmad_measurement_capability(" in source

    def test_production_dependencies_accepts_one_rather_than_resolving_it(self):
        import inspect

        from core.runtime_control.bootstrap import production_dependencies

        assert "measurement_capability" in inspect.signature(production_dependencies).parameters

    def test_the_launcher_forwards_its_data_dir_override(self):
        """`--data-dir` must reach the resolver, or the operator flag that
        exists for pointing at another copy of the data silently does
        nothing for the readiness verdict."""
        source = (REPO_ROOT / "scripts" / "runtime_bootstrap.py").read_text(encoding="utf-8")
        assert "resolve_tidmad_measurement_capability(args.data_dir)" in source


class TestThePersistentTracksReportAnHonestUnavailability:
    """§2a.2 three-track breadth, at each track's CURRENT maturity.

    Neither track has a dataset adapter, a `DatasetProfile` or any data before
    D14, so `probe_available=False` is the truthful answer. The point is that a
    TASK-OWNED resolver says so, naming itself and its reason — not that generic
    code inferred it from an absent TIDMAD path.

    The identities come from each pack's own module (`PACK_DIRNAME` and its
    declared geometry), so nothing is invented here and no example artifact is
    added or changed.
    """

    @staticmethod
    def _resolve_for(track: str, shape_class: str):
        from core.runtime_control.measurement_capability import resolve_measurement_capability

        return resolve_measurement_capability(
            task_identity=track,
            dataset_adapter=f"{track}_pack_declared_only",
            data_shape_class=shape_class,
            # No data exists for either track before D14. Passing `None` is the
            # honest input, and the resolver refuses to default it.
            dataset_root=None,
        )

    @pytest.fixture(scope="class")
    def tracks(self):
        from tools.example_packs import davis_future_prediction as davis
        from tools.example_packs import oxford_iiit_pet as pets

        return {
            pets.PACK_DIRNAME: f"rgb_classification_classes{pets.NUM_CLASSES}",
            davis.PACK_DIRNAME: (
                f"rgb_video_c{davis.CHANNELS}_h{davis.HEIGHT}_w{davis.WIDTH}"
                f"_ctx{davis.CONTEXT_FRAMES}_fut{davis.FUTURE_FRAMES}"
            ),
        }

    def test_each_track_is_unavailable_for_a_stated_task_owned_reason(self, tracks):
        for track, shape_class in tracks.items():
            capability = self._resolve_for(track, shape_class)
            assert capability.probe_available is False
            # The load-bearing assertion. A bare False is what the silent
            # fallback produced too.
            assert (capability.unavailability_reason or "").strip(), (
                f"{track} reports unavailable with no reason"
            )
            assert capability.task_identity == track
            assert capability.data_shape_class == shape_class
            # `detail` is the operator-facing line, and it must carry BOTH.
            assert track in capability.detail
            assert capability.unavailability_reason in capability.detail

    def test_neither_track_is_answered_as_tidmad(self, tracks):
        """The defect that would survive every other assertion here: generic
        infrastructure substituting TIDMAD's answer for a task it does not
        know. If that happened, the identity — not the boolean — is where it
        shows."""
        for track, shape_class in tracks.items():
            capability = self._resolve_for(track, shape_class)
            assert "tidmad" not in capability.task_identity.lower()
            assert "tidmad" not in capability.dataset_adapter.lower()
            assert "tidmad" not in capability.detail.lower()

    def test_the_two_tracks_do_not_share_an_identity(self, tracks):
        """Two tasks that resolve to the same capability identity would be
        interchangeable for measurement-reuse purposes, which they are not."""
        resolved = [self._resolve_for(t, s) for t, s in tracks.items()]
        assert resolved[0].task_identity != resolved[1].task_identity
        assert resolved[0].data_shape_class != resolved[1].data_shape_class

    def test_no_execution_maturity_was_added(self, tracks):
        """The mechanical half of §2.2's non-goal — **RE-SCOPED BY D14-3**
        (D14 is the milestone that ADDS execution maturity; 07c's job was to
        add none of it).

        Still asserted: 07c's routing obligations read the packs' DECLARED
        artifacts and add no dataset adapter, no `DatasetProfile`, no
        download, and no `resolved/` tree. What D14 legitimately added is
        reference PLUGIN SOURCE at `examples/<pack>/plugins/*.py` (loaded
        dynamically, never imported by production — the same relaxation the
        governance guards in `tests/unit/examples/` now encode); anything
        else under a pack is still an execution path hiding where this pin
        forbids one."""
        for track in tracks:
            pack = REPO_ROOT / "examples" / track
            offenders = [
                p
                for p in pack.rglob("*.py")
                if p.parent != pack / "plugins"  # sanctioned plugin source (D14)
            ]
            assert offenders == [], offenders
            assert not (pack / "resolved").exists(), (
                f"{track} grew a resolved/ tree; that is D14 execution maturity"
            )
