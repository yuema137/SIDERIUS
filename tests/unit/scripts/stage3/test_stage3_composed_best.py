"""Witnesses for the Stage-3 Composed Best writer (contract §1, §3, §4).

Synthetic band-chain workspaces are built through the REAL authorities the
writer consumes — ``materialize_effective_config`` (the pinned effective
Health config), ``write_run_invariants`` (the lock), and
``publish_iteration_manifest`` (the self-digested write-once manifest) — so
these tests certify the production consumption path, not a hand-rolled
parallel format. Only ``score_vector`` is stubbed, at the shared module's
boundary (``stage3_common.score_vector``).

Each test names the defect only it can catch:

* end-to-end: trial/invalid records silently winning the band; the pooled
  set scored more than once; provenance not matching the pooled bytes;
* direction: a ``max()`` re-derivation instead of ``MetricOrder``;
* frozen role identity: ``is_trial`` read as a value instead of the
  contract's absence-of-key rule;
* the no-band-scalar witness (coordinator addendum): a band-level scalar
  appearing anywhere in the provenance JSON or the stdout log;
* verification: consuming a run output whose bytes moved after publication;
* layout: pooling from a workspace whose locked scope is not the band.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

import scripts.stage3.stage3_common as stage3_common
from core.iteration_manifest import publish_iteration_manifest, sha256_file
from core.run_invariants import RunInvariants, write_run_invariants
from execute_tools.dataset_config import NUM_FILES, resolve_dataset_profile
from execute_tools.deliverable_spec import DeliverableNaming
from execute_tools.evaluation_metric import derive_tidmad_metric_spec
from execute_tools.health_checks.candidate_eligibility import resolve_scientific_gate_ids
from execute_tools.health_checks.config import materialize_effective_config
from scripts.stage3.stage3_composed_best import (
    BAND_LABELS,
    Stage3ComposedBestError,
    band_file_indices,
    run,
    select_band_winner,
)

NAMING = DeliverableNaming()
ARM = "gold"
#: A FULL production-shaped 09a stamp (post-gate-ruling: composed_best
#: validates the whole MetricSpec, not id+direction alone). Tests play the
#: STAMPING side here; a direction override simulates a different task's
#: declaration.
FULL_SPEC = derive_tidmad_metric_spec(resolve_dataset_profile())
METRIC = {"id": FULL_SPEC.id, "direction": FULL_SPEC.direction}
FULL_STAMP = FULL_SPEC.model_dump()


class _ScoreVectorStub:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.vector = [float(index) * 0.01 for index in range(NUM_FILES)]
        self.scalar = -2.5

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return list(self.vector), self.scalar


@pytest.fixture
def score_stub(monkeypatch) -> _ScoreVectorStub:
    stub = _ScoreVectorStub()
    monkeypatch.setattr(stage3_common, "score_vector", stub)
    return stub


def _passing_gates(required: frozenset[str]) -> list[dict]:
    return [
        {"gate_name": gate_id, "execution_status": "passed", "check_passed": True}
        for gate_id in sorted(required)
    ]


def _failing_gates(required: frozenset[str]) -> list[dict]:
    return [
        {"gate_name": gate_id, "execution_status": "passed", "check_passed": False}
        for gate_id in sorted(required)
    ]


def _record(
    exp_id: str,
    score: float,
    gates: list[dict],
    *,
    model_type: str = "wavenet",
    trial: bool = False,
    extra: dict | None = None,
) -> dict:
    record: dict = {
        "status": "success",
        "exp_id": exp_id,
        "model_type": model_type,
        "denoising_score": score,
        "health_gate_results": gates,
    }
    if trial:
        record["is_trial"] = True
        record["trial_portion"] = 0.1
    if extra:
        record.update(extra)
    return record


def _make_band_workspace(
    root: Path,
    band: str,
    iterations: list[dict],
    *,
    arm: str = ARM,
    lock_scope: list[int] | None = None,
) -> tuple[Path, frozenset[str]]:
    """One synthetic Stage-1 band chain workspace, built by the real authorities.

    ``iterations``: per-iteration specs — ``model_type``, ``records`` (a
    callable ``required_gate_ids -> list[record]``), ``deliverables``
    (``{exp_id: [file indices]}``), optional ``direction``.
    """
    indices = band_file_indices(band)
    workspace = root / f"{arm}_band{band}"
    workspace.mkdir(parents=True)
    _, config_sha = materialize_effective_config(
        None, indices, str(workspace), resolved_scope=indices
    )
    required = resolve_scientific_gate_ids(str(workspace / "health_checks_effective.yaml"))
    assert required, "fixture: scientific gate roles must resolve from the effective config"
    write_run_invariants(
        str(workspace),
        RunInvariants(
            resolved_data_scope=list(lock_scope) if lock_scope is not None else indices,
            health_gate_enabled=True,
            health_config_sha256=config_sha,
            experiment_arm=arm,
        ),
    )
    for number, spec in enumerate(iterations, start=1):
        run_name = f"iter_{number:03d}"
        iter_dir = workspace / run_name
        sub = iter_dir / "iteration_001" / spec["model_type"]
        sub.mkdir(parents=True)
        output = {
            "run_name": run_name,
            "model_type": spec["model_type"],
            "experiment_arm": arm,
            "metric_spec": {**FULL_STAMP, "direction": spec.get("direction", "higher")},
            "all_records": spec["records"](required),
        }
        if spec.get("omit_metric_spec"):
            # The pre-09a output shape (gate-ruling regression fixtures).
            del output["metric_spec"]
        output_path = sub / f"run_output_{run_name}.json"
        output_path.write_text(json.dumps(output), encoding="utf-8")
        for exp_id, deliverable_indices in spec.get("deliverables", {}).items():
            for index in deliverable_indices:
                name = NAMING.name(
                    model_type=spec["model_type"],
                    run_name=run_name,
                    exp_id=exp_id,
                    input_identity=index,
                )
                (sub / name).write_bytes(_payload(band, exp_id, index))
        publish_iteration_manifest(
            str(iter_dir),
            {
                "status": "completed",
                "iteration_dir": str(iter_dir),
                "output_path": str(output_path),
                "model_name": spec["model_type"],
                "experiment_arm": arm,
                "run_output_sha256": sha256_file(str(output_path)),
            },
        )
    return workspace, required


def _payload(band: str, exp_id: str, index: int) -> bytes:
    return f"h5:{band}:{exp_id}:{index}".encode()


def _simple_iteration(exp_id: str, score: float, band: str, *, model_type: str = "wavenet") -> dict:
    return {
        "model_type": model_type,
        "records": lambda required: [_record(exp_id, score, _passing_gates(required))],
        "deliverables": {exp_id: band_file_indices(band)},
    }


def _make_campaign(root: Path) -> None:
    """Four band workspaces; band 0-3 exercises the §1 selection table."""
    band = BAND_LABELS[0]

    def band0_iter1(required: frozenset[str]) -> list[dict]:
        return [_record("expA", -3.0, _passing_gates(required))]

    def band0_iter2(required: frozenset[str]) -> list[dict]:
        return [
            # A trial record with the BEST score — excluded by role.
            _record("expTrial", -1.0, _passing_gates(required), trial=True),
            # A formal record with a better score but a FAILED blocking
            # gate — excluded by the ONE eligibility authority.
            _record("expInvalid", -0.5, _failing_gates(required)),
            # The cumulative best HealthGate-valid formal winner.
            _record("expB", -2.5, _passing_gates(required)),
        ]

    _make_band_workspace(
        root,
        band,
        [
            {
                "model_type": "wavenet",
                "records": band0_iter1,
                "deliverables": {"expA": band_file_indices(band)},
            },
            {
                "model_type": "wavenet",
                "records": band0_iter2,
                "deliverables": {
                    "expB": band_file_indices(band),
                    "expInvalid": band_file_indices(band),
                },
            },
        ],
    )
    for other in BAND_LABELS[1:]:
        _make_band_workspace(root, other, [_simple_iteration(f"exp_{other}", -4.0, other)])


def test_composed_best_end_to_end_selection_pooling_one_call(tmp_path, score_stub):
    """The §1 table selects the cumulative best VALID FORMAL record per band,
    the pooled set is the winners' source-band files, the scorer runs ONCE,
    and the provenance pins the exact pooled bytes."""
    _make_campaign(tmp_path)

    provenance_path = run(str(tmp_path), ARM)

    provenance = json.loads(Path(provenance_path).read_text())
    winners = {block["band"]: block for block in provenance["winners"]}
    assert set(winners) == set(BAND_LABELS)
    assert winners["0-3"]["exp_id"] == "expB", (
        "band 0-3 winner must be the cumulative best HealthGate-valid FORMAL "
        "record — not the better trial, not the better invalid formal"
    )
    assert winners["0-3"]["iteration"] == "iter_002"
    assert winners["0-3"]["run_name"] == "iter_002"
    assert winners["0-3"]["experiment_arm"] == ARM

    # ONE scoring call over the full pooled 0..19 set.
    assert len(score_stub.calls) == 1
    assert set(score_stub.calls[0]["sample_set"]) == set(range(NUM_FILES))
    assert provenance["denoising_score"] == score_stub.scalar
    assert provenance["file_vector"] == score_stub.vector
    assert provenance["metric"] == METRIC

    # The pooled input is 20 symlinks; each band contributed ITS files only.
    pooled = os.path.join(str(tmp_path), "stage3", "composed_best", ARM, "pooled_input")
    links = sorted(os.listdir(pooled))
    assert len(links) == NUM_FILES
    assert all(os.path.islink(os.path.join(pooled, link)) for link in links)

    # Provenance sha256s pin the exact source bytes for every pooled file.
    for band in BAND_LABELS:
        block = winners[band]
        assert [entry["file_index"] for entry in block["deliverables"]] == band_file_indices(band)
        for entry in block["deliverables"]:
            expected = hashlib.sha256(
                _payload(band, block["exp_id"], entry["file_index"])
            ).hexdigest()
            assert entry["sha256"] == expected
            assert os.path.isfile(entry["source_path"])
    assert provenance["s_max"] == stage3_common.EXPECTED_S_MAX
    assert provenance["anchor_map_sha256"] == sha256_file(provenance["anchor_map_path"])


def test_no_band_scalar_in_provenance_or_stdout(tmp_path, score_stub, capsys):
    """Coordinator addendum witness: no band-level scalar field exists in the
    provenance JSON or the log — per-band information appears only as
    identity fields and per-FILE vector entries.

    How it fails: give any winner block a score-like field (e.g. copy the
    winning record's own band-scoped ``denoising_score`` into provenance),
    add any ``band_*``/``*_band`` scalar key, or print a band aggregate."""
    _make_campaign(tmp_path)
    provenance = json.loads(Path(run(str(tmp_path), ARM)).read_text())

    float_leaves: list[tuple[str, float]] = []
    all_keys: list[str] = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                all_keys.append(key)
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for position, value in enumerate(node):
                walk(value, f"{path}[{position}]")
        elif isinstance(node, float):
            float_leaves.append((path, node))

    walk(provenance, "$")

    allowed_prefixes = ("$.s_max", "$.denoising_score", "$.file_vector[")
    for path, _ in float_leaves:
        assert path.startswith(allowed_prefixes), (
            f"unexpected float at {path} — the only scalars in Composed Best output "
            f"are s_max, the single denoising_score, and per-FILE vector entries"
        )
    # No winner block carries any float (identity fields are strings/ints).
    winner_floats = [path for path, _ in float_leaves if path.startswith("$.winners")]
    assert winner_floats == []
    # No band-scalar key names anywhere.
    for key in all_keys:
        lowered = key.lower()
        assert not (
            "band" in lowered and any(word in lowered for word in ("score", "scalar", "mean"))
        ), f"band-scalar-shaped key {key!r} in provenance"

    stdout = capsys.readouterr().out
    assert "Composed Best Golden score (denoising_score): -2.5" in stdout
    for line in stdout.splitlines():
        lowered = line.lower()
        assert not ("band" in lowered and ("score" in lowered or "mean" in lowered)), (
            f"stdout prints a band-level aggregate: {line!r}"
        )


def test_direction_lower_selects_smaller_score(tmp_path):
    """The winner comes from ``MetricOrder`` over the stamped direction —
    under ``lower``, the SMALLER score wins. A ``max()``/higher-is-better
    re-derivation fails here (contract §1: never assume direction)."""
    band = BAND_LABELS[0]

    def records(required: frozenset[str]) -> list[dict]:
        return [
            _record("expHigh", -2.5, _passing_gates(required)),
            _record("expLow", -3.0, _passing_gates(required)),
        ]

    _make_band_workspace(
        tmp_path,
        band,
        [
            {
                "model_type": "wavenet",
                "direction": "lower",
                "records": records,
                "deliverables": {
                    "expHigh": band_file_indices(band),
                    "expLow": band_file_indices(band),
                },
            }
        ],
    )

    winner = select_band_winner(str(tmp_path), ARM, band)
    assert winner.exp_id == "expLow"


@pytest.mark.parametrize(
    "extra, message_match",
    [
        ({"is_trial": "yes"}, "is_trial"),
        ({"trial_portion": 0.1}, "trial_portion"),
    ],
    ids=["is_trial_non_bool", "trial_portion_value_without_is_trial"],
)
def test_anomalous_role_shapes_are_refused(tmp_path, extra, message_match):
    """Role identity (Q-S3-3 corrected): FORMAL == ``is_trial`` absent OR
    ``False`` — persisted ``all_records`` MATERIALIZE the default ``False``
    (``HyperparamTuningOutput.all_records: list[ExperimentRecord]`` +
    ``model_dump()``), so the pre-Q-S3-3 literal absence test refused every
    real formal record. What production genuinely never writes, still
    REFUSED loudly: a non-bool ``is_trial``, or a non-``None``
    ``trial_portion`` (trial-only value, #316 B2) on a formal-shaped
    record."""
    band = BAND_LABELS[0]

    def records(required: frozenset[str]) -> list[dict]:
        return [_record("expAnomaly", -2.0, _passing_gates(required), extra=extra)]

    _make_band_workspace(
        tmp_path,
        band,
        [
            {
                "model_type": "wavenet",
                "records": records,
                "deliverables": {"expAnomaly": band_file_indices(band)},
            }
        ],
    )

    with pytest.raises(Stage3ComposedBestError, match=message_match):
        select_band_winner(str(tmp_path), ARM, band)


def test_qs33_persisted_formal_shape_is_selectable(tmp_path):
    """Q-S3-3 regression (2026-08-26): the shape Stage-3 actually READS.

    ``HyperparamTuningOutput.all_records: list[ExperimentRecord]``
    re-validates builder dicts into models, and ``model_dump()``
    (``records.py:1048``) MATERIALIZES ``is_trial: False`` and
    ``trial_portion: None`` onto every persisted FORMAL record. This test
    builds the record THROUGH the production schema — never a hand-shaped
    dict — and requires selection to succeed on it. Fails when: role
    identity regresses to the contract's literal absence test, which
    refused every real formal record (found by the adversarial validator,
    confirmed empirically against the schema)."""
    from agent.schemas.hyperparam_tuning import ExperimentRecord

    band = BAND_LABELS[0]

    def records(required: frozenset[str]) -> list[dict]:
        gates = [
            {
                **gate,
                "would_invalidate_under_production_policy": False,
                "resolved_action": "continue",
            }
            for gate in _passing_gates(required)
        ]
        base = _record("expPersisted", -2.0, gates)
        base.update({"timestamp": "2026-08-26T12:00:00+00:00", "params": {}})
        dumped = ExperimentRecord.model_validate(base).model_dump(mode="json")
        # The materialized persisted shape — what the contract's literal
        # absence test misreads as anomalous:
        assert dumped.get("is_trial") is False
        assert "trial_portion" in dumped and dumped["trial_portion"] is None
        return [dumped]

    _make_band_workspace(
        tmp_path,
        band,
        [
            {
                "model_type": "wavenet",
                "records": records,
                "deliverables": {"expPersisted": band_file_indices(band)},
            }
        ],
    )
    winner = select_band_winner(str(tmp_path), ARM, band)
    assert winner.exp_id == "expPersisted"


def test_gate_ruling_absent_metric_spec_is_a_named_refusal(tmp_path):
    """Step-09a gate-ruling negative 1 (2026-08-26): spec ABSENT => refusal.

    A pre-09a-shaped output (no ``metric_spec`` stamp) must be a NAMED
    refusal, never a re-derivation and never a default. Fails when: the
    consumer regains a fallback derivation (the consumer-re-derivation
    class the local gate caught) — selection would then succeed here."""
    band = BAND_LABELS[0]
    _make_band_workspace(
        tmp_path,
        band,
        [{**_simple_iteration("expA", -3.0, band), "omit_metric_spec": True}],
    )
    with pytest.raises(Stage3ComposedBestError, match="no metric_spec stamp"):
        select_band_winner(str(tmp_path), ARM, band)


def test_gate_ruling_divergent_band_specs_are_a_named_refusal(tmp_path):
    """Step-09a gate-ruling negative 2 (2026-08-26): winners DISAGREE => refusal.

    The four band winners' stamped specs are reconciled through the ONE
    authority (``reconcile_metric_specs``); a band stamped with the same id
    but the OPPOSITE direction — the most dangerous disagreement, nothing
    about the identity looks wrong while the ranking inverts — must refuse
    with both sources named. Fails when: cross-band agreement regresses to
    a hand-rolled equality that a schema change desynchronizes, or the
    reconciliation is dropped and the first band's spec silently wins."""
    for band in BAND_LABELS:
        iteration = _simple_iteration(f"exp_{band}", -4.0, band)
        if band == BAND_LABELS[1]:
            iteration["direction"] = "lower"
        _make_band_workspace(tmp_path, band, [iteration])
    with pytest.raises(Stage3ComposedBestError, match="diverges across bands"):
        run(str(tmp_path), ARM)


def test_tampered_run_output_is_refused(tmp_path):
    """The writer VERIFIES the manifest's run-output digest before consuming:
    bytes moved after publication are a refusal, not an input. Fails if the
    verification call is dropped."""
    band = BAND_LABELS[0]
    workspace, _ = _make_band_workspace(tmp_path, band, [_simple_iteration("expA", -3.0, band)])
    output_path = workspace / "iter_001" / "iteration_001" / "wavenet" / "run_output_iter_001.json"
    with open(output_path, "a", encoding="utf-8") as handle:
        handle.write("\n")

    with pytest.raises(Stage3ComposedBestError, match=r"hash|sha|digest|match"):
        select_band_winner(str(tmp_path), ARM, band)


def test_scope_mismatch_refuses_the_workspace(tmp_path):
    """A workspace whose locked ``resolved_data_scope`` is not the band's
    file set is not the band's workspace — pooling from it is refused."""
    band = BAND_LABELS[0]
    _make_band_workspace(
        tmp_path,
        band,
        [_simple_iteration("expA", -3.0, band)],
        lock_scope=list(range(NUM_FILES)),
    )

    with pytest.raises(Stage3ComposedBestError, match="resolved_data_scope"):
        select_band_winner(str(tmp_path), ARM, band)


def test_missing_winner_deliverable_is_refused(tmp_path):
    """A winner whose source-band deliverable set is incomplete on disk is a
    refusal citing the Stage-1 retention clause — never a silent partial
    pool."""
    band = BAND_LABELS[0]
    indices = band_file_indices(band)

    def records(required: frozenset[str]) -> list[dict]:
        return [_record("expA", -3.0, _passing_gates(required))]

    _make_band_workspace(
        tmp_path,
        band,
        [
            {
                "model_type": "wavenet",
                "records": records,
                "deliverables": {"expA": indices[:-1]},  # one band file missing
            }
        ],
    )

    with pytest.raises(Stage3ComposedBestError, match="retention"):
        select_band_winner(str(tmp_path), ARM, band)
