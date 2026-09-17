"""Quickstart — the tiny synthetic task's OWN data behaviour, in one file.

This module is the executable half of ``examples/quickstart/``: a seeded data
generator, the :class:`TaskDataPath` implementation (plus the optional
``TaskScopeCapability`` sibling), and the data materializer that regenerates
the task's sha-pinned shards OUTSIDE the repository tree.

Why one file: every plugin here is loaded by an explicit ``file:`` reference
(``workflows/task_composition.py::_load_symbol``), which executes the file
under a synthetic module name — sibling imports between pack plugins would
need path surgery, so the task's data vocabulary stays self-contained instead.
The metric lives in ``_quickstart_metrics.py`` because it is bound by its own
``implementation: {file: ...}`` reference and only imports the framework.

Why the leading underscore: both plugin-directory scanners skip ``_`` members
(the ``examples/oxford_iiit_pet/plugins/_pets_health_views.py`` convention),
so this file is reachable ONLY through the manifest's explicit reference —
never by a directory scan.

The task's declarations are COMMITTED, not generated: since PR-12d landed,
governance guard (a) (``tests/unit/examples/test_pack_governance.py``)
exempts a ``task_config.yaml`` that a shipped
``configs/task_composition/*.yaml`` manifest BINDS — this pack's lives at
``declared/task_config.yaml``, bound by
``configs/task_composition/quickstart.yaml``. Only the DATA is regenerated
per workspace (:func:`materialize_run_bundle`).

Known framework fact this module tolerates (recorded, not papered over): the
tuner populates ``ScopeBuildRequest.task_parameters`` with
``{"seg_size": ...}`` unconditionally
(``nodes/ml_hyperparameter_tune_agent/planning.py:447``), so a non-TIDMAD task
receives that key whether it wants it or not. This task consumes no
task-parameters and IGNORES unknown keys rather than refusing them.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np
from pydantic import BaseModel, ConfigDict

from execute_tools.task_data_path import (
    DeliverableWriteRequest,
    EpochSamplingParams,
    EvalMaterializationParams,
    EvaluationReadRequest,
    ScopeBuildRequest,
    TaskOutputArtifactInventory,
    ValidationScopeError,
    deserialize_rows_scope,
)

if TYPE_CHECKING:  # torch is heavyweight; imported lazily inside methods
    from torch.utils.data import Dataset

# ---------------------------------------------------------------------------
# Task constants — the task's own vocabulary, declared once
# ---------------------------------------------------------------------------

#: Registry identity of this task's data path (opaque to the framework).
QUICKSTART_TASK_ID = "quickstart_tabular"

#: Deterministic generator seed. Changing it changes the dataset identity;
#: `declared/data_manifest.json` pins the per-shard content hashes it yields.
GENERATOR_SEED = 20260824

SHARD_COUNT = 4
ROWS_PER_SHARD = 64
FEATURE_DIM = 4
CLASS_COUNT = 2
#: Fraction of labels flipped (deterministically) after the rule is applied,
#: so a perfect classifier is impossible and accuracy has honest headroom.
LABEL_FLIP_FRACTION = 0.03

#: Role split, by shard. The task owns this; the framework never learns it.
TRAIN_SHARDS: tuple[int, ...] = (0, 1)
VALIDATION_SHARD = 2
FINAL_EVAL_SHARD = 3

#: The scope payload's self-identifying kind (PR-12bc B8 rows-scope codec).
SCOPE_KIND = "quickstart_rows"

_SHARD_TEMPLATE = "shard_{index:04d}.csv"
_CSV_HEADER = ("sample_id", "x0", "x1", "x2", "x3", "label")
_FLOAT_FORMAT = "{:.8f}"


def shard_filename(shard: int) -> str:
    """Canonical CSV filename for one shard."""
    return _SHARD_TEMPLATE.format(index=shard)


def _deliverable_name(*, model_type: str, run_name: str, exp_id: str) -> str:
    """The task's one naming authority, shared by both public call shapes."""
    from execute_tools.deliverable_spec import resolve_deliverable_naming

    return resolve_deliverable_naming().name(
        model_type=model_type,
        run_name=run_name,
        exp_id=exp_id,
        input_identity=0,
    )


def deliverable_name(request: DeliverableWriteRequest | EvaluationReadRequest) -> str:
    """Module-level naming adapter consumed by generic inference reporting."""
    return _deliverable_name(
        model_type=request.model_type,
        run_name=request.run_name,
        exp_id=request.exp_id,
    )


# ---------------------------------------------------------------------------
# Seeded generator — the dataset IS this function plus the seed
# ---------------------------------------------------------------------------


def generate_shard(shard: int) -> tuple[list[str], np.ndarray, np.ndarray]:
    """One shard of the synthetic dataset, deterministically.

    Rule: ``label = 1  iff  x0*x1 + sin(pi*x2) > x3`` over features drawn
    Uniform(-1, 1), then :data:`LABEL_FLIP_FRACTION` of labels are flipped by
    the same seeded stream. The per-shard stream is ``default_rng(seed=
    (GENERATOR_SEED, shard))`` so shards are independent and individually
    reproducible.

    Returns:
        ``(sample_ids, features float32 [ROWS_PER_SHARD, FEATURE_DIM],
        labels int64 [ROWS_PER_SHARD])``.

    Raises:
        ValueError: ``shard`` outside ``[0, SHARD_COUNT)``.
    """
    if not 0 <= shard < SHARD_COUNT:
        raise ValueError(f"shard must be in [0, {SHARD_COUNT}); got {shard}.")
    rng = np.random.default_rng((GENERATOR_SEED, shard))
    features = rng.uniform(-1.0, 1.0, size=(ROWS_PER_SHARD, FEATURE_DIM)).astype(np.float32)
    margin = features[:, 0] * features[:, 1] + np.sin(np.pi * features[:, 2]) - features[:, 3]
    labels = (margin > 0.0).astype(np.int64)
    flip_count = round(ROWS_PER_SHARD * LABEL_FLIP_FRACTION)
    if flip_count:
        flip_rows = rng.choice(ROWS_PER_SHARD, size=flip_count, replace=False)
        labels[flip_rows] = 1 - labels[flip_rows]
    sample_ids = [f"s{shard}r{row:03d}" for row in range(ROWS_PER_SHARD)]
    return sample_ids, features, labels


def render_shard_csv(shard: int) -> str:
    """The canonical CSV text for one shard (fixed float format ⇒ stable bytes)."""
    sample_ids, features, labels = generate_shard(shard)
    lines = [",".join(_CSV_HEADER)]
    for sample_id, row, label in zip(sample_ids, features, labels, strict=True):
        values = ",".join(_FLOAT_FORMAT.format(float(v)) for v in row)
        lines.append(f"{sample_id},{values},{int(label)}")
    return "\n".join(lines) + "\n"


def write_data_dir(data_dir: str | Path) -> dict[str, str]:
    """Write all shards under ``data_dir``; return ``{filename: sha256}``."""
    target = Path(data_dir)
    target.mkdir(parents=True, exist_ok=True)
    digests: dict[str, str] = {}
    for shard in range(SHARD_COUNT):
        text = render_shard_csv(shard)
        path = target / shard_filename(shard)
        path.write_text(text, encoding="utf-8")
        digests[path.name] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digests


# ---------------------------------------------------------------------------
# Scope vocabulary — rows-shaped, self-identifying (PR-12bc B8 codec)
# ---------------------------------------------------------------------------


class QuickstartScopeRow(BaseModel):
    """One evaluated unit: a (shard, row) identity plus its truth label.

    The label rides IN the scope because the scope is the run's ground-truth
    authority — the metric derives truth from it, exactly the pattern the
    Pets pack uses (truth never re-read from a second source).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sample_id: str
    shard: int
    row: int
    label: int


class QuickstartScope(BaseModel):
    """A tuple of rows. Serialized canonically; deserialized fail-closed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rows: tuple[QuickstartScopeRow, ...]


def _rows_for_shard(shard: int) -> list[QuickstartScopeRow]:
    sample_ids, _features, labels = generate_shard(shard)
    return [
        QuickstartScopeRow(sample_id=sample_id, shard=shard, row=row, label=int(label))
        for row, (sample_id, label) in enumerate(zip(sample_ids, labels, strict=True))
    ]


# ---------------------------------------------------------------------------
# The TaskDataPath implementation (+ optional TaskScopeCapability sibling)
# ---------------------------------------------------------------------------


class QuickstartTaskDataPath:
    """The four-method data-path contract for the quickstart task.

    Constructed by the composition authority from the manifest's seam-A
    ``config:`` mapping (PR-12d D1) — the shipped
    ``configs/task_composition/quickstart.yaml`` declares ``train_shards`` /
    ``eval_shard``, which are keys THIS constructor understands and the
    framework never learns. Every value also has a default, so the class
    stays no-argument constructible for direct use in tests and notebooks.
    """

    task_data_path_id: ClassVar[str] = QUICKSTART_TASK_ID

    def __init__(
        self,
        train_shards: Sequence[int] = TRAIN_SHARDS,
        eval_shard: int = VALIDATION_SHARD,
    ) -> None:
        self._train_shards = tuple(int(s) for s in train_shards)
        self._eval_shard = int(eval_shard)
        #: The task's declared anchor representatives — the same fact
        #: `declared/dataset_profile.json` carries as `anchor_selection_files`
        #: (the pack test pins the two against each other).
        self._anchor_shards: tuple[int, ...] = (0,)

    # -- data materialization (the frozen four methods) ---------------------

    def _read_shard_rows(self, data_dir: str, shard: int) -> dict[str, tuple[list[float], int]]:
        """``{sample_id: (features, label)}`` from one shard CSV on disk."""
        path = os.path.join(data_dir, shard_filename(shard))
        if not os.path.isfile(path):
            raise ValidationScopeError(
                f"quickstart shard file not found at {path!r}. The run bundle "
                f"materializes {SHARD_COUNT} shard CSVs into --data_dir; "
                "re-run the materializer rather than pointing at another "
                "directory."
            )
        rows: dict[str, tuple[list[float], int]] = {}
        with open(path, encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for record in reader:
                features = [float(record[f"x{i}"]) for i in range(FEATURE_DIM)]
                rows[record["sample_id"]] = (features, int(record["label"]))
        return rows

    def _materialize(
        self, scope: object, data_dir: str, *, exact: bool
    ) -> tuple[np.ndarray, np.ndarray]:
        """Features + labels for ``scope``, verified against the CSVs.

        ``exact=True`` is the validation obligation: every requested row must
        exist and carry the scope's own label, else
        :class:`ValidationScopeError` — never padding, never truncation.
        """
        checked = self._require_scope(scope)
        if not checked.rows:
            raise ValidationScopeError(
                "quickstart scope requests zero rows — an empty materialization "
                "is a caller wiring defect, not a dataset."
            )
        by_shard: dict[int, dict[str, tuple[list[float], int]]] = {}
        features: list[list[float]] = []
        labels: list[int] = []
        for row in checked.rows:
            if row.shard not in by_shard:
                by_shard[row.shard] = self._read_shard_rows(data_dir, row.shard)
            found = by_shard[row.shard].get(row.sample_id)
            if found is None:
                message = (
                    f"quickstart scope row {row.sample_id!r} is missing from "
                    f"{shard_filename(row.shard)!r} under {data_dir!r} — the "
                    "declared scope did not materialize exactly."
                )
                raise ValidationScopeError(message) if exact else ValueError(message)
            row_features, row_label = found
            if row_label != row.label:
                message = (
                    f"quickstart scope row {row.sample_id!r} carries label "
                    f"{row.label} but {shard_filename(row.shard)!r} stores "
                    f"{row_label} — the data on disk is not the data the scope "
                    "was built from (regenerate the run bundle)."
                )
                raise ValidationScopeError(message) if exact else ValueError(message)
            features.append(row_features)
            labels.append(row.label)
        return (
            np.asarray(features, dtype=np.float32),
            np.asarray(labels, dtype=np.int64),
        )

    @staticmethod
    def _as_torch_dataset(features: np.ndarray, labels: np.ndarray) -> Dataset[Any]:
        """``(model_input float32 [FEATURE_DIM], target int64 scalar)`` pairs."""
        import torch
        from torch.utils.data import TensorDataset

        return TensorDataset(
            torch.from_numpy(features.copy()),
            torch.from_numpy(labels.copy()),
        )

    def training_dataset(self, scope: object, params: EpochSamplingParams) -> Dataset[Any]:
        """A torch dataset over ``scope``, honouring the per-epoch knobs.

        ``train_portion`` subsamples the scope's rows with the per-epoch seed
        (``epoch_seed=None`` draws non-deterministically, preserving the
        builder's contract); ``max_samples`` is an absolute ceiling applied
        after the draw.
        """
        checked = self._require_scope(scope)
        rows = list(checked.rows)
        if params.train_portion is not None and params.train_portion < 1.0:
            keep = max(1, math.floor(len(rows) * params.train_portion))
            rng = np.random.default_rng(params.epoch_seed)
            chosen = sorted(rng.choice(len(rows), size=keep, replace=False).tolist())
            rows = [rows[i] for i in chosen]
        if params.max_samples is not None:
            rows = rows[: params.max_samples]
        subset = QuickstartScope(rows=tuple(rows))
        features, labels = self._materialize(subset, params.data_dir, exact=False)
        return self._as_torch_dataset(features, labels)

    def validation_dataset(self, scope: object, params: EvalMaterializationParams) -> Dataset[Any]:
        """EXACT materialization of the validation scope (fail-closed)."""
        features, labels = self._materialize(scope, params.data_dir, exact=True)
        return self._as_torch_dataset(features, labels)

    @staticmethod
    def deliverable_name(*, model_type: str, run_name: str, exp_id: str) -> str:
        """This task's single deliverable filename, via the naming authority.

        The manifest's declared ``deliverable:`` template is what actually
        names the file. This task has one artifact per experiment; its
        identity index is 0 (the landed PR-12d keyword ``input_identity`` —
        the pre-12d ``file_index`` compat fallback was removed by the pack's
        post-12d checklist, README §7 step 4).
        """
        return _deliverable_name(model_type=model_type, run_name=run_name, exp_id=exp_id)

    @staticmethod
    def _predicted_class_index(prediction: object) -> int:
        """The predicted class, from a caller's int or the model's raw logits.

        The generic inference unit hands back what the MODEL produced — a
        ``[2]`` logit tensor per sample — because it has no idea this task's
        deliverable is a class index. Turning logits into a label is task
        semantics, so it happens HERE (the PR-12d seam-C precedent,
        ``execute_tools/pets_data_path.py::_pets_class_index``). An
        already-decided int passes through.
        """
        import torch

        if isinstance(prediction, torch.Tensor) and prediction.ndim >= 1:
            return int(torch.argmax(prediction).item())
        return int(prediction)  # type: ignore[arg-type]

    def write_deliverable(self, outputs: Any, request: DeliverableWriteRequest) -> None:
        """Persist ``{sample_id: predicted_class}`` as ONE JSON deliverable.

        Two accepted shapes (seam C / B7 — pairing is TASK-OWNED):

        * ``request.task_scope`` set — the composed inference child's shape
          (`execute_tools/generic_inference.py`): ``outputs`` is the
          per-sample sequence IN SCOPE ROW ORDER, each element the model's
          ``[2]`` logit tensor or an already-decided class index. Pairing
          with ``sample_id`` happens here, strict on length — a mismatch
          means outputs and scope disagree about how many samples there
          were, and zipping to the shorter would mis-attribute every
          prediction after the first missing sample.
        * a ``{sample_id: class}`` mapping — the pre-paired component form
          (notebook §10); accepted with or without a scope, unchanged.

        Witnessed live 2026-08-25: the first composed chain run refused the
        child's positional list here (`error_inference`), because this codec
        predates the landed convention — the mapping-only requirement was a
        stale pack assumption, not the framework contract.

        Codec only: no scoring, no thresholds — the metric owns both.
        """
        if not isinstance(outputs, Mapping):
            if request.task_scope is None:
                raise ValueError(
                    f"quickstart deliverable outputs must be a mapping of "
                    f"sample_id -> predicted class when no task_scope is "
                    f"supplied; got {type(outputs).__name__}."
                )
            scope = self._require_scope(request.task_scope)
            sequence = list(outputs)
            if len(sequence) != len(scope.rows):
                raise ValueError(
                    f"quickstart deliverable received {len(sequence)} outputs "
                    f"for {len(scope.rows)} scope rows — refusing to mis-pair."
                )
            outputs = {
                row.sample_id: self._predicted_class_index(prediction)
                for row, prediction in zip(scope.rows, sequence, strict=True)
            }
        payload: dict[str, int] = {}
        for key, value in outputs.items():
            if not isinstance(key, str) or not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(
                    "quickstart deliverable outputs must map str sample_ids to "
                    f"int class indices; got {key!r} -> {value!r}."
                )
            if not 0 <= value < CLASS_COUNT:
                raise ValueError(
                    f"predicted class for {key!r} must be in [0, {CLASS_COUNT}); got {value}."
                )
            payload[key] = value
        name = self.deliverable_name(
            model_type=request.model_type,
            run_name=request.run_name,
            exp_id=request.exp_id,
        )
        os.makedirs(request.output_dir, exist_ok=True)
        target = os.path.join(request.output_dir, name)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, indent=2)

    def read_evaluation_payload(self, request: EvaluationReadRequest) -> object:
        """Decode the persisted deliverable back into ``{sample_id: class}``."""
        name = self.deliverable_name(
            model_type=request.model_type,
            run_name=request.run_name,
            exp_id=request.exp_id,
        )
        path = os.path.join(request.deliverable_dir, name)
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"quickstart deliverable not found at {path!r} — nothing was "
                "persisted for this experiment identity."
            )
        with open(path, encoding="utf-8") as handle:
            decoded = json.load(handle)
        if not isinstance(decoded, dict):
            raise ValueError(
                f"quickstart deliverable at {path!r} must decode to a JSON "
                f"object; got {type(decoded).__name__}."
            )
        return {str(key): int(value) for key, value in decoded.items()}

    def enumerate_output_artifacts(
        self, request: EvaluationReadRequest
    ) -> TaskOutputArtifactInventory:
        """List this attempt's exact JSON output, including partial writes."""
        name = self.deliverable_name(
            model_type=request.model_type,
            run_name=request.run_name,
            exp_id=request.exp_id,
        )
        path = Path(request.deliverable_dir) / name
        return TaskOutputArtifactInventory(
            run_name=request.run_name,
            exp_id=request.exp_id,
            model_type=request.model_type,
            relative_paths=(name,) if path.exists() or path.is_symlink() else (),
        )

    # -- optional TaskScopeCapability sibling -------------------------------

    def _require_scope(self, scope: object) -> QuickstartScope:
        if not isinstance(scope, QuickstartScope):
            received = type(scope)
            raise ValueError(
                f"quickstart received a scope of type {received.__name__} "
                f"(from module {received.__module__!r}); this instance only "
                f"understands the QuickstartScope defined by ITS OWN module "
                f"({QuickstartScope.__module__!r}). Build the scope through "
                "the SAME instance's build_training_scope / build_eval_scope / "
                "deserialize_scope. A same-named class from a second load of "
                "this plugin file is a different class — mixing loads is the "
                "usual cause."
            )
        return scope

    def _selected_training_shards(self, request: ScopeBuildRequest) -> tuple[int, ...]:
        if request.selection_strategy == "snapshot":
            return self._train_shards
        if request.selection_strategy == "anchors":
            return self._anchor_shards
        illegal = [s for s in request.target_partitions if s not in self._train_shards]
        if illegal:
            raise ValueError(
                f"target partitions {illegal} are not training shards "
                f"{list(self._train_shards)} — the validation/final shards must "
                "never leak into a training scope."
            )
        if not request.target_partitions:
            raise ValueError("selection_strategy='target' requires target_partitions.")
        return tuple(request.target_partitions)

    def _draw_rows(
        self, shards: Sequence[int], request: ScopeBuildRequest
    ) -> tuple[QuickstartScopeRow, ...]:
        if request.subset_ref is not None:
            raise ValueError(
                f"quickstart_tabular has no subset vocabulary; subset_ref must "
                f"be None, got {request.subset_ref!r}."
            )
        # task_parameters are OPAQUE per-attempt knobs; this task consumes
        # none and deliberately ignores unknown keys (the tuner always sends
        # {"seg_size": ...} — see the module docstring).
        rows: list[QuickstartScopeRow] = []
        rng = np.random.default_rng(request.seed)
        for shard in shards:
            shard_rows = _rows_for_shard(shard)
            keep = max(1, math.floor(len(shard_rows) * request.portion))
            if keep < len(shard_rows):
                chosen = sorted(rng.choice(len(shard_rows), size=keep, replace=False).tolist())
                shard_rows = [shard_rows[i] for i in chosen]
            rows.extend(shard_rows)
        if request.max_samples is not None:
            rows = rows[: request.max_samples]
        return tuple(rows)

    def build_training_scope(self, request: ScopeBuildRequest) -> object:
        """The training scope for one attempt: rows drawn from train shards."""
        return QuickstartScope(
            rows=self._draw_rows(self._selected_training_shards(request), request)
        )

    def build_eval_scope(self, request: ScopeBuildRequest) -> object:
        """The evaluation scope: the held-out eval shard (never a train shard).

        ``portion`` / ``seed`` / ``max_samples`` are honoured so a bounded
        round can evaluate on a subset; ``selection_strategy`` never moves the
        evaluation off the held-out shard.
        """
        return QuickstartScope(rows=self._draw_rows((self._eval_shard,), request))

    def serialize_scope(self, scope: object) -> str:
        """Canonical bytes: sorted keys, no whitespace — equal scopes, equal bytes."""
        checked = self._require_scope(scope)
        return json.dumps(
            {"kind": SCOPE_KIND, "rows": [row.model_dump() for row in checked.rows]},
            sort_keys=True,
            separators=(",", ":"),
        )

    def deserialize_scope(self, payload: str) -> object:
        """Fail-closed inverse (shared rows-scope codec, PR-12bc B8)."""
        return deserialize_rows_scope(payload, SCOPE_KIND, QuickstartScopeRow, QuickstartScope)


# ---------------------------------------------------------------------------
# Run-bundle materializer — regenerates the task's DATA (nothing else)
# ---------------------------------------------------------------------------
# Until PR-12d landed, this also generated `task_config.yaml` and two
# composition manifests, because governance guard (a) forbade committing a
# YAML with top-level `task_description`/`forward_contract` keys under
# `examples/`. The landed guard exempts manifest-BOUND task configs, so the
# task config now lives at `declared/task_config.yaml` and THE manifest ships
# at `configs/task_composition/quickstart.yaml` (README §7 steps 2-3).


def materialize_run_bundle(pack_dir: str | Path, out_dir: str | Path) -> dict[str, str]:
    """Regenerate the quickstart DATA under ``out_dir`` (sha-verified).

    Contents::

        out_dir/
        └── data/shard_0000.csv … shard_0003.csv

    The shard bytes are verified against ``declared/data_manifest.json`` so a
    drifted generator fails HERE, not downstream. Point the run's
    ``--data_dir`` at the returned ``data_dir``; the composition manifest is
    the SHIPPED ``configs/task_composition/quickstart.yaml`` and needs no
    generation.

    Returns:
        ``{"data_dir": absolute path}``.

    Raises:
        ValueError: the pack layout is incomplete, or a regenerated shard's
            sha256 disagrees with the committed manifest.
    """
    pack = Path(pack_dir).resolve()
    declared = pack / "declared"
    for required in (
        declared / "dataset_profile.json",
        declared / "metric_accuracy.json",
        declared / "task_config.yaml",
        declared / "data_manifest.json",
        pack / "plugins" / "_quickstart_task.py",
        pack / "plugins" / "_quickstart_metrics.py",
    ):
        if not required.is_file():
            raise ValueError(f"quickstart pack file missing: {required}")

    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    data_dir = out / "data"
    digests = write_data_dir(data_dir)

    committed = json.loads((declared / "data_manifest.json").read_text(encoding="utf-8"))
    expected = committed.get("sha256", {})
    if digests != expected:
        raise ValueError(
            "regenerated quickstart shards disagree with declared/"
            f"data_manifest.json.\n  expected: {expected}\n  generated: {digests}\n"
            "The generator and the committed pins must move together."
        )
    return {"data_dir": str(data_dir)}
