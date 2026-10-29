"""The quickstart example bundle zip: reproducible bytes and the same task as the checkout."""

import zipfile
from pathlib import Path

import pytest
import yaml

from execute_tools import task_data_path as tdp
from execute_tools.task_registration_scope import run_registration_scope
from tools.release.build_example_bundle import FIXED_TIME, SHIPPED_MANIFEST, build
from workflows.task_composition import compose_run_task_bindings

PACK_PREFIX = "../../examples/quickstart/"


def _unpack(zip_path: Path, into: Path) -> Path:
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(into)
    (top,) = into.iterdir()
    return top


def test_two_builds_produce_identical_bytes_with_fixed_metadata(tmp_path):
    """Defect: the zip depends on build time, file order or local modes.

    Fails if two builds differ byte for byte, or if any entry carries a
    timestamp other than 1980-01-01, a mode other than 0644, a compression, or
    an order other than sorted (each would make a re-release unverifiable).
    """
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    one, two = build(first, "9.9.9"), build(second, "9.9.9")
    assert one.name == "siderius-example-quickstart-9.9.9.zip"
    assert one.read_bytes() == two.read_bytes()
    with zipfile.ZipFile(one) as archive:
        infos = archive.infolist()
    names = [info.filename for info in infos]
    assert names == sorted(names)
    assert all(name.startswith("siderius-example-quickstart-9.9.9/") for name in names)
    for info in infos:
        assert info.date_time == FIXED_TIME
        assert info.external_attr >> 16 == 0o100644
        assert info.compress_type == zipfile.ZIP_STORED


@pytest.fixture
def isolated_task_registry(monkeypatch):
    """An empty task-data-path registry for this test, restored afterwards.

    Another test in the same process may leave ``quickstart_tabular``
    registered from a modified copy of the plugin; the registry then (rightly)
    refuses the checkout plugin as different content. The test needs the
    checkout's own registration, so it starts from an empty roster, as
    ``test_step12_pr12e_negative_controls`` does.
    """
    monkeypatch.setattr(tdp, "_REGISTRY", {})
    monkeypatch.setattr(tdp, "_CONTENT", {})


def test_bundle_task_is_self_contained_and_composes_like_the_checkout_quickstart(
    tmp_path, isolated_task_registry
):
    """Defect: the bundle's task drifts from examples/quickstart or still points outside itself.

    The bundle manifest spells references package-relative, and the plugin
    reference spelling is part of the semantic fingerprint, so the comparison
    puts the bundle's files back in the checkout layout: the shipped manifest
    over the bundle's ``task/`` files, with the bundle manifest's own
    non-path values. Fails if a declaration or plugin byte differs, a file is
    missing, a manifest value was changed by the rewrite, or the bundle
    manifest needs ``../`` or an absolute path to compose.
    """
    (tmp_path / "zip").mkdir()
    package = _unpack(build(tmp_path / "zip", "0"), tmp_path / "unpacked") / "task"
    manifest = package / "task.yaml"
    assert "../" not in manifest.read_text()

    def back_to_checkout(value):
        if isinstance(value, dict):
            return {key: back_to_checkout(item) for key, item in value.items()}
        if isinstance(value, list):
            return [back_to_checkout(item) for item in value]
        if (
            isinstance(value, str)
            and (package / value).exists()
            and value.split("/")[0]
            in (
                "declared",
                "plugins",
            )
        ):
            return PACK_PREFIX + value
        return value

    layout = tmp_path / "layout"
    restored = layout / "configs" / "task_composition" / "quickstart.yaml"
    restored.parent.mkdir(parents=True)
    restored.write_text(yaml.safe_dump(back_to_checkout(yaml.safe_load(manifest.read_text()))))
    pack = layout / "examples" / "quickstart"
    pack.mkdir(parents=True)
    for folder in ("declared", "plugins"):
        (package / folder).rename(pack / folder)
    with run_registration_scope():
        expected = compose_run_task_bindings(str(SHIPPED_MANIFEST)).semantic_fingerprint
    with run_registration_scope():
        assert compose_run_task_bindings(str(restored)).semantic_fingerprint == expected
    # The bundle manifest composes on its own, inside its own folder.
    for folder in ("declared", "plugins"):
        (pack / folder).rename(package / folder)
    with run_registration_scope():
        bundled = compose_run_task_bindings(str(manifest))
    assert bundled.task_data_path_id == "quickstart_tabular"
