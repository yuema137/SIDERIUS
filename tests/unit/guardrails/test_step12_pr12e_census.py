"""Step 12 / PR-12e — the zero-infrastructure-edit census, and its own plants.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12e_out_of_tree_graduation.md`` §I (all four sub-sections), §J (N9/N11),
§G.3 (this module is workstream B's owned shared artifact).

------------------------------------------------------------------------
WHAT THIS MODULE IS
------------------------------------------------------------------------

12e's central claim is not "a fourth task runs". It is **"a fourth task runs
and SIDERIUS was not edited to let it"**. Those are different claims, and only
the second one decays silently: a framework can absorb a task by growing a
table entry, an import, an enum member or an ``if``, and every test stays
green while the extension mechanism quietly becomes *"edit the framework"*.

So the census has **two halves, and the second is the one a byte census would
miss**:

``I.2`` **the measurement half** — a *run-scoped* tree census. Baseline SHA
with ``git status --porcelain`` empty, a sha256 manifest over the nine
production dirs, the run, then the same two facts again. Generated files are
excluded *by construction* (a run writes to the workspace, not the repo), so
there is no exclusion list to argue over. **If the run creates a repo file the
census fails — that is the point.**

``I.3`` **the semantic half** — byte equality proves nothing about *hidden
accommodation* that landed in an earlier commit. Seven separate nets, each
with its own plant.

------------------------------------------------------------------------
THE FOUR RECORDED CENSUS-BLINDNESS SHAPES, AND THIS MODULE'S IMMUNITY
------------------------------------------------------------------------

This project has shipped a census that was green for the wrong reason four
times. Every guard below names which shape it is immune to and why.

``F-12bc-6`` *the detector named a SYMBOL and stayed green through the very
landing it existed to announce.*
  **Immunity**: the needles are not a literal list in this file. They are
  EXTRACTED FROM THE PACKAGE at census time
  (:func:`resolve_package_identifiers`), from the structural positions the
  frozen §D.2 package contract defines. Rename the task and the census
  follows; it cannot go stale relative to the artifact it censuses.

``F-12bc-9`` *the census's FILE SET omitted the directory where the code
lived.*
  **Immunity**: the dir list is IMPORTED from the one canonical definition
  (``test_step10_p1_c4_extension_proof.PRODUCTION_DIRS``) rather than forked,
  and :func:`test_the_file_set_is_a_superset_of_what_git_tracks` cross-checks
  the walk against ``git ls-files`` — an independent tool, so a directory this
  module forgot to walk is reported by one that did not.

``F-P2b-4`` *an ANCHORED symbol regex was blind to a leading underscore.*
  **Immunity**: matching is normalized per WORD — lowercase, separators
  stripped — so ``_eventseq``, ``EventSeq``, ``event-seq`` and
  ``event.seq`` all match one needle. Proven by
  :func:`test_the_matcher_sees_every_spelling_of_one_identifier`.

``F-12e-UX-8`` *the file set was ``rglob("*.py")`` while the code lived in
``app.js``.*
  **Immunity**: there is **no suffix filter at all**. The walk returns every
  file under the nine dirs; the text census decodes whatever decodes. That is
  not a stylistic choice — ``sdsc_submission_scripts`` holds 9 ``.sh`` and 3
  ``.slurm`` files against 3 ``.py`` files, and ``dashboard`` holds the
  ``.js`` that F-12e-UX-8 was actually about. A ``*.py`` census is blind to
  the majority of one production dir.

A fifth, unnumbered shape is worth naming because this module is structurally
immune to it and most Python censuses are not: **a census that IMPORTS the
thing it censuses can be fooled by a stale ``.pyc``**. Nothing here imports a
production module to inspect it — every guard reads SOURCE BYTES off disk and
parses them. There is no bytecode cache in the loop to clear.

------------------------------------------------------------------------
PUBLIC API — owned by workstream B, consumed READ-ONLY by workstream C (§G.3)
------------------------------------------------------------------------

Identifier binding
    ``PACKAGE_ROOT_ENV``, :class:`PackageIdentifiers`,
    :class:`PackageNotAvailable`, :func:`package_root_from_env`,
    :func:`resolve_package_identifiers`, :func:`require_package_identifiers`

File set
    ``PRODUCTION_DIRS`` (re-exported, never forked),
    :func:`production_files`, :func:`decodable_text_files`

Measurement half (§I.2)
    :func:`tree_manifest`, :func:`manifest_delta`,
    :func:`git_status_porcelain`, :func:`working_tree_is_clean`,
    :func:`zero_infrastructure_edit`

Semantic half (§I.3)
    :func:`find_identifier_mentions`, :func:`find_identity_dispatch`,
    :func:`find_task_catalog`, :func:`find_package_imports`,
    :func:`find_silent_task_fallback`, :func:`find_declared_identifier_growth`,
    :func:`find_copied_values`

Neither workstream implements a private copy of the other's helper. A
duplicated helper is a merge-cost defect, not parallelism (§G.3).
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

# The canonical nine-dir definition. IMPORTED, never forked: F-12bc-9 is
# exactly what a second copy of this list produces once the two drift.
from tests.unit.workflows.test_step10_p1_c4_extension_proof import (
    PRODUCTION_DIRS,
    TASK_NAMES,
    find_task_identity_dispatch,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Where the out-of-tree package lives. The package is built by workstream A
#: at an arbitrary checkout path and is deliberately NOT in this repository
#: (§I.1: an in-repo package would make the census self-satisfying), so the
#: only honest binding is an environment variable the Gate sets.
PACKAGE_ROOT_ENV = "SIDERIUS_12E_PACKAGE_ROOT"


def _contract_metadata_symbols(root: Path, raw: dict) -> frozenset[str]:
    """Manifest ``symbol:`` names that are CONTRACT METADATA, not task identity.

    A manifest points at an implementation and at the symbol that
    implementation declares ITSELF with. Two different things wear that field:

    * ``symbol: SequenceNllLossMetric`` — a class the PACKAGE authored. The
      name IS task-specific identity, and a framework that learned it would be
      accommodating the task. **A needle.**
    * ``symbol: PLUGIN_LOSS_TYPE`` — the framework's public contract constant,
      spelled identically by every pack including the shipped ones. The task
      identity is that constant's VALUE (``eventseq_sequence_nll``), which the
      AST pass below already collects. **Not a needle** — hunting for the NAME
      fires on ``workflows/task_composition.py`` and every plugin loader.

    **KNOWN AND BOUNDED OVER-BREADTH — source-grounded, not assumed.**
    ``_compose_objective`` requires only that the symbol resolve to a
    *non-empty string*; it does **not** constrain the symbol NAME, and the
    landed docstring says "e.g. ``PLUGIN_LOSS_TYPE``" — an example, not a
    requirement. So the public mechanism does **NOT** guarantee that a
    string-resolving ``symbol:`` is a generic contract export: a package may
    legally declare ``symbol: EVENTSEQ_LOSS_NAME``, and this rule would then
    drop a package-authored NAME from the needle set.

    **Why that residual is tolerable, and exactly how far it extends**: the
    identity VALUE is collected independently by the AST pass, so **every
    production accommodation that uses the task's identity string is still
    caught** — which is the accommodation shape that matters. What would be
    missed is production referencing the package's *constant name* itself.
    ``test_a_package_authored_constant_name_does_not_hide_the_identity``
    pins that boundary in both directions so it cannot widen silently.

    Deliberately NOT fixed by intersecting with "names that appear in
    production": that is circular — the planted accommodation would make its
    own name look framework-known and exclude itself.

    **The discriminator is STRUCTURAL, not a hand-maintained allowlist**: ask
    the package's own source what the symbol IS. A module-level assignment to
    a string constant is contract metadata carrying a value; a ``class`` or
    ``def`` is an identifier the package authored. Nesting cannot decide it —
    ``metric.implementation.symbol`` and ``objective.implementation.symbol``
    sit at the same depth and fall on opposite sides.

    Consequence worth stating: a NEW framework contract symbol needs no edit
    here. It is classified by what it is, so this cannot rot into a list that
    someone must remember to extend.

    Defect this exists to catch, and how it fails: if the extraction treated
    every ``symbol:`` as identity, the census would report ~15 findings in
    untouched framework files and a real planted task identifier would be lost
    in the noise. Found when the package's ``objective:`` section landed —
    before it, the manifest happened to name only package-authored classes, so
    the extraction was green FOR THE WRONG REASON.
    """
    declared: set[str] = set()
    for path in {
        *(root / r for r in _scalar_strings(raw, ("file",))),
        *_package_plugin_files(root, raw),
    }:
        if not path.is_file() or path.suffix != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):  # pragma: no cover - a broken plugin
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                if not isinstance(node.value.value, str):
                    continue
                declared.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return frozenset(declared)


#: Directory entries never carrying source. ``__pycache__`` is excluded
#: because it is DERIVED — hashing it would make the manifest depend on which
#: interpreter last ran, not on what the repository contains.
_SKIP_DIR_PARTS = frozenset({"__pycache__", ".git", ".pytest_cache", ".ruff_cache"})

#: Symbols that name TIDMAD's compatibility defaults. A reference to one of
#: these *in a fallback position* is the C-P56-1 shape: a family that failed
#: to resolve silently becoming TIDMAD's.
#:
#: ``TidmadSandbox`` is deliberately NOT here. It is the generic subprocess
#: EXECUTOR whose name is historical — it carries no metric, no profile and no
#: data path, so ``sandbox_factory or TidmadSandbox`` is dependency-injection
#: defaulting, not a task semantic resolving itself. Including it would make
#: this census report a constructor default, and a census that reports
#: correct code is one that gets switched off.
_TIDMAD_DEFAULT_SYMBOLS = frozenset(
    {
        "TIDMAD",
        "TIDMAD_PROFILE",
        "TIDMAD_COMPATIBILITY_ID",
        "TIDMAD_METRIC_ID",
        "derive_tidmad_metric",
        "derive_tidmad_metric_spec",
    }
)

#: No production failure path may choose scientific task semantics. The empty
#: mapping is intentional and exact: a newly introduced fallback is red.
_ALLOWED_LEGACY_DEFAULTS: dict[str, int] = {}


# ======================================================================
# Identifier binding — the needles come FROM the package (F-12bc-6)
# ======================================================================


class PackageNotAvailable(RuntimeError):
    """The out-of-tree package could not be resolved.

    Deliberately an ERROR and not a skip at this layer. A misconfigured Gate
    — ``SIDERIUS_12E_PACKAGE_ROOT`` pointing at a typo — must fail loudly;
    only the *absence* of the variable is a legitimate "not bound yet", and
    that decision belongs to :func:`require_package_identifiers`, at the test
    boundary where a skip can carry a reason.
    """


@dataclass(frozen=True, slots=True)
class PackageIdentifiers:
    """Everything about the fourth task that must be absent from production.

    Extracted from the STRUCTURAL POSITIONS the frozen §D.2 package contract
    defines, never from a literal list in this file — see F-12bc-6 above.
    """

    package_root: Path
    package_name: str
    task_data_path_id: str
    metric_ids: tuple[str, ...]
    plugin_symbols: tuple[str, ...]
    plugin_module_stems: tuple[str, ...]
    declared_extra: tuple[str, ...]
    distinctive_values: tuple[float, ...]

    def needles(self) -> tuple[str, ...]:
        """The identifier set the absence censuses hunt for.

        Filtered to length >= 4 after normalization: a three-character token
        is not evidence of accommodation, it is a coincidence generator.
        """
        raw = (
            self.package_name,
            self.task_data_path_id,
            *self.metric_ids,
            *self.plugin_symbols,
            *self.plugin_module_stems,
            *self.declared_extra,
        )
        seen: dict[str, str] = {}
        for value in raw:
            key = _normalize(value)
            if len(key) >= 4:
                seen.setdefault(key, value)
        return tuple(sorted(seen.values()))


def _normalize(value: str) -> str:
    """One spelling for every spelling. The F-P2b-4 immunity, in one line."""
    return re.sub(r"[^0-9a-z]+", "", str(value).lower())


def package_root_from_env() -> Path | None:
    raw = os.environ.get(PACKAGE_ROOT_ENV, "").strip()
    return Path(raw) if raw else None


def _scalar_strings(node: Any, keys: Iterable[str]) -> list[str]:
    """String values living under any of ``keys``, at any depth."""
    wanted = frozenset(keys)
    found: list[str] = []
    stack: list[Any] = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                if key in wanted and isinstance(value, str) and value.strip():
                    found.append(value)
                stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
    return found


def _numeric_scalars(node: Any) -> list[float]:
    found: list[float] = []
    stack: list[Any] = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, bool):
            continue
        elif isinstance(item, (int, float)):
            found.append(float(item))
    return found


def _is_distinctive(value: float) -> bool:
    """Whether a package constant is distinctive enough to census for.

    The net this feeds (§I.3 bullet 5, "no constant from the package copied
    into production") is only meaningful for values that would not occur in
    generic code by accident. ``32``, ``256`` and ``0.5`` occur everywhere;
    ``7919`` and ``0.0137`` do not.

    Stated as an explicit, documented filter because the alternative — census
    every declared number — reports a finding on every batch size in the
    repository and gets switched off within a week, which is how the launcher
    guard nearly died.

    **Honest false negative**: a package whose only constants are small round
    numbers gets no coverage from this net. That is detected, not hidden —
    :func:`test_the_copied_value_net_refuses_to_be_vacuous` skips with a named
    reason rather than passing.
    """
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        return False
    if float(value).is_integer():
        return abs(value) >= 1000
    return len(f"{value!r}".partition(".")[2].rstrip("0")) >= 3


def _package_plugin_files(root: Path, raw: dict[str, Any]) -> list[Path]:
    """Every ``.py`` file under a directory the manifest names with ``dir:``."""
    found: list[Path] = []
    for dir_ref in _scalar_strings(raw, ("dir",)):
        plugin_dir = root / dir_ref if not os.path.isabs(dir_ref) else Path(dir_ref)
        if plugin_dir.is_dir():
            found.extend(p for p in sorted(plugin_dir.glob("*.py")) if p.stem != "__init__")
    return found


def resolve_package_identifiers(root: Path) -> PackageIdentifiers:
    """Read the package's own declarations and derive the census needles.

    Raises:
        PackageNotAvailable: the path is not a package meeting the frozen
            §D.2 contract. Loud, so a typo in the Gate's environment cannot
            present as "nothing to census".
    """
    root = Path(root)
    manifest = root / "composition.yaml"
    if not manifest.is_file():
        raise PackageNotAvailable(
            f"{PACKAGE_ROOT_ENV}={root!s} does not hold a task package: no "
            f"composition.yaml. The §D.2 package contract names it as the "
            f"operator entrypoint, and the census derives every needle from "
            f"it — an unreadable package would census for nothing and pass."
        )
    try:
        raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:  # pragma: no cover - IO shape
        raise PackageNotAvailable(f"{manifest} is unreadable: {exc}") from exc
    if not isinstance(raw, dict):
        raise PackageNotAvailable(f"{manifest} is not a YAML mapping.")

    section = raw.get("task_data_path")
    task_id = section.get("id") if isinstance(section, dict) else None
    if not isinstance(task_id, str) or not task_id.strip():
        raise PackageNotAvailable(
            f"{manifest} declares no `task_data_path.id`. That id is the "
            f"fourth task's name at the registry boundary; without it the "
            f"identifier census has no primary needle."
        )

    # A manifest `symbol:` names the FRAMEWORK's public plugin-contract symbol
    # that an implementation declares ITSELF with -- `PLUGIN_LOSS_TYPE`,
    # `PLUGIN_MODEL_TYPE`, ... The task identity is that symbol's VALUE
    # (`eventseq_sequence_nll`), which this extraction already collects
    # separately as a module-level identity constant. The NAME is shared by
    # every pack, including the shipped ones, so treating it as a needle makes
    # the census fire on `workflows/task_composition.py` and every plugin
    # loader -- 15 findings, none of them the fourth task.
    #
    # Found by adding the package's `objective:` declaration (whose landed
    # shape is `symbol: PLUGIN_LOSS_TYPE`, identical to DAVIS's). Before that
    # declaration existed the manifest happened to carry only task-specific
    # symbol names, so the extraction was green FOR THE WRONG REASON: it had
    # never met a manifest that names a framework contract symbol.
    symbols = tuple(
        s
        for s in dict.fromkeys(_scalar_strings(raw, ("symbol",)))
        if s not in _contract_metadata_symbols(root, raw)
    )
    file_refs = tuple(dict.fromkeys(_scalar_strings(raw, ("file",))))
    stem_list = [Path(ref).stem for ref in file_refs]

    # A `dir:` section (model_plugins, loss_plugins) names a DIRECTORY the
    # framework scans, so its plugin files are never listed as `file:` refs
    # and a `file:`-only extraction misses every one of them. The real
    # package's model, objective and corpus modules all arrive this way —
    # three plugin identities the census would have hunted for nothing.
    #
    # This is F-12bc-9 in the needle set rather than in the file set: an
    # extraction whose SOURCE SET omits where the identities live.
    stem_list.extend(p.stem for p in _package_plugin_files(root, raw))
    stems = tuple(dict.fromkeys(stem_list))

    metric_ids: list[str] = []
    declared_extra: list[str] = []
    values: list[float] = []

    # `require:` names the plugin IDENTITIES a declaration insists on — the
    # model type the plugin registry keys on, the loss name a LossConfig
    # selects. Those are precisely the names a framework would have to learn
    # in order to accommodate the task, so they are needles of the first
    # rank; the manifest's own `require` list is where they are stated.
    for section in raw.values():
        if isinstance(section, dict):
            required = section.get("require")
            if isinstance(required, list):
                declared_extra.extend(str(r) for r in required if isinstance(r, str))
    for decl_ref in _scalar_strings(raw, ("declaration", "config")):
        path = root / decl_ref if not os.path.isabs(decl_ref) else Path(decl_ref)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            payload = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
        except (OSError, ValueError, yaml.YAMLError):  # pragma: no cover
            continue
        metric_ids.extend(_scalar_strings(payload, ("id", "metric_id")))
        declared_extra.extend(_scalar_strings(payload, ("task_id", "task_name", "name")))
        values.extend(_numeric_scalars(payload))

    # Module-level identity CONSTANTS inside the package's own plugin files.
    #
    # `PLUGIN_MODEL_TYPE = "eventseq_embedding_gru"` is the name the model
    # registry keys on, and a loss plugin's name constant is what a
    # `LossConfig(loss_type="custom", loss_name=...)` selects. Neither appears
    # in the manifest unless a `require:` list happens to name it, yet both
    # are names the framework would have to learn to accommodate the task —
    # so they are first-rank needles.
    #
    # Read from SOURCE BYTES via `ast`, never by importing the plugin: the
    # module's stated immunity to a stale `.pyc` has to hold for the needle
    # extractor too, or the census would be exactly as blind as the thing it
    # is protecting against.
    # A COMPOUND token — one carrying a separator, or long enough that no
    # English word is plausible. This source is the only low-confidence one in
    # the extraction (the others come from `id:` / `symbol:` / `file:`, which
    # are identities by position), and without the rule it scavenged
    # `"classifier"`, `"generated"`, `"long"` and `"mean"` from ordinary
    # module constants — needles that would report a finding on half of
    # production and get the whole census switched off.
    #
    # The trade is deliberate and one-directional: a package whose model type
    # is a bare word (`"mymodel"`) is MISSED here, and covers itself through
    # `declared/census_identifiers.json`. A miss is caught by the manifest
    # equality half; noise is caught by nothing, because people stop reading.
    identity_like = re.compile(r"^(?=.*[_.\-])[A-Za-z_][A-Za-z0-9_.\-]{3,}$|^[A-Za-z_]\w{11,}$")
    for stem_path in {*(root / r for r in file_refs), *_package_plugin_files(root, raw)}:
        if not stem_path.is_file() or stem_path.suffix != ".py":
            continue
        try:
            tree = ast.parse(stem_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):  # pragma: no cover - a broken plugin
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
                continue
            if not isinstance(node.value.value, str):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name) and t.id.isupper()]
            if names and identity_like.match(node.value.value):
                declared_extra.append(node.value.value)

    # An OPTIONAL escape hatch the package may use to declare extra needles
    # it knows the framework must never learn. Additive: absent means the
    # structural extraction above is the whole needle set.
    extra_file = root / "declared" / "census_identifiers.json"
    if extra_file.is_file():
        try:
            extra = json.loads(extra_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # pragma: no cover
            extra = None
        if isinstance(extra, list):
            declared_extra.extend(str(item) for item in extra if isinstance(item, str))

    return PackageIdentifiers(
        package_root=root,
        package_name=root.name,
        task_data_path_id=task_id,
        metric_ids=tuple(dict.fromkeys(metric_ids)),
        plugin_symbols=symbols,
        plugin_module_stems=stems,
        declared_extra=tuple(dict.fromkeys(declared_extra)),
        distinctive_values=tuple(sorted({v for v in values if _is_distinctive(v)})),
    )


def require_package_identifiers() -> PackageIdentifiers:
    """The test-boundary binding: skip when unbound, RAISE when misbound."""
    root = package_root_from_env()
    if root is None:
        pytest.skip(
            f"{PACKAGE_ROOT_ENV} is not set — the out-of-tree package is "
            f"workstream A's deliverable and binds at the integration "
            f"checkpoint. The census MECHANISM is proven green here against "
            f"synthetic plants; only the real-artifact rows wait."
        )
    return resolve_package_identifiers(root)


# ======================================================================
# The file set — no suffix filter, and the dir list is imported (I.1)
# ======================================================================


def production_files(root: Path, dirs: Iterable[str] = PRODUCTION_DIRS) -> list[Path]:
    """EVERY file under the nine production dirs. No suffix filter.

    F-12e-UX-8 immunity by construction: there is nothing to forget to add.
    """
    found: list[Path] = []
    for rel in dirs:
        base = Path(root) / rel
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_PARTS]
            for name in filenames:
                if name.endswith(".pyc"):
                    continue
                found.append(Path(dirpath) / name)
    return sorted(found)


def decodable_text_files(root: Path, dirs: Iterable[str] = PRODUCTION_DIRS):
    """``(path, text)`` for every production file that decodes as UTF-8."""
    for path in production_files(root, dirs):
        try:
            yield path, path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue


def _python_files(root: Path, dirs: Iterable[str] = PRODUCTION_DIRS) -> list[Path]:
    return [p for p in production_files(root, dirs) if p.suffix == ".py"]


# ======================================================================
# §I.2 — the measurement half
# ======================================================================


def tree_manifest(root: Path, dirs: Iterable[str] = PRODUCTION_DIRS) -> dict[str, str]:
    """``{repo-relative path: sha256}`` over the nine production dirs."""
    root = Path(root)
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in production_files(root, dirs)
    }


def manifest_delta(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    """What moved between two manifests, partitioned by HOW it moved."""
    return {
        "added": sorted(set(after) - set(before)),
        "removed": sorted(set(before) - set(after)),
        "modified": sorted(k for k in set(before) & set(after) if before[k] != after[k]),
    }


def git_status_porcelain(root: Path) -> str:
    """``git status --porcelain`` in ``root``, verbatim."""
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def working_tree_is_clean(root: Path) -> bool:
    return git_status_porcelain(root).strip() == ""


@contextmanager
def zero_infrastructure_edit(root: Path = REPO_ROOT) -> Iterator[dict[str, str]]:
    """The §I.2 run-scoped census, as the Gate will execute it.

    ``with zero_infrastructure_edit(): <the run>`` asserts, on exit, that the
    working tree is still clean AND that the sha256 manifest is unchanged.

    **This is a run-scoped guard, not a repository lint.** The claim is about
    what a RUN does, and a run that writes into the repository is exactly the
    accommodation §I.2 exists to catch. Generated files need no exclusion
    list: the run writes to the workspace.
    """
    root = Path(root)
    assert working_tree_is_clean(root), (
        "the §I.2 census must start from a clean tree, or 'unchanged after "
        "the run' is unmeasurable:\n" + git_status_porcelain(root)
    )
    before = tree_manifest(root)
    yield before
    delta = manifest_delta(before, tree_manifest(root))
    assert delta == {"added": [], "removed": [], "modified": []}, (
        f"the run edited SIDERIUS production source: {delta}. The graduation "
        f"claim is that a fourth task costs ZERO infrastructure edits; a run "
        f"that writes into the repository has falsified it."
    )
    assert working_tree_is_clean(root), (
        "the working tree is dirty after the run:\n" + git_status_porcelain(root)
    )


# ======================================================================
# §I.3 — the semantic half
# ======================================================================


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    lineno: int
    kind: str
    detail: str


_WORD = re.compile(r"[A-Za-z0-9_.\-]+")


def _line_matches(line: str, normalized_needles: dict[str, str]) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for word in _WORD.findall(line):
        normal = _normalize(word)
        for needle_key, needle in normalized_needles.items():
            if needle_key in normal:
                hits.append(("word", needle))
    prose = re.sub(r"[^a-z0-9]+", " ", line.lower())
    for needle_key, needle in normalized_needles.items():
        spaced = " ".join(re.findall(r"[a-z]+|[0-9]+", needle_key))
        if len(spaced) > len(needle_key) and f" {spaced} " in f" {prose} ":
            hits.append(("prose", needle))
    return hits


def find_identifier_mentions(
    files: Iterable[tuple[Path, str]], needles: Iterable[str], root: Path
) -> list[Finding]:
    """Every mention of a package identifier, in any spelling.

    Matching is per-WORD and normalized, so ``_eventseq``, ``EventSeq``,
    ``event-seq`` and ``event.seq`` are one needle (F-P2b-4), and two
    unrelated identifiers on one line cannot fuse into a false match.
    """
    keys = {_normalize(n): n for n in needles if _normalize(n)}
    findings: list[Finding] = []
    for path, text in files:
        rel = str(Path(path).relative_to(root))
        for lineno, line in enumerate(text.splitlines(), start=1):
            for kind, needle in _line_matches(line, keys):
                findings.append(Finding(rel, lineno, f"{kind} mention", needle))
    return findings


def _matches(value: object, keys: Iterable[str]) -> str | None:
    """SUBSTRING match on the normalized form. Used where the needle is
    expected to be EMBEDDED — a module path, an import alias, a field name."""
    if not isinstance(value, str):
        return None
    normal = _normalize(value)
    return next((k for k in keys if k and k in normal), None)


def _matches_exact(value: object, keys: Iterable[str]) -> str | None:
    """EQUALITY on the normalized form. Used where the value IS the identity.

    The dispatch and catalog censuses ask "is this string a task id?", and a
    substring test answers a different question: ``_config["tidmad_data_dir"]``
    is a config key that happens to contain a task word, and reporting it
    would train the next reader to ignore the census. Spelling immunity is
    preserved — ``"TIDMAD"``, ``"tidmad"`` and ``"tid-mad"`` are one key —
    only the embedding is dropped. A needle embedded in a LARGER identifier
    is a schema-growth or import defect, and has its own net.
    """
    if not isinstance(value, str):
        return None
    normal = _normalize(value)
    return next((k for k in keys if k and k == normal), None)


def find_identity_dispatch(tree: ast.AST, names: Iterable[str]) -> list[tuple[int, str]]:
    """Every AST shape in which a TASK IDENTITY selects behaviour.

    The strict generalization of P1's ``find_task_identity_dispatch`` — same
    five shapes, an arbitrary name set instead of a hardcoded one. It is a
    generalization and not a divergent second copy, which
    :func:`test_the_generalized_detector_reproduces_the_p1_detector_exactly`
    proves by differential over the whole production tree.
    """
    keys = [_normalize(n) for n in names]
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for operand in [node.left, *node.comparators]:
                if isinstance(operand, ast.Constant) and _matches_exact(operand.value, keys):
                    hits.append((node.lineno, "comparison against a task name"))
                elif isinstance(operand, ast.Tuple | ast.List | ast.Set) and any(
                    isinstance(e, ast.Constant) and _matches_exact(e.value, keys)
                    for e in operand.elts
                ):
                    hits.append((node.lineno, "membership test over task names"))
        elif isinstance(node, ast.Dict) and any(
            isinstance(k, ast.Constant) and _matches_exact(k.value, keys) for k in node.keys if k
        ):
            hits.append((node.lineno, "mapping keyed on a task name"))
        elif isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Constant) and _matches_exact(node.slice.value, keys):
                hits.append((node.lineno, "subscript by a task name"))
        elif isinstance(node, ast.MatchValue):
            if isinstance(node.value, ast.Constant) and _matches_exact(node.value.value, keys):
                hits.append((node.lineno, "match-case on a task name"))
    return hits


def find_task_catalog(tree: ast.AST, names: Iterable[str]) -> list[tuple[int, str]]:
    """A container literal naming TWO OR MORE task identities.

    A catalog is a different defect from a dispatch: an id -> behaviour
    mapping table needs no ``if`` anywhere, so the dispatch census walks
    straight past it. Two distinct ids in one literal is what makes it a
    catalog rather than an implementation naming itself.
    """
    keys = [_normalize(n) for n in names]
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        matched: set[str] = set()
        if isinstance(node, ast.Dict):
            for key in node.keys:
                hit = _matches_exact(key.value, keys) if isinstance(key, ast.Constant) else None
                if hit:
                    matched.add(hit)
        elif isinstance(node, ast.Tuple | ast.List | ast.Set):
            for element in node.elts:
                hit = (
                    _matches_exact(element.value, keys)
                    if isinstance(element, ast.Constant)
                    else None
                )
                if hit:
                    matched.add(hit)
        if len(matched) >= 2:
            hits.append((node.lineno, f"task catalog over {sorted(matched)}"))
    return hits


def find_package_imports(tree: ast.AST, needles: Iterable[str]) -> list[tuple[int, str]]:
    """Any way a production module could reach INTO the external package."""
    keys = [_normalize(n) for n in needles]
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _matches(alias.name, keys):
                    hits.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            if _matches(node.module or "", keys):
                hits.append((node.lineno, f"from {node.module} import ..."))
            for alias in node.names:
                if _matches(alias.name, keys):
                    hits.append((node.lineno, f"from ... import {alias.name}"))
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in {
                "import_module",
                "__import__",
                "spec_from_file_location",
                "insert",
                "append",
                "load_module",
            }:
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and _matches(arg.value, keys):
                        hits.append((node.lineno, f"{name}({arg.value!r})"))
    return hits


def find_silent_task_fallback(tree: ast.AST) -> list[tuple[int, str]]:
    """A TIDMAD default reached from a FAILURE position — the C-P56-1 shape.

    Narrow on purpose. ``resolve_task_data_path``'s regime-A row legitimately
    names ``TIDMAD_COMPATIBILITY_ID`` inside ``if context is None:`` — that is
    a DECLARED absence resolving a declared compatibility path, which the
    frozen truth table requires. What must never exist is the same symbol
    reached because something FAILED:

    * inside an ``except`` handler,
    * as the right operand of ``or`` / the ``orelse`` of a conditional,
      **in a VALUE position** (an assignment, a return, an argument),
    * as the default argument of ``.get(...)`` / ``.pop(...)`` /
      ``getattr(...)``.

    Those three are "the family did not resolve, so use TIDMAD's", which is
    the silent-TIDMAD outcome the whole composition edge exists to prevent.

    **The value-position restriction is load-bearing, not tidiness.**
    ``if files < 1 or files > TIDMAD.num_files:`` is an ``or`` whose right
    operand names a TIDMAD symbol, and it is a RANGE CHECK — the opposite of a
    fallback. Reporting it (which the first draft of this detector did, twice
    in one file) is how a census gets switched off.

    ``getattr``'s default is the THIRD argument while ``.get``'s is the
    second, which the first draft also got wrong — so ``getattr(m, 'x',
    TIDMAD_PROFILE)`` went undetected while the docstring claimed it was
    covered. Both are pinned by plants below.
    """
    hits: list[tuple[int, str]] = []

    def _names(node: ast.AST) -> set[str]:
        out: set[str] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in _TIDMAD_DEFAULT_SYMBOLS:
                out.add(sub.id)
            elif isinstance(sub, ast.Attribute) and sub.attr in _TIDMAD_DEFAULT_SYMBOLS:
                out.add(sub.attr)
        return out

    # Every expression that ends up as a VALUE somewhere.
    value_roots: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign | ast.Return):
            if node.value is not None:
                value_roots.append(node.value)
        elif isinstance(node, ast.Call):
            value_roots.extend(node.args)
            value_roots.extend(kw.value for kw in node.keywords)
        elif isinstance(node, ast.arguments):
            value_roots.extend(d for d in [*node.defaults, *node.kw_defaults] if d is not None)

    seen: set[int] = set()
    for root in value_roots:
        for node in ast.walk(root):
            if id(node) in seen:
                continue
            seen.add(id(node))
            if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
                for value in node.values[1:]:
                    found = _names(value)
                    if found:
                        hits.append((node.lineno, f"`or {sorted(found)}` fallback"))
            elif isinstance(node, ast.IfExp) and _names(node.orelse):
                hits.append((node.lineno, f"conditional fallback to {sorted(_names(node.orelse))}"))

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            found = set().union(*(_names(stmt) for stmt in node.body)) if node.body else set()
            if found:
                hits.append((node.lineno, f"TIDMAD default inside except: {sorted(found)}"))
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            # `.get(key, DEFAULT)` and `.pop(key, DEFAULT)` take the default
            # second; `getattr(obj, name, DEFAULT)` takes it third.
            index = 2 if name == "getattr" else 1
            if name in {"get", "getattr", "pop"} and len(node.args) > index:
                found = _names(node.args[index])
                if found:
                    hits.append((node.lineno, f"{name}(..., {sorted(found)}) default"))
    return sorted(set(hits))


def find_declared_identifier_growth(tree: ast.AST, needles: Iterable[str]) -> list[tuple[int, str]]:
    """A schema that grew to NAME the fourth task.

    Enum members, annotated record fields and class-level constants — by
    attribute NAME or by declared string VALUE, because
    ``FOURTH = "eventseq"`` and ``eventseq_scope: str`` are the same defect
    wearing different clothes.
    """
    keys = [_normalize(n) for n in needles]
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            targets: list[str] = []
            value: ast.expr | None = None
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                targets, value = [stmt.target.id], stmt.value
            elif isinstance(stmt, ast.Assign):
                targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
                value = stmt.value
            for target in targets:
                if _matches(target, keys):
                    hits.append((stmt.lineno, f"{node.name}.{target} names the task"))
            if isinstance(value, ast.Constant) and _matches(value.value, keys):
                hits.append(
                    (stmt.lineno, f"{node.name}.{targets or ['<expr>']} declares {value.value!r}")
                )
    return hits


def find_copied_values(
    files: Iterable[tuple[Path, str]], values: Iterable[float], root: Path
) -> list[Finding]:
    """A DISTINCTIVE package constant appearing as a literal in production."""
    tokens = {}
    for value in values:
        tokens[str(int(value)) if float(value).is_integer() else repr(float(value))] = value
    if not tokens:
        return []
    findings: list[Finding] = []
    for path, text in files:
        rel = str(Path(path).relative_to(root))
        for lineno, line in enumerate(text.splitlines(), start=1):
            for token in tokens:
                if re.search(rf"(?<![\w.]){re.escape(token)}(?![\w.])", line):
                    findings.append(Finding(rel, lineno, "copied constant", token))
    return findings


# ======================================================================
# A synthetic production mirror — where every plant lives
# ======================================================================
#
# Plants never touch the repository. Each census function takes an explicit
# ``root``, so an offender is planted into a nine-dir mirror under ``tmp_path``
# and the real tree is only ever READ. That is not merely tidy: a plant in the
# repository would have to be removed by `git checkout`, and a `git checkout`
# that silently restores a plant is one of the three recorded ways a mutation
# proof lies.


def _mirror(tmp_path: Path, contents: dict[str, str] | None = None) -> Path:
    """A minimal nine-dir production tree, one benign module per dir."""
    root = tmp_path / "mirror"
    for rel in PRODUCTION_DIRS:
        target = root / rel
        target.mkdir(parents=True, exist_ok=True)
        (target / "benign.py").write_text("VALUE = 1\n", encoding="utf-8")
    for rel, text in (contents or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


#: The needle set every plant below uses. Deliberately shaped like a real
#: package identifier and deliberately absent from this repository, so a plant
#: proves detection rather than rediscovering an existing mention.
PLANT_NEEDLE = "eventseq_probe_v0"
PLANT_NEEDLES = (PLANT_NEEDLE,)


def _one(findings: list, what: str) -> None:
    """Anti-vacuity: a plant must turn the census red EXACTLY once.

    A census that goes red for two reasons at once is not a census — it
    cannot tell you which plant it saw, so it cannot tell you which net is
    load-bearing.
    """
    assert len(findings) == 1, f"{what}: expected exactly 1 finding, got {findings}"


# ======================================================================
# The file set
# ======================================================================


class TestTheFileSetCannotBeBlind:
    """F-12bc-9 and F-12e-UX-8, made executable.

    **How these fail when the behaviour breaks**: narrow the walk to
    ``rglob("*.py")`` and the suffix test reports the ``.sh``/``.slurm``/``.js``
    files that vanished; drop a directory from the walk and the git
    cross-check reports every tracked file in it.
    """

    def test_the_dir_list_is_the_canonical_one_and_not_a_copy(self):
        """F-12bc-9's root cause is a SECOND copy of the file set drifting
        from the first. There is no second copy: this asserts the imported
        name is the same object the P1 module defines, so a future change
        there reaches here automatically."""
        from tests.unit.workflows import test_step10_p1_c4_extension_proof as p1

        assert PRODUCTION_DIRS is p1.PRODUCTION_DIRS
        assert len(PRODUCTION_DIRS) == 9

    def test_the_file_set_is_a_superset_of_what_git_tracks(self):
        """The independent oracle. ``git ls-files`` is a different tool with
        a different notion of the file set, so a directory this module forgot
        to walk — or a suffix it filtered out — is reported by something that
        did not share the bug."""
        tracked = subprocess.run(
            ["git", "ls-files", "-z", *PRODUCTION_DIRS],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        expected = {p for p in tracked.split("\0") if p}
        walked = {str(p.relative_to(REPO_ROOT)) for p in production_files(REPO_ROOT)}
        missing = sorted(expected - walked)
        assert missing == [], (
            f"the census walk misses {len(missing)} file(s) git tracks under the "
            f"nine production dirs: {missing[:20]}"
        )

    def test_it_covers_the_non_python_suffixes_that_actually_exist(self):
        """F-12e-UX-8 was a census over ``*.py`` while the defect lived in
        ``app.js``. Quantified here rather than asserted: a ``*.py`` census
        sees 3 of the 16 files in ``sdsc_submission_scripts``."""
        walked = production_files(REPO_ROOT)
        suffixes = {p.suffix for p in walked}
        for suffix in (".py", ".sh", ".slurm", ".js", ".md"):
            assert suffix in suffixes, f"no {suffix} file reached the census"
        sdsc = [p for p in walked if p.parts[-2:][0] or True]
        sdsc = [p for p in walked if "sdsc_submission_scripts" in p.parts]
        assert len([p for p in sdsc if p.suffix == ".py"]) < len(sdsc) / 2, (
            "a *.py-only census would see under half of sdsc_submission_scripts"
        )

    def test_derived_bytecode_is_excluded_but_nothing_else_is(self):
        """``__pycache__`` is the ONE exclusion, and it is excluded because it
        is derived — hashing it would make the manifest depend on which
        interpreter last ran. Everything else is in, including the ``.md``
        files a doc-only edit would touch."""
        walked = production_files(REPO_ROOT)
        assert not any("__pycache__" in p.parts for p in walked)
        assert not any(p.suffix == ".pyc" for p in walked)
        assert any(p.suffix == ".md" for p in walked)

    def test_this_module_is_not_inside_its_own_census_subject(self):
        """§G.2's write set, made executable.

        12e's whole claim is measured by a manifest over the nine dirs, so a
        census helper that ever landed in one of them would be measuring a
        tree 12e itself edited — the census would move on its own commits and
        the graduation claim would quietly become circular. The write set is
        ``tests/``, and ``tests/`` is not a production dir."""
        assert "tests" not in PRODUCTION_DIRS
        assert Path(__file__).resolve() not in set(production_files(REPO_ROOT))


# ======================================================================
# §I.2 — the measurement half
# ======================================================================


class TestTheMeasurementHalf:
    """The §I.2 procedure, proven on a real throwaway git repository.

    The Gate executes it around the real run; these prove the helper reports
    what it claims to. **How they fail**: make ``tree_manifest`` hash paths
    instead of bytes and the modification case goes green; make
    ``zero_infrastructure_edit`` swallow the delta and the created-file case
    goes green.
    """

    def test_a_modified_byte_is_reported_as_modified(self, tmp_path):
        root = _mirror(tmp_path)
        before = tree_manifest(root)
        (root / "src/core" / "benign.py").write_text("VALUE = 2\n", encoding="utf-8")
        assert manifest_delta(before, tree_manifest(root))["modified"] == ["src/core/benign.py"]

    def test_a_file_the_run_created_is_reported_as_added(self, tmp_path):
        """§I.2's whole point: *if the run creates a repo file, the census
        fails*. No exclusion list — the run writes to the workspace."""
        root = _mirror(tmp_path)
        before = tree_manifest(root)
        (root / "src/workflows" / "generated_by_the_run.json").write_text("{}", encoding="utf-8")
        assert manifest_delta(before, tree_manifest(root))["added"] == [
            "src/workflows/generated_by_the_run.json"
        ]

    def test_a_deleted_file_is_reported_as_removed(self, tmp_path):
        root = _mirror(tmp_path)
        before = tree_manifest(root)
        (root / "src/agent" / "benign.py").unlink()
        assert manifest_delta(before, tree_manifest(root))["removed"] == ["src/agent/benign.py"]

    def test_the_manifest_covers_non_python_production_files(self, tmp_path):
        """The measurement half inherits the file set's immunity: a shell
        script edited by the run must be reported, and a ``*.py`` manifest
        would not see it."""
        root = _mirror(tmp_path, {"sdsc_submission_scripts/run_x.sh": "echo a\n"})
        before = tree_manifest(root)
        (root / "sdsc_submission_scripts" / "run_x.sh").write_text("echo b\n", encoding="utf-8")
        assert manifest_delta(before, tree_manifest(root))["modified"] == [
            "sdsc_submission_scripts/run_x.sh"
        ]

    def test_the_clean_tree_check_actually_asks_git(self, tmp_path):
        """Reachability, on a real repository rather than a mock: an
        untracked file makes it dirty, committing makes it clean. A helper
        that returned ``True`` unconditionally would pass the Gate's census
        while the tree was full of edits."""
        root = tmp_path / "repo"
        (root / "src/core").mkdir(parents=True)
        (root / "src/core" / "m.py").write_text("x = 1\n", encoding="utf-8")
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "base"]):
            subprocess.run(["git", *args], cwd=str(root), check=True, env=env, capture_output=True)
        assert working_tree_is_clean(root)
        (root / "src/core" / "leaked.py").write_text("y = 2\n", encoding="utf-8")
        assert not working_tree_is_clean(root)
        assert "leaked.py" in git_status_porcelain(root)

    def test_the_run_scoped_census_fails_when_the_run_writes_into_the_repo(self, tmp_path):
        """The Gate-facing entry point, end to end. **This is the assertion
        the whole PR turns on**, so it is proven to fire rather than assumed
        to."""
        root = tmp_path / "repo"
        (root / "src/core").mkdir(parents=True)
        (root / "src/core" / "m.py").write_text("x = 1\n", encoding="utf-8")
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "base"]):
            subprocess.run(["git", *args], cwd=str(root), check=True, env=env, capture_output=True)

        with zero_infrastructure_edit(root):
            pass  # a well-behaved run touches nothing

        with pytest.raises(AssertionError, match="edited SIDERIUS production source"):
            with zero_infrastructure_edit(root):
                (root / "src/core" / "accommodation.py").write_text("z = 3\n", encoding="utf-8")


# ======================================================================
# §I.3 bullet 1 — identifier absence
# ======================================================================


class TestTheIdentifierMatcherCannotBeFooledBySpelling:
    """F-P2b-4: the recorded defect was an ANCHORED symbol regex blind to a
    leading underscore. **How this fails**: re-anchor the matcher and the
    underscore/camel/hyphen rows go green-to-red immediately."""

    @pytest.mark.parametrize(
        "line",
        [
            "from x import eventseq_probe_v0",
            "import _eventseq_probe_v0_helper",
            "value = EventSeqProbeV0()",
            "ref = 'event-seq-probe-v0'",
            "mod = 'pkg.eventseq.probe.v0'",
            "FOO = _EventseqProbeV0",
            "    # eventseq_probe_v0 lives out of tree",
        ],
    )
    def test_the_matcher_sees_every_spelling_of_one_identifier(self, line, tmp_path):
        root = _mirror(tmp_path, {"src/core/x.py": line + "\n"})
        findings = find_identifier_mentions(decodable_text_files(root), PLANT_NEEDLES, root)
        assert findings, f"{line!r} went undetected"

    def test_two_unrelated_identifiers_on_one_line_do_not_fuse(self, tmp_path):
        """The cost of normalizing is a fusion false positive. Matching is
        per-WORD precisely so that ``eventseq`` beside ``probe_v0`` is two
        identifiers, not one needle."""
        root = _mirror(tmp_path, {"src/core/x.py": "a = eventseq(); b = probe_v0\n"})
        assert find_identifier_mentions(decodable_text_files(root), PLANT_NEEDLES, root) == []

    def test_a_short_identifier_is_not_a_needle(self):
        """Length >= 4 after normalization. A package that called something
        ``ev`` would otherwise make the census report every ``.every()`` in
        the dashboard's JavaScript."""
        pkg = PackageIdentifiers(
            package_root=Path("/x"),
            package_name="ev",
            task_data_path_id="abc",
            metric_ids=("nll_loss",),
            plugin_symbols=(),
            plugin_module_stems=(),
            declared_extra=(),
            distinctive_values=(),
        )
        assert pkg.needles() == ("nll_loss",)


class TestNoProductionSourceMentionsTheFourthTask:
    """§I.3 bullet 1 — the standing guard, and the plants that make it mean
    something.

    Split into an EXECUTABLE-source test and a DOCUMENTATION test so a
    failure says which one it is: a ``.md`` that names the task is a
    different (much milder) finding from a ``.py`` that does, and one
    assertion covering both would report the milder one and hide the other.
    """

    def test_a_package_authored_constant_name_does_not_hide_the_identity(self):
        """The bounded edge-case proof for `_contract_metadata_symbols`.

        `_compose_objective` constrains the symbol's VALUE (a non-empty
        string) and NOT its NAME, so a package may legally declare
        `symbol: <PACKAGE_AUTHORED_CONSTANT>`. The exclusion rule would then
        drop that NAME from the needle set. This pins what that costs.

        Defect it catches, and how it fails: if someone later "simplifies"
        the AST identity pass so needles come only from manifest `symbol:`
        fields, a task whose objective is declared through a package-authored
        constant would become INVISIBLE to the census — production could
        accommodate it by name and stay green. Then the second assertion
        fails, because the identity value would no longer be a needle.
        """
        pkg = require_package_identifiers()
        needles = set(pkg.needles())
        root = package_root_from_env()
        assert root is not None  # require_package_identifiers already proved it

        # 1. The boundary as it actually is: a name assigned a module-level
        #    string constant is excluded, package-authored or not.
        excluded = _contract_metadata_symbols(
            root,
            yaml.safe_load((root / "composition.yaml").read_text(encoding="utf-8")),
        )
        assert "PLUGIN_LOSS_TYPE" in excluded, (
            "the framework contract symbol must be excluded, or the census "
            "fires on task_composition.py and every plugin loader"
        )

        # 2. The mitigation, and it is what makes (1) affordable: the task's
        #    IDENTITY VALUE is collected independently of any symbol name, so
        #    a production accommodation using the task's identity is still
        #    caught no matter how the package spells the constant holding it.
        assert pkg.task_data_path_id in needles, (
            f"the task id {pkg.task_data_path_id!r} must be a needle "
            f"independently of symbol-name extraction; without that, "
            f"excluding a symbol name would make a real accommodation "
            f"invisible"
        )
        objective_values = {
            n for n in needles if isinstance(n, str) and n.endswith("_sequence_nll")
        }
        assert objective_values, (
            "the objective's declared identity VALUE is not a needle. The "
            "symbol-name exclusion is only safe because the value is "
            "collected separately; with both gone, a framework that learned "
            "this task's objective name would pass the census."
        )

    def test_no_executable_production_source_mentions_it(self):
        pkg = require_package_identifiers()
        files = [
            (p, t)
            for p, t in decodable_text_files(REPO_ROOT)
            if p.suffix not in {".md", ".rst", ".txt"}
        ]
        findings = find_identifier_mentions(files, pkg.needles(), REPO_ROOT)
        assert findings == [], (
            f"SIDERIUS executable source learned the fourth task's identity: "
            f"{findings}. The extension mechanism would be 'edit the framework'."
        )

    def test_no_production_documentation_mentions_it(self):
        pkg = require_package_identifiers()
        files = [
            (p, t)
            for p, t in decodable_text_files(REPO_ROOT)
            if p.suffix in {".md", ".rst", ".txt"}
        ]
        findings = find_identifier_mentions(files, pkg.needles(), REPO_ROOT)
        assert findings == [], (
            f"a production-dir document names the fourth task: {findings}. The "
            f"package documents itself (§D.2 ships its own README); a node or "
            f"operator doc that has to name it is accommodation in prose."
        )

    @pytest.mark.parametrize("production_dir", PRODUCTION_DIRS)
    def test_a_plant_in_EVERY_production_dir_is_caught_exactly_once(self, production_dir, tmp_path):
        """F-12bc-9, discharged by exhaustion rather than by inspection. A
        census whose file set omits one directory passes its own review; nine
        parametrized plants do not let it."""
        rel = f"{production_dir}/planted.py"
        root = _mirror(tmp_path, {rel: f"TASK = '{PLANT_NEEDLE}'\n"})
        findings = find_identifier_mentions(decodable_text_files(root), PLANT_NEEDLES, root)
        _one(findings, f"plant in {production_dir}")
        assert findings[0].path == rel

    @pytest.mark.parametrize(
        "rel",
        [
            "src/dashboard/app.js",
            "sdsc_submission_scripts/run_x.sh",
            "sdsc_submission_scripts/job.slurm",
            "src/dashboard/index.html",
        ],
    )
    def test_a_plant_in_a_NON_PYTHON_file_is_caught_exactly_once(self, rel, tmp_path):
        """F-12e-UX-8 by name: the recorded defect was a census over
        ``*.py`` while the code lived in ``app.js``."""
        root = _mirror(tmp_path, {rel: f"var task = '{PLANT_NEEDLE}';\n"})
        findings = find_identifier_mentions(decodable_text_files(root), PLANT_NEEDLES, root)
        _one(findings, f"plant in {rel}")
        assert findings[0].path == rel

    def test_the_baseline_is_green_once_the_plant_is_removed(self, tmp_path):
        """The other half of every mutation proof. Without it, a census that
        reports a finding on ANY input looks identical to one that works."""
        root = _mirror(tmp_path, {"src/core/planted.py": f"TASK = '{PLANT_NEEDLE}'\n"})
        assert len(find_identifier_mentions(decodable_text_files(root), PLANT_NEEDLES, root)) == 1
        (root / "src/core" / "planted.py").write_text("TASK = 'something_else'\n", encoding="utf-8")
        assert find_identifier_mentions(decodable_text_files(root), PLANT_NEEDLES, root) == []


# ======================================================================
# §I.3 bullet 2 / 6 — dispatch and catalog
# ======================================================================


class TestTheGeneralizedDetectorIsAGeneralizationNotACopy:
    def test_the_generalized_detector_is_never_BLINDER_than_the_p1_detector(self):
        """The one defect only this test catches: a SECOND dispatch detector
        drifting from P1's and being blind where P1 sees.

        The claim is a SUPERSET, not equality, and the direction is the point
        — this detector may report more (it is spelling-normalized), but it
        may never report less. If P1 gains a sixth shape and this one does
        not, this goes red: F-12bc-9's failure mode applied to detector logic
        instead of to a file set. Equality is asserted separately, over the
        current tree, so a widening is a deliberate act.
        """
        for path in _python_files(REPO_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            mine = set(find_identity_dispatch(tree, TASK_NAMES))
            theirs = set(find_task_identity_dispatch(tree))
            assert theirs <= mine, (
                f"the generalized detector is BLIND where P1's sees, on "
                f"{path}: {sorted(theirs - mine)}"
            )
            assert mine == theirs, (
                f"the generalized detector reports what P1's does not, on "
                f"{path}: {sorted(mine - theirs)}. That is not wrong in "
                f"principle, but it must be a deliberate widening."
            )
        for source in (
            'if task == "tidmad":\n    pass\n',
            'if name in ("pets", "davis"):\n    pass\n',
            'TABLE = {"tidmad": 1, "pets": 2}\n',
            'value = TABLE["davis"]\n',
            'match task:\n    case "tidmad":\n        pass\n',
        ):
            tree = ast.parse(source)
            assert find_identity_dispatch(tree, TASK_NAMES) == find_task_identity_dispatch(tree)


class TestNoBranchIsKeyedOnTheFourthTask:
    """§I.3 bullet 6 = §J's N11. **How it fails**: plant any of the five
    shapes keyed on the package's identity and the census names the shape."""

    def test_no_production_module_branches_on_the_package_identity(self):
        pkg = require_package_identifiers()
        offenders: dict[str, list[tuple[int, str]]] = {}
        for path in _python_files(REPO_ROOT):
            hits = find_identity_dispatch(
                ast.parse(path.read_text(encoding="utf-8", errors="ignore")), pkg.needles()
            )
            if hits:
                offenders[str(path.relative_to(REPO_ROOT))] = hits
        assert offenders == {}, f"the fourth task selects framework behaviour: {offenders}"

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            (f'if task == "{PLANT_NEEDLE}":\n    pass\n', "comparison against a task name"),
            (
                f'if t in ("tidmad", "{PLANT_NEEDLE}"):\n    pass\n',
                "membership test over task names",
            ),
            (f'TABLE = {{"{PLANT_NEEDLE}": 1}}\n', "mapping keyed on a task name"),
            (f'v = TABLE["{PLANT_NEEDLE}"]\n', "subscript by a task name"),
            (f'match t:\n    case "{PLANT_NEEDLE}":\n        pass\n', "match-case on a task name"),
        ],
    )
    def test_N11_the_bypass_plant_turns_the_census_red_exactly_once(self, source, expected):
        hits = find_identity_dispatch(ast.parse(source), PLANT_NEEDLES)
        _one(hits, f"N11 plant {expected}")
        assert hits[0][1] == expected

    def test_N11_baseline_is_green_without_the_plant(self):
        assert (
            find_identity_dispatch(ast.parse("if task == other:\n    pass\n"), PLANT_NEEDLES) == []
        )

    def test_the_detector_does_not_flag_a_banner_or_a_named_constant(self):
        """Anti-false-positive, inherited from P1 and re-proven for the
        generalized detector: a census that reports a print statement trains
        the next reader to ignore it."""
        assert (
            find_identity_dispatch(
                ast.parse(f'print("=== {PLANT_NEEDLE} activated ===")\n'), PLANT_NEEDLES
            )
            == []
        )
        assert (
            find_identity_dispatch(
                ast.parse("if header != PLUGIN_HEADER:\n    pass\n"), PLANT_NEEDLES
            )
            == []
        )


class TestNoCentralTaskCatalog:
    """§I.3 bullet 2. A catalog needs no ``if``, so the dispatch census walks
    straight past it — that is the defect only this test catches."""

    def test_production_holds_no_container_naming_two_task_identities(self):
        names = tuple(TASK_NAMES)
        root = package_root_from_env()
        if root is not None:
            names = names + resolve_package_identifiers(root).needles()
        offenders: dict[str, list[tuple[int, str]]] = {}
        for path in _python_files(REPO_ROOT):
            hits = find_task_catalog(
                ast.parse(path.read_text(encoding="utf-8", errors="ignore")), names
            )
            if hits:
                offenders[str(path.relative_to(REPO_ROOT))] = hits
        assert offenders == {}, (
            f"a central id -> behaviour catalog exists: {offenders}. Registration "
            f"happens because the TASK's own file ran; a table is the other thing."
        )

    @pytest.mark.parametrize(
        "source",
        [
            f'CATALOG = {{"tidmad": A, "{PLANT_NEEDLE}": B}}\n',
            f'KNOWN = ("tidmad", "pets", "{PLANT_NEEDLE}")\n',
            f'KNOWN = ["tidmad", "{PLANT_NEEDLE}"]\n',
            f'KNOWN = {{"tidmad", "{PLANT_NEEDLE}"}}\n',
        ],
    )
    def test_a_catalog_plant_is_caught_exactly_once(self, source):
        hits = find_task_catalog(ast.parse(source), (*TASK_NAMES, PLANT_NEEDLE))
        _one(hits, "catalog plant")

    def test_one_id_alone_is_not_a_catalog(self):
        """The threshold that keeps this from firing on every implementation
        that names itself — ``pets_data_path.py`` compares against its OWN
        header constant, and a single id in a literal is that shape."""
        assert find_task_catalog(ast.parse('MINE = ("tidmad",)\n'), TASK_NAMES) == []


# ======================================================================
# §I.3 bullet 3 — no production import from the package
# ======================================================================


class TestNoProductionModuleImportsThePackage:
    """**How it fails**: add ``import <pkg>`` anywhere in production and this
    names the file and the line. The defect only this test catches is an
    import that a TEXT census would also see but could not classify — the
    distinction matters because an import is executable coupling while a
    mention in a comment is not."""

    def test_no_production_module_reaches_into_the_package(self):
        pkg = require_package_identifiers()
        offenders: dict[str, list[tuple[int, str]]] = {}
        for path in _python_files(REPO_ROOT):
            hits = find_package_imports(
                ast.parse(path.read_text(encoding="utf-8", errors="ignore")), pkg.needles()
            )
            if hits:
                offenders[str(path.relative_to(REPO_ROOT))] = hits
        assert offenders == {}, f"production imports the external package: {offenders}"

    @pytest.mark.parametrize(
        "source",
        [
            f"import {PLANT_NEEDLE}\n",
            f"from {PLANT_NEEDLE}.plugins import DataPath\n",
            f"from x import {PLANT_NEEDLE}\n",
            f'importlib.import_module("{PLANT_NEEDLE}")\n',
            f'__import__("{PLANT_NEEDLE}")\n',
            f'sys.path.insert(0, "/opt/{PLANT_NEEDLE}/plugins")\n',
            f'spec_from_file_location("m", "/opt/{PLANT_NEEDLE}/p.py")\n',
        ],
    )
    def test_every_reach_in_shape_is_caught_exactly_once(self, source):
        hits = find_package_imports(ast.parse(source), PLANT_NEEDLES)
        _one(hits, f"import plant {source.strip()!r}")

    def test_an_unrelated_import_is_not_flagged(self):
        assert (
            find_package_imports(
                ast.parse("import json\nfrom pathlib import Path\n"), PLANT_NEEDLES
            )
            == []
        )


# ======================================================================
# §I.3 bullet 4 — no hidden fallback to TIDMAD  (= §J's N9)
# ======================================================================


class TestNoHiddenFallbackToTidmad:
    """§I.3 bullet 4 / N9. The C-P56-1 shape one layer down: a family that
    fails to resolve must REFUSE, never silently become TIDMAD's.

    **Why the detector is narrow and not "any mention of TIDMAD"**:
    ``resolve_task_data_path`` legitimately names ``TIDMAD_COMPATIBILITY_ID``
    inside ``if context is None:``, because the frozen truth table says a
    DECLARED absence resolves the compatibility path. A census that flagged
    it would be switched off. What is forbidden is the same symbol reached
    from a FAILURE position."""

    def test_no_production_module_falls_back_to_a_tidmad_default(self):
        """The standing guard. Counts are pinned EXACTLY, per file: a second
        legacy default inside an already-exempt file is a new fallback and
        fails here, which a file-level exemption would have hidden."""
        counted: dict[str, int] = {}
        detail: dict[str, list[tuple[int, str]]] = {}
        for path in _python_files(REPO_ROOT):
            hits = find_silent_task_fallback(
                ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            )
            if hits:
                rel = str(path.relative_to(REPO_ROOT))
                counted[rel] = len(hits)
                detail[rel] = hits
        assert counted == _ALLOWED_LEGACY_DEFAULTS, (
            f"a failure path resolves TIDMAD's default: {detail}.\n"
            f"expected exactly {_ALLOWED_LEGACY_DEFAULTS}. A composed run that "
            f"cannot resolve a family must refuse — silently scoring with "
            f"TIDMAD's semantics is C-P56-1 one layer down."
        )

    @pytest.mark.parametrize(
        "source",
        [
            "try:\n    m = compose()\nexcept Exception:\n    m = TIDMAD_METRIC_ID\n",
            "impl = registry.get(task_id) or TIDMAD\n",
            "impl = registry.get(task_id, TIDMAD_COMPATIBILITY_ID)\n",
            "impl = found if found else TIDMAD_PROFILE\n",
            "impl = getattr(mod, 'x', TIDMAD_PROFILE)\n",
            "try:\n    m = compose()\nexcept Exception:\n    m = derive_tidmad_metric()\n",
        ],
    )
    def test_N9_a_fallback_plant_turns_the_census_red_exactly_once(self, source):
        hits = find_silent_task_fallback(ast.parse(source))
        _one(hits, f"N9 plant {source.splitlines()[-1].strip()!r}")

    def test_the_declared_regime_A_row_is_NOT_flagged(self):
        """The near-miss that decides whether this census survives contact
        with the real tree. Quoted from ``resolve_task_data_path``."""
        source = (
            "def resolve(context):\n"
            "    if context is None:\n"
            "        impl = _REGISTRY.get(TIDMAD_COMPATIBILITY_ID)\n"
            "        if impl is None:\n"
            "            raise TaskDataPathResolutionError('...')\n"
            "        return impl\n"
        )
        assert find_silent_task_fallback(ast.parse(source)) == []


# ======================================================================
# §I.3 bullet 7 — no schema grew to name the fourth task
# ======================================================================


class TestNoSchemaGrewToNameTheFourthTask:
    """§I.3 bullet 7. **How it fails**: add ``EVENTSEQ = "eventseq"`` to any
    enum or ``eventseq_scope: str`` to any record and this names the class
    and the member."""

    def test_the_manifest_vocabulary_did_not_grow(self):
        """Asserted through the PRODUCTION constant, not a copy of it: the
        composition root is §E's 'CONSUMES ONLY' authority, and a fourth task
        needing a new manifest key is a §N STOP."""
        pkg = require_package_identifiers()
        from workflows.task_composition import _MANIFEST_KEYS, composition_field_names

        keys = [_normalize(n) for n in pkg.needles()]
        for name in (*_MANIFEST_KEYS, *composition_field_names()):
            assert _matches(name, keys) is None, (
                f"the composition vocabulary grew {name!r} to name the fourth task"
            )

    def test_no_enum_member_or_record_field_names_it(self):
        pkg = require_package_identifiers()
        offenders: dict[str, list[tuple[int, str]]] = {}
        for path in _python_files(REPO_ROOT):
            hits = find_declared_identifier_growth(
                ast.parse(path.read_text(encoding="utf-8", errors="ignore")), pkg.needles()
            )
            if hits:
                offenders[str(path.relative_to(REPO_ROOT))] = hits
        assert offenders == {}, f"a production schema names the fourth task: {offenders}"

    @pytest.mark.parametrize(
        "source",
        [
            f'class Kind(StrEnum):\n    FOURTH = "{PLANT_NEEDLE}"\n',
            f"class Record(BaseModel):\n    {PLANT_NEEDLE}_scope: str\n",
            f'class C:\n    NAME = "{PLANT_NEEDLE}"\n',
        ],
    )
    def test_a_schema_growth_plant_is_caught_exactly_once(self, source):
        _one(find_declared_identifier_growth(ast.parse(source), PLANT_NEEDLES), "schema plant")

    def test_an_unrelated_field_is_not_flagged(self):
        assert (
            find_declared_identifier_growth(
                ast.parse("class R(BaseModel):\n    file_index: int = 0\n"), PLANT_NEEDLES
            )
            == []
        )


class TestTheNeedleSourceSetCoversWhereIdentitiesActuallyLIVE:
    """F-12bc-9 applied to the NEEDLE SET rather than to the file set.

    A census whose file set omits a directory is blind there; so is one whose
    needle EXTRACTION omits a structural position. The first draft read only
    ``file:``/``symbol:``/``id:`` and the real package's model type, objective
    name and three plugin modules arrive through ``dir:``-scanned directories
    and module-level constants — five identities the census would have hunted
    for while claiming to hunt for everything.

    **How these fail**: delete the ``dir:`` scan and the plugin-directory row
    goes red; delete the constant scavenger and the ``PLUGIN_MODEL_TYPE`` row
    goes red; delete the ``require:`` reader and the third goes red.
    """

    @staticmethod
    def _pkg(tmp_path: Path) -> Path:
        root = tmp_path / "pkg"
        (root / "declared").mkdir(parents=True)
        (root / "plugins").mkdir(parents=True)
        (root / "composition.yaml").write_text(
            "task_data_path:\n"
            "  file: plugins/named_data_path.py\n"
            "  symbol: NamedDataPath\n"
            "  id: a_declared_task_v0\n"
            "model_plugins:\n"
            "  dir: plugins\n"
            "  require: [a_required_plugin_type]\n",
            encoding="utf-8",
        )
        (root / "plugins" / "named_data_path.py").write_text("X = 1\n", encoding="utf-8")
        (root / "plugins" / "scanned_model.py").write_text(
            'PLUGIN_MODEL_TYPE = "a_scanned_model_type"\nBARE = "classifier"\n',
            encoding="utf-8",
        )
        return root

    def test_a_dir_scanned_plugin_module_becomes_a_needle(self, tmp_path):
        needles = resolve_package_identifiers(self._pkg(tmp_path)).needles()
        assert "scanned_model" in needles

    def test_a_module_level_identity_constant_becomes_a_needle(self, tmp_path):
        needles = resolve_package_identifiers(self._pkg(tmp_path)).needles()
        assert "a_scanned_model_type" in needles

    def test_a_require_entry_becomes_a_needle(self, tmp_path):
        needles = resolve_package_identifiers(self._pkg(tmp_path)).needles()
        assert "a_required_plugin_type" in needles

    def test_a_BARE_WORD_constant_does_NOT_become_a_needle(self, tmp_path):
        """The other half, and the reason the three rows above are safe to
        widen. ``BARE = "classifier"`` is an ordinary module constant; as a
        needle it would report a finding on half of production and the census
        would be switched off within a week."""
        needles = resolve_package_identifiers(self._pkg(tmp_path)).needles()
        assert "classifier" not in needles
        assert not any(_normalize(n) == "classifier" for n in needles)


# ======================================================================
# §I.3 bullet 5 — no package constant copied into production
# ======================================================================


class TestNoPackageConstantWasCopiedIntoProduction:
    """§I.3 bullet 5. The net for the case where somebody copies a VALUE
    without the name — which the identifier census by definition cannot see.

    **This net's honest limit is documented at :func:`_is_distinctive`**: only
    values a generic module would not hold by accident are censused, and a
    package with no such value gets a NAMED SKIP rather than a silent pass."""

    def test_the_copied_value_net_refuses_to_be_vacuous(self):
        pkg = require_package_identifiers()
        if not pkg.distinctive_values:
            pytest.skip(
                f"{pkg.package_name} declares no distinctive constant (int >= 1000 "
                f"or a float with >= 3 decimals), so this net covers nothing for "
                f"it. Named rather than passed — a vacuous green is the failure "
                f"mode this whole module exists to prevent."
            )
        assert pkg.distinctive_values

    def test_no_distinctive_package_constant_appears_in_production(self):
        pkg = require_package_identifiers()
        if not pkg.distinctive_values:
            pytest.skip("no distinctive constant to census; see the test above")
        findings = find_copied_values(
            decodable_text_files(REPO_ROOT), pkg.distinctive_values, REPO_ROOT
        )
        assert findings == [], f"a package constant was copied into production: {findings}"

    def test_a_copied_constant_plant_is_caught_exactly_once(self, tmp_path):
        root = _mirror(tmp_path, {"src/core/planted.py": "VOCAB = 7919\n"})
        _one(find_copied_values(decodable_text_files(root), (7919.0,), root), "constant plant")

    def test_a_substring_of_a_larger_number_is_not_a_finding(self, tmp_path):
        """``7919`` inside ``179190`` is not the constant, and a census that
        said so would be switched off inside a week."""
        root = _mirror(tmp_path, {"src/core/planted.py": "N = 179190\nM = 0.79191\n"})
        assert find_copied_values(decodable_text_files(root), (7919.0,), root) == []

    def test_the_distinctiveness_filter_is_the_documented_one(self):
        """Pins the filter so a future widening is a deliberate act: small
        round numbers are excluded because ``32`` and ``0.5`` occur in every
        module, which would make this net noise."""
        assert _is_distinctive(7919) and _is_distinctive(0.0137)
        assert not _is_distinctive(32) and not _is_distinctive(0.5)


# ======================================================================
# §I.4 — the census's own negative control
# ======================================================================


class TestTheCensusRefusesAMisconfiguredPackage:
    """§I.4's spirit at the binding layer. A census that SKIPS because the
    Gate's environment held a typo would report 'green' for a run that never
    censused anything — the vacuity §I.4 exists to prevent, one level up."""

    def test_a_missing_package_path_RAISES_rather_than_skipping(self, tmp_path):
        with pytest.raises(PackageNotAvailable, match=re.escape("composition.yaml")):
            resolve_package_identifiers(tmp_path / "nope")

    def test_a_package_without_a_declared_task_id_RAISES(self, tmp_path):
        root = tmp_path / "pkg"
        root.mkdir()
        (root / "composition.yaml").write_text("metric: {}\n", encoding="utf-8")
        with pytest.raises(PackageNotAvailable, match=re.escape("task_data_path.id")):
            resolve_package_identifiers(root)

    def test_an_unset_variable_skips_with_a_reason(self, monkeypatch):
        monkeypatch.delenv(PACKAGE_ROOT_ENV, raising=False)
        assert package_root_from_env() is None

    def test_the_needles_come_from_the_package_not_from_this_file(self, tmp_path):
        """F-12bc-6's immunity, executable. Rename the task in the package
        and the needle set follows — a hardcoded list would keep censusing
        for the OLD name and stay green through the very landing it exists to
        announce."""
        root = tmp_path / "pkg"
        (root / "declared").mkdir(parents=True)
        (root / "composition.yaml").write_text(
            "task_data_path:\n"
            "  file: plugins/renamed_data_path.py\n"
            "  symbol: RenamedDataPath\n"
            "  id: renamed_task_v9\n"
            "metric:\n"
            "  declaration: declared/metric.json\n",
            encoding="utf-8",
        )
        (root / "declared" / "metric.json").write_text(
            json.dumps({"id": "renamed_nll_loss", "direction": "lower", "cutoff": 8191}),
            encoding="utf-8",
        )
        pkg = resolve_package_identifiers(root)
        keys = {_normalize(n) for n in pkg.needles()}
        assert "renamedtaskv9" in keys, "the declared task id is not a needle"
        assert "renamednllloss" in keys, "the declared metric id is not a needle"
        # The plugin SYMBOL and the plugin FILE STEM normalize to one needle
        # — they are the same identity spelled two ways, which is the whole
        # point of normalizing, so the needle set holds one of them.
        assert "renameddatapath" in keys
        assert 8191.0 in pkg.distinctive_values


class TestTheRealTreeCensusIsReachableBeforeThePackageExists:
    """The defect only this class catches: **a census that is nothing but a
    skip**.

    Every guard above that needs the package SKIPS until
    ``SIDERIUS_12E_PACKAGE_ROOT`` is bound at the integration checkpoint. A
    suite of skips looks exactly like a suite of passes in a summary line, and
    would let 12e reach its Gate having never once run the census over the
    real repository.

    So these bind a SYNTHETIC package — a minimal §D.2-shaped manifest in
    ``tmp_path``, not workstream A's deliverable — and drive the real-tree
    censuses through it. The negative row uses a needle that IS in production,
    so the census is proven to go RED against the real tree, not merely to
    complete.
    """

    @staticmethod
    def _synthetic(tmp_path: Path, task_id: str, symbol: str) -> Path:
        root = tmp_path / "synthetic_pkg"
        root.mkdir(parents=True, exist_ok=True)
        (root / "composition.yaml").write_text(
            f"task_data_path:\n  file: plugins/p.py\n  symbol: {symbol}\n  id: {task_id}\n",
            encoding="utf-8",
        )
        return root

    def test_the_real_tree_is_clean_against_a_task_it_has_never_heard_of(
        self, tmp_path, monkeypatch
    ):
        root = self._synthetic(tmp_path, "quantum_lattice_probe_v0", "QuantumLatticeProbe")
        monkeypatch.setenv(PACKAGE_ROOT_ENV, str(root))
        pkg = require_package_identifiers()
        assert (
            find_identifier_mentions(decodable_text_files(REPO_ROOT), pkg.needles(), REPO_ROOT)
            == []
        )
        for path in _python_files(REPO_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            assert find_identity_dispatch(tree, pkg.needles()) == []
            assert find_package_imports(tree, pkg.needles()) == []
            assert find_declared_identifier_growth(tree, pkg.needles()) == []

    def test_the_real_tree_census_goes_RED_for_a_name_production_does_hold(
        self, tmp_path, monkeypatch
    ):
        """Reachability, the only way it can honestly be shown: a needle that
        production genuinely contains must be REPORTED. A census returning
        ``[]`` because it walked nothing is indistinguishable from a clean
        tree until this row exists."""
        root = self._synthetic(tmp_path, "deliverable_naming", "DeliverableNaming")
        monkeypatch.setenv(PACKAGE_ROOT_ENV, str(root))
        pkg = require_package_identifiers()
        findings = find_identifier_mentions(
            decodable_text_files(REPO_ROOT), pkg.needles(), REPO_ROOT
        )
        assert findings, (
            "the real-tree identifier census reported nothing for a name production holds — it is walking an empty file set"
        )
        assert any(f.path == "src/execute_tools/deliverable_spec.py" for f in findings)


class TestTheCensusReadsBytesNotImports:
    """The fifth, unnumbered blindness shape. A census that imports what it
    censuses can be fooled by a stale ``.pyc``; nothing here imports a
    production module to inspect it.

    **How this fails**: switch any census to ``inspect.getsource(module)`` or
    to reading ``module.__dict__`` and this reports the import."""

    def test_no_census_helper_imports_a_production_module_to_inspect_it(self):
        source = Path(__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        banned = {"getsource", "getsourcefile", "getmembers", "import_module"}
        used = {
            node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        }
        assert not (used & banned), (
            f"the census inspects imported objects ({used & banned}); a stale "
            f".pyc can then make it green. Read source bytes instead."
        )


# ======================================================================
# The Gate's entry point — §I.2 executed from a shell, around a real run
# ======================================================================
#
# `zero_infrastructure_edit` is the in-Python form. `G-12e` launches through
# the operator surface (a shell script), so the two halves of the measurement
# have to be callable as separate processes with the baseline persisted in
# between:
#
#     cd <repo root>
#     python -m tests.unit.guardrails.test_step12_pr12e_census snapshot base.json
#     ... the real run ...
#     python -m tests.unit.guardrails.test_step12_pr12e_census verify   base.json
#
# The `-m` form is the tested one: it puts the repository root on `sys.path`
# without a PYTHONPATH the Gate script could forget to export.
#
# `verify` exits 1 and prints the delta if anything under the nine production
# dirs moved. Without this the Gate would have to take the census on trust, or
# re-implement the manifest in bash — and a second implementation of the
# measurement is how the two stop agreeing.


#: The dotted module path the Gate invokes. Derived from this file's own
#: location so a move cannot leave the documented command pointing at nothing.
_CLI_MODULE = ".".join(Path(__file__).resolve().relative_to(REPO_ROOT).with_suffix("").parts)


def git_head(root: Path = REPO_ROOT) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def census_snapshot(root: Path = REPO_ROOT) -> dict[str, Any]:
    status = git_status_porcelain(root)
    return {
        "head": git_head(root),
        "clean": status.strip() == "",
        "status": status,
        "production_dirs": list(PRODUCTION_DIRS),
        "file_count": len(production_files(root)),
        "manifest": tree_manifest(root),
    }


def census_verify(baseline: dict[str, Any], root: Path = REPO_ROOT) -> tuple[bool, dict[str, Any]]:
    status = git_status_porcelain(root)
    delta = manifest_delta(baseline["manifest"], tree_manifest(root))
    report = {
        "baseline_head": baseline.get("head"),
        "head": git_head(root),
        "baseline_clean": baseline.get("clean"),
        "clean": status.strip() == "",
        "status": status,
        "delta": delta,
    }
    ok = (
        bool(baseline.get("clean"))
        and report["clean"]
        and delta == {"added": [], "removed": [], "modified": []}
    )
    return ok, report


def _cli(argv: list[str]) -> int:  # pragma: no cover - exercised by subprocess
    if len(argv) != 3 or argv[1] not in {"snapshot", "verify"}:
        print(
            "usage: test_step12_pr12e_census.py {snapshot|verify} <baseline.json>",
            file=sys.stderr,
        )
        return 2
    target = Path(argv[2])
    if argv[1] == "snapshot":
        snapshot = census_snapshot()
        target.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
        print(
            f"[census] baseline at {snapshot['head'][:12]} — "
            f"{snapshot['file_count']} files, clean={snapshot['clean']}"
        )
        return 0 if snapshot["clean"] else 1
    ok, report = census_verify(json.loads(target.read_text(encoding="utf-8")))
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"[census] ZERO-INFRASTRUCTURE-EDIT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


class TestTheGateEntryPoint:
    """The CLI a shell Gate calls, proven to PASS and to FAIL.

    **The defect only this class catches**: a Gate script that runs the census
    and always sees exit 0. Both halves are exercised as real processes on a
    throwaway repository, because the exit code is the whole interface — an
    in-process call to :func:`census_verify` would not prove the CLI wires its
    return value to one.
    """

    @staticmethod
    def _repo(tmp_path: Path) -> Path:
        root = tmp_path / "repo"
        (root / "src/core").mkdir(parents=True)
        (root / "src/core" / "m.py").write_text("x = 1\n", encoding="utf-8")
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "base"]):
            subprocess.run(["git", *args], cwd=str(root), check=True, env=env, capture_output=True)
        return root

    def test_snapshot_then_verify_PASSES_when_the_run_touched_nothing(self, tmp_path):
        root = self._repo(tmp_path)
        baseline = census_snapshot(root)
        assert baseline["clean"]
        ok, report = census_verify(baseline, root)
        assert ok, report

    def test_verify_FAILS_when_the_run_wrote_into_a_production_dir(self, tmp_path):
        root = self._repo(tmp_path)
        baseline = census_snapshot(root)
        (root / "src/core" / "written_by_the_run.py").write_text("y = 2\n", encoding="utf-8")
        ok, report = census_verify(baseline, root)
        assert not ok
        assert report["delta"]["added"] == ["src/core/written_by_the_run.py"]
        assert not report["clean"]

    def test_verify_FAILS_when_the_BASELINE_was_taken_from_a_dirty_tree(self, tmp_path):
        """A baseline recorded on a dirty tree cannot support 'unchanged after
        the run', so the verdict must be FAIL even when nothing moved
        afterwards — otherwise a Gate could launder a dirty tree by
        snapshotting it."""
        root = self._repo(tmp_path)
        (root / "src/core" / "already_dirty.py").write_text("z = 3\n", encoding="utf-8")
        baseline = census_snapshot(root)
        assert not baseline["clean"]
        ok, _ = census_verify(baseline, root)
        assert not ok

    def test_the_cli_exits_non_zero_on_a_violation(self, tmp_path):
        """Reachability of the EXIT CODE, as a real process. A Gate script
        reads ``$?`` and nothing else."""
        baseline = tmp_path / "base.json"
        root = self._repo(tmp_path)
        payload = census_snapshot(root)
        payload["manifest"]["src/core/ghost.py"] = "0" * 64
        baseline.write_text(json.dumps(payload), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", _CLI_MODULE, "verify", str(baseline)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "FAIL" in result.stdout

    def test_the_cli_refuses_an_unknown_subcommand(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", _CLI_MODULE, "wat", str(tmp_path / "x.json")],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2


def _package_authored_names(root: Path) -> frozenset[str]:
    """Module-level names the external package defines that NO shipped pack does.

    The discriminator is structural and non-circular: a name defined by the
    external package AND by an in-tree pack under ``examples/*/plugins/`` is
    **plugin-contract vocabulary** (``PLUGIN_LOSS_TYPE``, ``PluginLossConfig``)
    that production references legitimately. A name only the external package
    defines is **package-authored**.

    Derived from the PACKS, never from production -- so a planted
    accommodation cannot make its own name look legitimate, which is the
    circularity the operator explicitly forbade.
    """

    def _defined(paths) -> set[str]:
        names: set[str] = set()
        for path in paths:
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, SyntaxError):  # pragma: no cover - a broken plugin
                continue
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    names.update(t.id for t in node.targets if isinstance(t, ast.Name))
                elif isinstance(node, ast.ClassDef | ast.FunctionDef):
                    names.add(node.name)
        return names

    shipped = _defined((REPO_ROOT / "examples").rglob("plugins/*.py"))
    # Names SIDERIUS itself DEFINES are the framework's own vocabulary --
    # `__all__`, and protocol method names like `deliverable_name` that the
    # package implements because the ABC requires them. Excluding what
    # production DEFINES is not the forbidden circularity: that rule was
    # "exclude because the name APPEARS in production", which a plant could
    # satisfy by referencing it. A plant REFERENCES; it does not define the
    # package's class as its own.
    owned = _defined(p for p in production_files(REPO_ROOT) if p.suffix == ".py")
    external = _defined((root / "plugins").glob("*.py"))
    return frozenset(external - shipped - owned)


class TestNoProductionSourceReferencesAPackageAuthoredSymbol:
    """The complementary half of the identifier census -- the FALSE-NEGATIVE side.

    `_contract_metadata_symbols` deliberately drops a manifest ``symbol:`` that
    resolves to a module-level string constant, and the loader does NOT
    guarantee such a name is framework-owned (``_compose_objective`` constrains
    the VALUE, never the NAME). So a package-authored constant name can be
    absent from the needle set.

    **Proven gap, not a hypothetical**: planting
    ``getattr(mod, "EVENTSEQ_TASK_DATA_PATH_ID")`` in a production module left
    every other guard GREEN -- the import census sees no import, and the
    identifier census never held that NAME.

    **How this fails**: production names any symbol only the external package
    defines, and this reports the file, line and symbol. Kept deliberately
    narrow -- it is a set-membership test over names, not an identifier
    analyzer, and it infers nothing from capitalization, naming style or
    nesting depth.
    """

    def test_no_production_module_names_a_package_authored_symbol(self):
        root = package_root_from_env()
        if root is None:
            pytest.skip(f"{PACKAGE_ROOT_ENV} is unset; the package is not present")
        authored = _package_authored_names(root)
        assert authored, "the package defines no authored symbols -- extraction is broken"
        offenders: list[tuple[str, int, str]] = []
        for path in production_files(REPO_ROOT):
            if path.suffix != ".py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:  # pragma: no cover
                continue
            rel = str(path.relative_to(REPO_ROOT))
            for node in ast.walk(tree):
                name = None
                if isinstance(node, ast.Name):
                    name = node.id
                elif isinstance(node, ast.Attribute):
                    name = node.attr
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    name = node.value
                if name in authored:
                    offenders.append((rel, getattr(node, "lineno", 0), name))
        assert offenders == [], (
            f"production source names symbols only the external package "
            f"defines: {offenders}. That is task-specific accommodation -- the "
            f"framework would be reaching for this package's own vocabulary."
        )

    def test_the_contract_vocabulary_is_NOT_reported(self):
        """Anti-false-positive: the shared plugin-contract names production
        legitimately references must never be authored names, or this guard
        would fire on every loader and get switched off."""
        root = package_root_from_env()
        if root is None:
            pytest.skip(f"{PACKAGE_ROOT_ENV} is unset; the package is not present")
        authored = _package_authored_names(root)
        assert "PLUGIN_LOSS_TYPE" not in authored
        assert "PLUGIN_MODEL_TYPE" not in authored


if __name__ == "__main__":  # pragma: no cover
    # ANY argument goes to the CLI, including an unrecognised one.
    #
    # The first draft fell through to `pytest.main` for an unknown subcommand,
    # and the CLI's own "refuses an unknown subcommand" test spawns exactly
    # that — so running this file re-ran the whole module, whose test spawned
    # it again. A fork bomb, written by the test that was checking the error
    # path. Direct execution with no arguments runs the suite; with arguments
    # it is the Gate's tool and nothing else.
    sys.exit(_cli(sys.argv) if len(sys.argv) > 1 else pytest.main([__file__, "-q"]))
