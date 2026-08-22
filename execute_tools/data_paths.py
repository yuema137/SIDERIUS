"""
Machine-specific data paths — loaded from tidmad_data_config.yaml.

All modules import from here instead of hardcoding paths.
When migrating to a new server, update tidmad_data_config.yaml only.

Usage:
    from execute_tools.data_paths import TIDMAD_DATA_DIR, SIDERIUS_DATA_DIR
"""

import os
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

# Find config file relative to project root. The real (gitignored) config is
# ``tidmad_data_config.yaml``; the tracked template is
# ``tidmad_data_config.example.yaml``. Fall back to the template (with a
# warning) so unit tests and fresh clones can import this module without
# manual setup — production code that actually reads from these paths still
# fails loudly when the placeholder template values are used.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "tidmad_data_config.yaml")
_EXAMPLE_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "tidmad_data_config.example.yaml")

if os.path.exists(_CONFIG_PATH):
    _active_config_path = _CONFIG_PATH
elif os.path.exists(_EXAMPLE_CONFIG_PATH):
    warnings.warn(
        f"tidmad_data_config.yaml not found at {_CONFIG_PATH}; "
        f"falling back to template at {_EXAMPLE_CONFIG_PATH}. "
        "Copy the template and update paths for this machine before running "
        "anything that reads from TIDMAD_DATA_DIR or SIDERIUS_DATA_DIR.",
        stacklevel=2,
    )
    _active_config_path = _EXAMPLE_CONFIG_PATH
else:
    raise FileNotFoundError(
        f"Data config not found at {_CONFIG_PATH} and no template available at "
        f"{_EXAMPLE_CONFIG_PATH}. Restore tidmad_data_config.example.yaml or "
        "create tidmad_data_config.yaml manually."
    )

# Use yaml if available, fall back to simple parsing
try:
    import yaml

    with open(_active_config_path) as f:
        _config = yaml.safe_load(f)
except ImportError:
    # Minimal YAML parsing for simple key: value files
    _config = {}
    with open(_active_config_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition(":")
            _config[key.strip()] = value.strip()

TIDMAD_DATA_DIR: str = _config["tidmad_data_dir"]
SIDERIUS_DATA_DIR: str = _config["siderius_data_dir"]


class DatasetDirectoryUnavailable(RuntimeError):
    """The physical dataset directory could not be resolved for a real run.

    Raised by :func:`resolve_dataset_dir` at the LAUNCH boundary so a run
    that cannot read its data fails before it spends anything — not after a
    real LLM has generated and validated a candidate.
    """


def resolve_dataset_dir(explicit: str | None = None, *, purpose: str = "this run") -> str:
    """Resolve the physical dataset directory for a run. **FAILS CLOSED.**

    This is the single resolution point for *where the data physically
    lives*, as distinct from what the dataset semantically IS (that is the
    Dataset Profile's job — a host path is deliberately NOT task semantics).

    Precedence, which is the one already declared in-tree rather than a new
    policy:

    1. an explicit operator override (``--data_dir``);
    2. otherwise ``TIDMAD_DATA_DIR``, i.e. this module's machine-local
       ``tidmad_data_config.yaml``.

    That ordering is what ``core/runtime_control/probe_production.py``
    documents as **F-1a** (*"the dataset path resolves through the single
    source of truth … when no explicit ``data_dir`` is supplied — never a
    second convention"*), and what
    ``tests/unit/sdsc_submission_scripts/test_chain_data_dir_portability.py``
    already asserts about the chain shell: with no ``--data_dir`` the
    rendered invocation omits the flag *"so the Python config layer resolves
    the data directory"*. Before this function existed, nothing on the
    launch path performed that resolution, so the value travelled to the
    tuner as ``None``.

    No machine-specific path is tracked anywhere: the location comes from a
    gitignored per-machine config (or an explicit override), never from
    source, defaults or tests.

    Args:
        explicit: the operator's ``--data_dir``, or ``None``.
        purpose: named in the error message so an operator knows which
            launch refused.

    Returns:
        An existing directory path.

    Raises:
        DatasetDirectoryUnavailable: nothing resolvable, or the resolved
            path is not a directory. Never returns a path that does not
            exist, and never substitutes a different one.
    """
    source = "--data_dir" if explicit else "tidmad_data_config.yaml (TIDMAD_DATA_DIR)"
    candidate = explicit or TIDMAD_DATA_DIR

    if not candidate:
        raise DatasetDirectoryUnavailable(
            f"no dataset directory could be resolved for {purpose}. Consulted: "
            f"{source}. Supply --data_dir <path>, or set `tidmad_data_dir` in "
            f"{_CONFIG_PATH}."
        )
    if not os.path.isdir(candidate):
        detail = ""
        if _active_config_path == _EXAMPLE_CONFIG_PATH and not explicit:
            detail = (
                f" NOTE: {_CONFIG_PATH} does not exist, so the tracked TEMPLATE "
                f"{_EXAMPLE_CONFIG_PATH} supplied this placeholder value. Copy the "
                "template and set the real path for this machine."
            )
        raise DatasetDirectoryUnavailable(
            f"the dataset directory resolved for {purpose} is not a readable "
            f"directory: {candidate!r} (source: {source}).{detail} Supply "
            "--data_dir <path> to override."
        )
    return candidate


# ---------------------------------------------------------------------------
# Run-scoped physical data root (Step 11 C4 — R-11-7, R-11-8)
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS. Before C4 the physical dataset root never crossed the
# subprocess boundary: neither the training nor the inference argv carried
# `--data_dir`, and the scoring argv carried no `--raw_data_dir`, so all
# three children fell back to the module-level ``TIDMAD_DATA_DIR`` resolved
# AT IMPORT. A composed run therefore read TIDMAD's data no matter what it
# had declared — the whole spawn surface has only ever been executed by
# TIDMAD (design §3.1).
#
# WHAT IT IS NOT. A host path is execution provenance, not task semantics
# (R-11-7): it is deliberately excluded from the composition's semantic
# fingerprint, because two checkouts of the same task package at different
# paths are the same scientific run.
#
# The binding mirrors ``task_data_path``'s ContextVar pattern exactly, and
# for the same reason its ``active_*`` / ``resolve_*`` split exists: a
# caller asking *"which root should I use?"* wants the legacy fallback, and
# a caller asking *"is this run explicitly bound?"* must NOT get it —
# otherwise every legacy child's argv gains a flag it never had.

_ACTIVE_PHYSICAL_DATA_ROOT: ContextVar[str | None] = ContextVar(
    "siderius_active_physical_data_root", default=None
)


@contextmanager
def bind_physical_data_root(root: str, *, purpose: str = "this run") -> Iterator[str]:
    """Bind the run's resolved physical dataset root for the run scope.

    **Fails closed at the BINDING edge** (R-11-8), which is the point: a
    composed run whose declared root is missing, empty, a placeholder or
    not a directory must be refused before it spends an LLM call or a GPU
    minute — not after a child has silently read somebody else's data.
    Validation is :func:`resolve_dataset_dir`, so there is exactly ONE
    fail-closed rule and this is not a second convention.

    Args:
        root: the resolved root, e.g. the operator's ``--data_dir``.
        purpose: named in the refusal so an operator knows which launch
            refused.

    Yields:
        The validated root.

    Raises:
        DatasetDirectoryUnavailable: the root is unusable.
    """
    # An EMPTY root must refuse rather than reach `resolve_dataset_dir`,
    # which treats a falsy `explicit` as "no override supplied" and falls
    # back to TIDMAD_DATA_DIR. That fallback is correct at the LAUNCH
    # boundary and wrong here: binding an empty string is a caller stating
    # a root, and resolving it to TIDMAD's is exactly the silent substitution
    # R-11-8 forbids for a composed run. Found by C4's own negative test.
    if not root or not root.strip():
        raise DatasetDirectoryUnavailable(
            f"an empty physical data root was bound for {purpose}. A composed "
            f"run must name a real directory: an empty value would otherwise "
            f"resolve to the legacy import-time TIDMAD_DATA_DIR, which is the "
            f"silent substitution Step 11 exists to remove."
        )
    validated = resolve_dataset_dir(root, purpose=purpose)
    token = _ACTIVE_PHYSICAL_DATA_ROOT.set(validated)
    try:
        yield validated
    finally:
        _ACTIVE_PHYSICAL_DATA_ROOT.reset(token)


def active_physical_data_root() -> str | None:
    """The bound root, or ``None`` — **without** the legacy fallback.

    This is what the subprocess transport asks. Emitting the flag on the
    strength of a fallback would change the argv of every un-composed
    legacy child, which R-11-1 forbids.
    """
    return _ACTIVE_PHYSICAL_DATA_ROOT.get()


def resolve_physical_data_root() -> str:
    """What a production read site asks for: bound root, else legacy.

    The ``TIDMAD_DATA_DIR`` fallback is the LEGACY / un-composed path and,
    after Step 11, must never be consulted for a composed run (R-11-8) —
    which is enforced by a composed run being required to bind a root
    rather than by a check here. Removing the import-time fallback itself
    is explicitly NOT Step-11 scope: CI resolves the root from the tracked
    template and creates no real config, so removing it would break
    collection repo-wide.
    """
    bound = _ACTIVE_PHYSICAL_DATA_ROOT.get()
    return bound if bound is not None else TIDMAD_DATA_DIR


# ── V20 PR C1 / C-C3b: the task-owned measurement capability ────────────────


def resolve_tidmad_measurement_capability(dataset_root: str | None = None):
    """TIDMAD's answer to "can this environment measure, and measure what?".

    The task-owned half of the §15.3 boundary. `core/runtime_control/` used
    to import `TIDMAD_DATA_DIR` directly, which made the measured-evidence
    path silently unavailable on any other task. The generic resolver now
    takes the dataset root as an argument and refuses to default it; this
    function is where the TIDMAD default legitimately lives, because this
    module IS the TIDMAD data layer.

    Args:
        dataset_root: override, for tests and for a task pointed at another
            copy of the data. Defaults to the configured `TIDMAD_DATA_DIR`.

    Returns:
        `ResolvedMeasurementCapability` -- available or not, always with a
        reason when not.
    """
    from core.runtime_control.measurement_capability import (
        resolve_measurement_capability,
    )
    from execute_tools.dataset_config import TIDMAD

    return resolve_measurement_capability(
        task_identity="tidmad_denoise",
        dataset_adapter="tidmad_hdf5",
        # Shape class, not a path: what makes two datasets interchangeable
        # for resource purposes is the segment geometry, not where they live.
        data_shape_class=(
            f"psd{TIDMAD.psd_segment_length}_seg{TIDMAD.segments_per_file}_files{TIDMAD.num_files}"
        ),
        dataset_root=TIDMAD_DATA_DIR if dataset_root is None else dataset_root,
    )
