"""Cross-pack governance guards for `examples/` (Step-07 PR0, design §3.5 / C4).

Each guard's docstring names (1) the defect only it catches and (2) its
validity window + relaxation owner. PR0-only guards are MATURITY PINS, not
permanent repository rules — relaxing one is the named owner's explicit act,
recorded in that owner's design, never a silent deletion. Guards marked
[permanent] encode roadmap §22.23 rules (separability, honest STATUS, the
three mandatory roots).

Every guard is written as a function of a root so a `tmp_path` mirror can
prove it fires (or, for the presence guard, that it does NOT reject an extra
root). The checkout root is derived from ``__file__`` (CLAUDE.md portability).
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_ROOT = REPO_ROOT / "examples"

#: Production packages that must never depend on the example packs or the
#: PR0 tooling (roadmap §22.23.9 separability; design C4 (c)).
PRODUCTION_PACKAGES = (
    "src/core",
    "src/agent",
    "src/nodes",
    "src/execute_tools",
    "src/workflows",
    "src/ml_models",
    "src/dashboard",
    "src/tools",
    "scripts",
)
FORBIDDEN_IMPORT_ROOTS = ("examples", "tools.example_packs")
PARALLEL_COPY_KEYS = ("task_description", "forward_contract")
REQUIRED_PACK_DOCS = ("README.md", "PROVENANCE.md", "STATUS.md")
MATURITY_LEVEL = re.compile(r"\bL[0-4]\b")
WORKFLOW_DECLARATIONS_DIR = "workflow_declarations"
#: Framework-owned release sources of the quickstart example bundle
#: (``tools.release.build_example_bundle``): not a scientific pack, and its one
#: Python file is the bundle's data writer, shipped as a file, never imported.
CONSOLE_BUNDLE_DIR = "console_bundle"
CONSOLE_BUNDLE_SOURCES = frozenset({"examples/console_bundle/fetch_data.py"})
WORKFLOW_DECLARATION_SOURCES = frozenset(
    {
        "examples/workflow_declarations/managed_reusable_candidate.py",
        "examples/workflow_declarations/native_training.py",
        "examples/workflow_declarations/reusable_candidate.py",
        "examples/workflow_declarations/reusable_training.py",
    }
)


# ---------------------------------------------------------------------------
# guard implementations (pure functions of a root)
# ---------------------------------------------------------------------------


def _python_files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def _composition_bound_task_configs(repo_root: Path) -> frozenset[Path]:
    """Every path a SHIPPED composition manifest binds as its ``task_config``.

    Step 12 / PR-12d D5 — the evidence that re-scopes guard (a). A pack's own
    task config is legitimate exactly when a manifest RESOLVES it; a YAML
    nobody binds is still the hand-written parallel copy the guard was written
    against. Refs resolve against the manifest's own directory, which is the
    rule ``workflows/task_composition.py::_resolve_path`` applies.
    """
    bound: set[Path] = set()
    manifests = repo_root / "configs" / "task_composition"
    if not manifests.is_dir():
        return frozenset()
    for manifest in sorted(manifests.glob("*.yaml")):
        payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        section = payload.get("task_config") if isinstance(payload, dict) else None
        ref = section.get("config") if isinstance(section, dict) else None
        if isinstance(ref, str) and ref.strip():
            bound.add((manifest.parent / ref).resolve())
    return frozenset(bound)


def _yaml_parallel_copies(
    examples_root: Path, bound_task_configs: frozenset[Path] = frozenset()
) -> list[tuple[Path, str]]:
    """(path, key) for every YAML under examples/ whose TOP-LEVEL mapping
    declares a runtime-authority key. Prose mentioning the word is fine.

    ``bound_task_configs`` are the files a shipped composition manifest
    actually resolves — those are BOUND declarations, not parallel copies, and
    the default empty set means "nothing is exempt" so the plant below still
    exercises the original rule.
    """
    offenders: list[tuple[Path, str]] = []
    for path in sorted(p for p in examples_root.rglob("*") if p.suffix in (".yaml", ".yml")):
        if path.resolve() in bound_task_configs:
            continue
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            offenders.extend((path, key) for key in PARALLEL_COPY_KEYS if key in payload)
    return offenders


def _forbidden_imports(module_path: Path) -> list[str]:
    """Import targets in ``module_path`` that resolve into a forbidden root."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            targets.append(node.module)
            # `from tools import example_packs` names the package as an alias
            targets.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return [
        t
        for t in targets
        if any(t == root or t.startswith(root + ".") for root in FORBIDDEN_IMPORT_ROOTS)
    ]


def _production_importers(repo_root: Path) -> dict[str, list[str]]:
    offenders: dict[str, list[str]] = {}
    for package in PRODUCTION_PACKAGES:
        base = repo_root / package
        if not base.is_dir():
            continue
        for module in _python_files_under(base):
            hits = _forbidden_imports(module)
            if hits:
                offenders[str(module.relative_to(repo_root))] = hits
    return offenders


def _pack_dirs(examples_root: Path) -> list[Path]:
    # Shipped packs are tracked; ignored remnants of retired packs are user state.
    names = {
        Path(p).parts[1]
        for p in _tracked(examples_root.parent, examples_root.name)
        if len(Path(p).parts) > 2
    }
    names.discard(WORKFLOW_DECLARATIONS_DIR)
    names.discard(CONSOLE_BUNDLE_DIR)
    return sorted(examples_root / name for name in names)


def _tracked(repo_root: Path, rel: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--", rel],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        timeout=120,
    )
    if result.returncode != 0:  # not a git checkout (e.g. a source tarball)
        pytest.skip(f"not a git checkout: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line]


# ---------------------------------------------------------------------------
# (a) MATURITY PIN — no parallel task_description / forward_contract YAML
#     [valid: before Step 12 — owner: Step 12]
# ---------------------------------------------------------------------------


def test_no_yaml_under_examples_declares_an_UNBOUND_runtime_authority_key() -> None:
    """[MATURITY PIN, RE-SCOPED BY Step 12 / PR-12d D5 (the named relaxation
    owner) — original: NO top-level `task_description` / `forward_contract`
    YAML under `examples/` at all, valid through Step 11]

    Defect caught, unchanged in substance: a YAML under `examples/` declares a
    TOP-LEVEL `task_description` / `forward_contract` that NOTHING resolves —
    a hand-written parallel copy of a runtime task authority. Not caught
    elsewhere: `test_step04b_task_description_single_source` scans `configs/`
    only. Inspects YAML top-level KEYS, so prose (README) may name the word
    freely.

    What D5 changed is the PREMISE, not the rule. Before task composition,
    `configs/task_config.yaml` was the single runtime authority and any second
    copy was by definition parallel. A composed run reads whatever its
    manifest's `task_config.config:` names, so a pack's own declaration is now
    the legitimate location (Q-12d-1: task-owned declarations co-locate with
    the pack) — but ONLY when a shipped manifest actually binds it. An
    unbound one is still the original defect, which is why the exemption is
    computed from the manifests rather than allowlisted by filename.
    """
    assert EXAMPLES_ROOT.is_dir()
    bound = _composition_bound_task_configs(REPO_ROOT)
    assert bound, "no shipped composition binds a task config — the exemption is vacuous"
    assert _yaml_parallel_copies(EXAMPLES_ROOT, bound) == []


def test_negative_parallel_copy_yaml_in_mirror_is_detected(tmp_path: Path) -> None:
    """Proves guard (a) fires on a top-level key and NOT on prose or a nested key.

    The fourth case is the Step-12 re-scope: a pack's own task config is not
    an offender **while a shipped manifest BINDS it**. The exemption is the
    binding, never the path — which is what
    `test_negative_an_UNBOUND_pack_task_config_is_still_an_offender` proves
    from the other side, using the one input that can tell the two rules
    apart.
    """
    pack = tmp_path / "examples" / "some_pack"
    (pack / "declared").mkdir(parents=True)
    (pack / "task.yaml").write_text("task_description: parallel copy\nother: 1\n")
    (pack / "notes.yaml").write_text("readme: 'the phrase task_description in prose'\n")
    (pack / "nested.yaml").write_text("meta:\n  forward_contract: {}\n")
    bound_config = pack / "declared" / "task_config.yaml"
    bound_config.write_text("task_description: bound\n")
    offenders = _yaml_parallel_copies(tmp_path / "examples", frozenset({bound_config.resolve()}))
    assert offenders == [(pack / "task.yaml", "task_description")]


def test_negative_an_UNBOUND_pack_task_config_is_still_an_offender() -> None:
    """The re-scope's own falsifier: the exemption is BINDING, not location.

    Fails when someone widens `_yaml_parallel_copies` to allow any file called
    `declared/task_config.yaml` — the shipped Pets declaration would stay
    green either way, so only a file in the sanctioned LOCATION that no
    manifest resolves can tell the two rules apart.
    """
    bound = _composition_bound_task_configs(REPO_ROOT)
    shipped = [pack / "declared" / "task_config.yaml" for pack in _pack_dirs(EXAMPLES_ROOT)]
    assert shipped, "no pack ships a task config, so this proves nothing"
    for path in shipped:
        assert path.resolve() in bound, f"{path} is shipped but no manifest binds it"

    # With NOTHING bound, every one of them is an offender again. That is the
    # whole claim: the location did not change, only the binding did.
    unbound_offenders = _yaml_parallel_copies(EXAMPLES_ROOT, frozenset())
    for path in shipped:
        assert (path, "task_description") in unbound_offenders
    assert _yaml_parallel_copies(EXAMPLES_ROOT, bound) == []


# ---------------------------------------------------------------------------
# (b) MATURITY PIN — no `.py` under examples/   [valid: PR0 / Step 07 — owner: D14]
# ---------------------------------------------------------------------------


def _is_sanctioned_plugin_source(rel_posix: str) -> bool:
    """D14 re-scope: reference plugin SOURCE lives at exactly
    ``examples/<pack>/plugins/*.py``. The four explicit workflow declaration
    examples and the example bundle's ``fetch_data.py`` are also sanctioned;
    these exact-path exceptions do not permit other Python files in those
    framework-owned namespaces."""
    parts = rel_posix.split("/")
    if len(parts) >= 2 and parts[:2] == ["examples", WORKFLOW_DECLARATIONS_DIR]:
        return rel_posix in WORKFLOW_DECLARATION_SOURCES
    if len(parts) >= 2 and parts[:2] == ["examples", CONSOLE_BUNDLE_DIR]:
        return rel_posix in CONSOLE_BUNDLE_SOURCES
    return len(parts) == 4 and parts[0] == "examples" and parts[2] == "plugins"


def test_workflow_declarations_are_not_scientific_example_packs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exclude the framework namespace while retaining unknown tracked packs."""
    monkeypatch.setattr(
        sys.modules[__name__],
        "_tracked",
        lambda _repo_root, _rel: [
            "examples/workflow_declarations/native_training.py",
            "examples/new_scientific_pack/README.md",
            "examples/quickstart/README.md",
        ],
    )
    assert _pack_dirs(EXAMPLES_ROOT) == [
        EXAMPLES_ROOT / "new_scientific_pack",
        EXAMPLES_ROOT / "quickstart",
    ]


def test_python_under_examples_only_as_pack_plugin_source_d14_rescope() -> None:
    """[MATURITY PIN, RE-SCOPED BY D14-2 (the named relaxation owner) —
    original: NO `.py` under examples/, valid through PR0 / Step 07]

    Defect caught: an executable `.py` lands under `examples/` OUTSIDE the
    sanctioned plugin location (`examples/<pack>/plugins/*.py`) — production
    or tooling code hiding in a pack, unchecked by pyright's allowlist and
    the packages list. The sanctioned files are PLUGIN SOURCE loaded
    dynamically through the plugin mechanism (never imported — guard (c)
    stays absolute below)."""
    assert EXAMPLES_ROOT.is_dir(), f"expected layout missing: {EXAMPLES_ROOT}"
    offenders = [
        p
        for p in _python_files_under(EXAMPLES_ROOT)
        if not _is_sanctioned_plugin_source(p.relative_to(REPO_ROOT).as_posix())
    ]
    assert offenders == []
    tracked_offenders = [
        p
        for p in _tracked(REPO_ROOT, "examples")
        if p.endswith(".py") and not _is_sanctioned_plugin_source(p)
    ]
    assert tracked_offenders == []


def test_negative_python_under_examples_mirror_is_detected(tmp_path: Path) -> None:
    """Proves only plugin sources and the four declared scripts are sanctioned."""
    mirror = tmp_path / "examples" / "some_pack"
    (mirror / "plugins").mkdir(parents=True)
    (mirror / "plugins" / "model.py").write_text("PLUGIN_MODEL_TYPE = 'x'\n")
    (mirror / "loader.py").write_text("import os\n")
    workflow = tmp_path / "examples" / WORKFLOW_DECLARATIONS_DIR
    workflow.mkdir()
    (workflow / "native_training.py").write_text("pass\n")
    (workflow / "unexpected.py").write_text("pass\n")
    (workflow / "plugins").mkdir()
    (workflow / "plugins" / "intrusion.py").write_text("pass\n")
    found = _python_files_under(tmp_path / "examples")
    rels = [p.relative_to(tmp_path).as_posix() for p in found]
    offenders = [r for r in rels if not _is_sanctioned_plugin_source(r)]
    assert offenders == [
        "examples/some_pack/loader.py",
        "examples/workflow_declarations/plugins/intrusion.py",
        "examples/workflow_declarations/unexpected.py",
    ]
    assert "examples/some_pack/plugins/model.py" in rels  # detected, sanctioned
    assert "examples/workflow_declarations/native_training.py" in rels


# ---------------------------------------------------------------------------
# (c) PERMANENT — separability: production never imports examples / tools.example_packs
# ---------------------------------------------------------------------------


def test_production_packages_never_import_examples_or_pack_tooling() -> None:
    """[PERMANENT — roadmap §22.23.9 separability]

    Defect caught: a module under a production package imports `examples` or
    `tools.example_packs` — the framework would start depending on an example
    pack or on PR0 tooling (a runtime subsystem it must never be). AST-based:
    catches `import x`, `from x import y`, `from tools import example_packs`;
    string mentions in comments/docstrings do not trip it."""
    for package in PRODUCTION_PACKAGES:
        assert (REPO_ROOT / package).is_dir(), f"expected production package missing: {package}"
    assert _production_importers(REPO_ROOT) == {}


def test_negative_fake_production_importer_is_detected(tmp_path: Path) -> None:
    """Proves guard (c) fires for each import form and stays silent for prose."""
    core = tmp_path / "src/core"
    core.mkdir(parents=True)
    (core / "a.py").write_text("import examples.tidmad\n")
    (core / "b.py").write_text("from tools.example_packs import projection\n")
    (core / "c.py").write_text("from tools import example_packs\n")
    (core / "d.py").write_text(
        '"""mentions examples and tools.example_packs in prose"""\nimport os\n'
    )
    offenders = _production_importers(tmp_path)
    assert set(offenders) == {"src/core/a.py", "src/core/b.py", "src/core/c.py"}


# ---------------------------------------------------------------------------
# (d) PERMANENT — README / PROVENANCE / STATUS present; STATUS names a maturity level
# ---------------------------------------------------------------------------


def test_every_pack_has_the_three_docs_and_status_names_a_maturity_level() -> None:
    """[PERMANENT — roadmap §22.23.3 categories, §22.23.4 honest maturity]

    Defect caught: a pack lacks README / PROVENANCE / STATUS, or its STATUS
    stops naming a maturity level `L0`-`L4`."""
    packs = _pack_dirs(EXAMPLES_ROOT)
    assert packs, "no example packs found"
    for pack in packs:
        for doc in REQUIRED_PACK_DOCS:
            assert (pack / doc).is_file(), f"{pack.name} lacks {doc}"
        status = (pack / "STATUS.md").read_text(encoding="utf-8")
        assert MATURITY_LEVEL.search(status), f"{pack.name}/STATUS.md names no L0-L4 level"


# ---------------------------------------------------------------------------
# (e) PERMANENT — README cites the owning roadmap section / paths
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (f) PERMANENT — the two framework-owned minimal roots exist
# ---------------------------------------------------------------------------


def test_framework_minimal_roots_exist_and_are_tracked() -> None:
    """The framework keeps one quickstart and one synthetic contrast pack."""
    for root in ("quickstart", "synthetic_masked_regression"):
        assert (EXAMPLES_ROOT / root).is_dir()
        tracked = _tracked(REPO_ROOT, f"examples/{root}")
        assert tracked, f"examples/{root} has no tracked files (ignored or never committed?)"
        assert f"examples/{root}/README.md" in tracked


# ---------------------------------------------------------------------------
# (g) PERMANENT — every resolved/ snapshot directory carries the read-only banner
# ---------------------------------------------------------------------------
