# tests/unit/agent/schemas/test_health_feedback.py
"""CB1 unit suite for agent/schemas/health_feedback.py.

Design: docs/design/v19_priorities/pr3_healthgate_feedback.md §3.2-§3.4,
§3.8, §7.1. Gate-result fixtures mirror the REAL persisted V17 payload
shape (exploration_loss_v17_20260718, design §2.5) — threshold.metric
self-describes the check, aggregate_statistics carries the worst-case
stats — rather than an invented schema.
"""

import pytest
from pydantic import ValidationError

from agent.schemas.health_feedback import (
    PRE_GATE_ERROR_STATUSES,
    SOURCE_EXP_IDS_BOUND,
    CollapseFingerprint,
    CollapseFingerprintHistoryEntry,
    FingerprintOccurrence,
    HealthFeedbackRetentionPolicy,
    bucket_value,
    build_collapse_fingerprint,
    build_gate_outcomes,
    classify_round_provenance,
    merge_fingerprint_history,
    select_primary_gate_outcome,
)
from agent.schemas.hyperparam_tuning import ExperimentRecord

# ---------------------------------------------------------------------------
# Fixtures — real V17 persisted shapes (design §2.5)
# ---------------------------------------------------------------------------


def _gate(
    name="output_diversity_blocking",
    metric="n_unique_int8_values",
    unit="count",
    worst_stat="minimum",
    worst=1.0,
    operator=">",
    *,
    execution_status="failed",
    check_passed=False,
    would_invalidate=True,
    resolved_action="invalidate_round",
    failure_reason="output_diversity: n_unique_int8_values=1 <= 25",
):
    """One PersistedHealthGateResult dict in the real V17 shape."""
    agg = {"minimum": worst, "maximum": worst, "mean": worst, "count": 3}
    if worst_stat == "maximum":
        agg["minimum"] = 0.0
    return {
        "gate_name": name,
        "execution_status": execution_status,
        "check_passed": check_passed,
        "would_invalidate_under_production_policy": would_invalidate,
        "resolved_action": resolved_action,
        "failure_reason": failure_reason,
        # Step 10 / P4: the operator is now LOAD-BEARING — the worst-case
        # direction is derived from it instead of from a per-metric-name map.
        # It must match the check this fixture claims to reproduce, which is
        # what the real persisted row carries.
        "threshold": {"metric": metric, "operator": operator, "value": 25, "unit": unit},
        "aggregation": {},
        "metrics": {"aggregate_statistics": agg},
        "gate_runtime_seconds": 0.5,
    }


def _amplitude_gate(dominant=0.9612, **kw):
    return _gate(
        name="amplitude_collapse_blocking",
        metric="dominant_mode_fraction",
        unit="fraction",
        worst_stat="maximum",
        worst=dominant,
        operator="<=",  # amplitude_collapse is a CEILING; the real row says so
        failure_reason=f"amplitude_collapse: dominant_mode_fraction={dominant}",
        **kw,
    )


def _record(**overrides):
    """Minimal executed-success record dict (raw-JSON authoring form)."""
    base = {
        "exp_id": "m_iter_001_001",
        "status": "success",
        "model_type": "m",
        "timestamp": "2026-07-29 00:00:00",
        "params": {},
    }
    base.update(overrides)
    return base


def _fp(sig="s1", check="output_diversity_blocking", metrics=None, hr="collapse"):
    return CollapseFingerprint(
        check_name=check,
        signature=sig,
        metrics=metrics or {"n_unique_int8_values": 1},
        human_readable=hr,
    )


POLICY = HealthFeedbackRetentionPolicy()  # documented defaults: window 3, max 8


# ---------------------------------------------------------------------------
# Primary-fingerprint selection rule (§3.3 — 6 cases)
# ---------------------------------------------------------------------------


class TestPrimarySelection:
    def test_action_consistency_beats_config_order(self):
        # First-in-order gate resolved to a DIFFERENT action than the round;
        # the second matches the round's blocking verdict and must win.
        g1 = _gate(
            name="output_std_blocking",
            metric="output_std_mv",
            unit="mV",
            resolved_action="continue",
            would_invalidate=False,
        )
        g2 = _amplitude_gate(resolved_action="invalidate_round")
        picked = select_primary_gate_outcome([g1, g2], "invalidate_round")
        assert picked["gate_name"] == "amplitude_collapse_blocking"

    def test_counterfactual_narrows(self):
        g1 = _gate(
            name="output_std_blocking", metric="output_std_mv", unit="mV", would_invalidate=False
        )
        g2 = _amplitude_gate(would_invalidate=True)
        picked = select_primary_gate_outcome([g1, g2], None)
        assert picked["gate_name"] == "amplitude_collapse_blocking"

    def test_severity_narrows(self):
        # Live vocabulary (post-F-SCANC-1): invalidate_round (severity 1)
        # outranks continue (severity 0) among failed gates.
        g1 = _gate(resolved_action="continue")
        g2 = _amplitude_gate(resolved_action="invalidate_round")
        picked = select_primary_gate_outcome([g1, g2], None)
        assert picked["gate_name"] == "amplitude_collapse_blocking"

    def test_a_historical_retired_action_ranks_below_any_live_action(self):
        """F-SCANC-1 reader tolerance: a persisted record from before the
        retirement can carry "skip_iter" (a custom pre-v1 config); the
        severity step must DEGRADE it below every live action instead of
        raising — this is what keeps an old workspace's feedback restore
        readable. Fails when: `_sev`'s except-degrade is removed, or the
        retired string is mapped back onto a live severity."""
        g1 = _gate(resolved_action="invalidate_round")
        g2 = _amplitude_gate(resolved_action="skip_iter")
        picked = select_primary_gate_outcome([g1, g2], None)
        assert picked["gate_name"] == "output_diversity_blocking"

    def test_config_order_final_tiebreak(self):
        g1 = _gate()
        g2 = _amplitude_gate()  # identical action/counterfactual/severity
        picked = select_primary_gate_outcome([g1, g2], "invalidate_round")
        assert picked["gate_name"] == "output_diversity_blocking"

    def test_missing_counterfactual_falls_through(self):
        # Legacy-shaped results without the counterfactual field: step 2
        # eliminates everyone and must be skipped, not return None.
        g1 = _gate()
        g2 = _amplitude_gate()
        for g in (g1, g2):
            g["would_invalidate_under_production_policy"] = None
        picked = select_primary_gate_outcome([g1, g2], "invalidate_round")
        assert picked["gate_name"] == "output_diversity_blocking"

    def test_healthy_round_returns_none(self):
        g = _gate(
            execution_status="passed",
            check_passed=True,
            would_invalidate=False,
            resolved_action="continue",
            failure_reason=None,
        )
        assert select_primary_gate_outcome([g], None) is None


# ---------------------------------------------------------------------------
# Fingerprint construction: signature, bucketing, raw metrics (§3.3-§3.4)
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_signature_count_exact(self):
        fp = build_collapse_fingerprint([_gate(worst=1.0)], "invalidate_round")
        assert fp.signature == "output_diversity_blocking:n_unique_int8_values=1"
        assert fp.metrics == {"n_unique_int8_values": 1}  # raw, int-exact

    def test_signature_float_bucketed_two_sig_figs(self):
        a = build_collapse_fingerprint([_amplitude_gate(0.9612)], None)
        b = build_collapse_fingerprint([_amplitude_gate(0.9634)], None)
        # Same collapse mode after 2-sig-fig bucketing...
        assert (
            a.signature
            == b.signature
            == ("amplitude_collapse_blocking:dominant_mode_fraction=0.96")
        )
        # ...but the RAW values are preserved untouched.
        assert a.metrics["dominant_mode_fraction"] == 0.9612
        assert b.metrics["dominant_mode_fraction"] == 0.9634

    def test_recompute_signature_from_stored_raw(self):
        fp = build_collapse_fingerprint([_amplitude_gate(0.9612)], None)
        name, value = next(iter(fp.metrics.items()))
        assert f"{fp.check_name}:{name}={bucket_value(value, exact=False)}" == fp.signature


class TestADeclaredCountIsNotAValidatedCount:
    """A declared UNIT drove a stored VALUE, and nothing validated the value.

    ``_extract_discriminating_metrics`` rendered the worst observation as
    ``int(value)`` whenever ``threshold.unit`` was in ``_INTEGRAL_UNITS``, so a
    check declaring ``unit: count`` over a fractional metric stored 3.9 as 3 —
    in ``CollapseFingerprint.metrics``, whose own schema says it "stores RAW
    values (never bucketed) so signatures can be recomputed under a revised
    bucketing rule from stored artifacts alone". Truncation destroys precisely
    what that guarantee exists for.

    The unit is an unconstrained string on both of its sources —
    ``EvidenceUnit.literal`` (check-owned) and ``EvidenceUnit.config_key``
    (resolved from the task's own composed config, e.g. a task declaring
    ``value_scale.unit: count``) — so this is reachable by any task, in-tree or
    external, without touching framework code.

    Exactness now requires the declared cardinal unit AND a value that is one.

    ============================================  ==============================
    if this regresses                             which test reds
    ============================================  ==============================
    the raw store is truncated again              ``test_a_fractional_count_...``
    two fractional counts collapse into one       ``test_two_fractional_counts_``
    a genuine whole count stops rendering as int  ``test_a_whole_count_...``
    a non-finite scalar crashes the fingerprint   ``test_a_non_finite_...``
    ============================================  ==============================
    """

    METRIC = "n_unique_int8_values"

    def _count_gate(self, worst):
        return _gate(worst=worst, unit="count", metric=self.METRIC)

    def test_a_fractional_count_keeps_its_digits(self):
        fp = build_collapse_fingerprint([self._count_gate(3.9)], "invalidate_round")
        assert fp.metrics == {self.METRIC: 3.9}, (
            "the raw store was truncated to satisfy a declaration; 3.9 is not a count "
            "and the fix is to stop claiming it is, not to round it off"
        )

    def test_a_fractional_count_is_not_rendered_as_a_cardinal(self):
        """Exactness is a property of the value, not only of the declaration."""
        fp = build_collapse_fingerprint([self._count_gate(3.9)], "invalidate_round")
        assert fp.signature == f"output_diversity_blocking:{self.METRIC}=3.9"

    def test_two_fractional_counts_do_not_collide(self):
        """Under truncation both stored 3 and both signed `=3` — one collapse
        mode where there were two."""
        a = build_collapse_fingerprint([self._count_gate(3.1)], "invalidate_round")
        b = build_collapse_fingerprint([self._count_gate(3.9)], "invalidate_round")
        assert a.metrics != b.metrics
        assert a.signature != b.signature

    def test_a_whole_count_is_unchanged(self):
        """Byte-parity for every real count. ``aggregate_statistics`` publishes
        floats, so TIDMAD's counts arrive as ``1.0`` and must still persist as
        the int ``1`` — the shipped rendering."""
        fp = build_collapse_fingerprint([self._count_gate(1.0)], "invalidate_round")
        assert fp.metrics == {self.METRIC: 1}
        assert isinstance(fp.metrics[self.METRIC], int)
        assert fp.signature == f"output_diversity_blocking:{self.METRIC}=1"

    def test_a_non_finite_scalar_count_no_longer_crashes(self):
        """``int(float('nan'))`` raises. ``aggregate_statistics`` filters
        non-finite values; the SCALAR branch — added for task-owned checks with
        no per-file dimension — does not, so a task-owned count-declared check
        publishing NaN took the whole fingerprint build down with a
        ``ValueError`` from inside a schema helper."""
        gate = self._count_gate(1.0)
        gate["metrics"] = {self.METRIC: float("nan")}
        fp = build_collapse_fingerprint([gate], "invalidate_round")
        assert fp is not None
        assert fp.metrics[self.METRIC] != fp.metrics[self.METRIC]  # NaN, preserved raw

    def test_human_readable_never_in_equality(self):
        a = build_collapse_fingerprint([_gate(failure_reason="prose A")], None)
        b = build_collapse_fingerprint([_gate(failure_reason="prose B")], None)
        assert a.human_readable != b.human_readable
        assert a.signature == b.signature  # matching ignores prose

    def test_no_allowlisted_metric_means_no_fingerprint(self):
        # Mid-form result without aggregate_statistics: nothing is
        # invented from prose (design §3.3).
        g = _gate()
        g["metrics"] = {}
        assert build_collapse_fingerprint([g], "invalidate_round") is None

    def test_gate_outcomes_condense_all_results(self):
        healthy = _gate(
            name="output_std_blocking",
            metric="output_std_mv",
            unit="mV",
            worst=7.35,
            execution_status="passed",
            check_passed=True,
            would_invalidate=False,
            resolved_action="continue",
            failure_reason=None,
        )
        recording = {
            "gate_name": "pearson_dispersion_recording",
            "execution_status": "passed",
            "check_passed": True,
            "would_invalidate_under_production_policy": False,
            "resolved_action": "continue",
            "failure_reason": None,
            "threshold": None,
            "aggregation": {},
            "metrics": {
                "pearson_dispersion": 0.048,
                "pearson_mean": 0.01,
                "pearson_per_file": {"3": 0.1},
            },
            "gate_runtime_seconds": 0.1,
        }
        outs = build_gate_outcomes([_gate(), healthy, recording])
        assert [o.gate_name for o in outs] == [
            "output_diversity_blocking",
            "output_std_blocking",
            "pearson_dispersion_recording",
        ]
        assert outs[0].key_metrics == {"n_unique_int8_values": 1}
        assert outs[1].key_metrics == {"output_std_mv": 7.35}
        # Recording allowlist: scalars in, per-file trees out (design §3.4).
        assert outs[2].key_metrics == {"pearson_dispersion": 0.048, "pearson_mean": 0.01}


# ---------------------------------------------------------------------------
# Provenance classification (§3.2 ladder; real-vintage shapes from §2.5)
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_evidence_present_wins_regardless_of_status(self):
        # Governing rule: persisted evidence is never discarded by a
        # status rule — even a (hypothetical) error record with results.
        rec = _record(status="error_scoring", health_gate_results=[_gate()])
        assert classify_round_provenance(rec) == "gated"

    def test_gates_disabled(self):
        rec = _record(health_gate_enabled=False)
        assert classify_round_provenance(rec) == "gates_disabled"

    def test_pre_gate_statuses_not_evaluated(self):
        for status in sorted(PRE_GATE_ERROR_STATUSES | {"skipped_time_risk"}):
            rec = _record(status=status)
            assert classify_round_provenance(rec) == "gate_not_evaluated", status

    def test_attempt_failure_not_evaluated(self):
        rec = _record(record_type="attempt_failure", status="error")
        assert classify_round_provenance(rec) == "gate_not_evaluated"

    def test_current_gated_empty_list_is_gated_not_legacy(self):
        # V17-era executed record: key PRESENT, list empty (design §2.5).
        # Emptiness alone is never the discriminator.
        rec = _record(status="success", health_gate_results=[])
        assert classify_round_provenance(rec) == "gated"

    def test_mid_vintage_round_fields_only(self):
        # Real pre-V17 shape: no health_gate_results key at all, but
        # commit-5b round fields present on a collapse record.
        rec = _record(
            status="failed_mode_collapse",
            gate_action="invalidate_round",
            failure_reason="[output_diversity_blocking] collapse",
        )
        assert classify_round_provenance(rec) == "round_fields_only"

    def test_legacy_executed_record(self):
        rec = _record(status="success")  # no gate keys of any kind
        assert classify_round_provenance(rec) == "legacy"

    def test_dict_and_model_paths_agree(self):
        # Both REAL production forms — the raw dict and the model
        # validated FROM that dict — classify identically (§2.5 signal).
        for raw in (
            _record(status="success"),
            _record(status="success", health_gate_results=[]),
            _record(status="skipped_oom_risk"),
        ):
            model = ExperimentRecord.model_validate({**raw, "params": {}})
            assert classify_round_provenance(raw) == classify_round_provenance(model), raw

    def test_round_trip_manufactures_presence_documented_hazard(self):
        # model_dump() emits defaulted fields, so re-validating its output
        # MANUFACTURES field presence (design §2.5 hazard). This test
        # pins the hazard so nobody "simplifies" classification to run
        # after a round-trip: a legacy record would silently become gated.
        raw = _record(status="success")  # genuine legacy
        model = ExperimentRecord.model_validate({**raw, "params": {}})
        assert classify_round_provenance(model) == "legacy"
        round_tripped = ExperimentRecord.model_validate(model.model_dump())
        assert classify_round_provenance(round_tripped) == "gated"  # the hazard


# ---------------------------------------------------------------------------
# Typed history entries + validation negatives (§3.8)
# ---------------------------------------------------------------------------


class TestHistoryEntryValidation:
    def test_bucket_count_zero_rejected(self):
        with pytest.raises(ValidationError):
            FingerprintOccurrence(iteration=1, count=0)

    def test_duplicate_iterations_rejected(self):
        with pytest.raises(ValidationError, match="ascending"):
            CollapseFingerprintHistoryEntry(
                signature="s",
                check_name="c",
                human_readable="h",
                occurrences=[
                    FingerprintOccurrence(iteration=2, count=1),
                    FingerprintOccurrence(iteration=2, count=1),
                ],
            )

    def test_descending_iterations_rejected(self):
        with pytest.raises(ValidationError, match="ascending"):
            CollapseFingerprintHistoryEntry(
                signature="s",
                check_name="c",
                human_readable="h",
                occurrences=[
                    FingerprintOccurrence(iteration=3, count=1),
                    FingerprintOccurrence(iteration=1, count=1),
                ],
            )

    def test_empty_signature_and_check_name_rejected(self):
        with pytest.raises(ValidationError):
            CollapseFingerprintHistoryEntry(signature="", check_name="c", human_readable="h")
        with pytest.raises(ValidationError):
            CollapseFingerprintHistoryEntry(signature="s", check_name="", human_readable="h")

    def test_policy_rejects_non_positive(self):
        for kw in (
            {"history_window_iterations": 0},
            {"history_window_iterations": -1},
            {"max_entries_per_model": 0},
            {"max_entries_per_model": -1},
        ):
            with pytest.raises(ValidationError):
                HealthFeedbackRetentionPolicy(**kw)

    def test_policy_defaults_are_documented_values(self):
        # Legacy/missing configuration resolves to the documented defaults.
        p = HealthFeedbackRetentionPolicy()
        assert p.history_window_iterations == 3
        assert p.max_entries_per_model == 8


# ---------------------------------------------------------------------------
# Windowed counts from occurrences (§3.8 — canonical operator example)
# ---------------------------------------------------------------------------


def _entry(sig="s1", occurrences=()):
    return CollapseFingerprintHistoryEntry(
        signature=sig,
        check_name="output_diversity_blocking",
        metrics={"n_unique_int8_values": 1},
        human_readable="collapse",
        occurrences=[FingerprintOccurrence(iteration=i, count=c) for i, c in occurrences],
    )


class TestWindowedCounts:
    def test_non_contiguous_canonical_example(self):
        # Occurrences at iterations 1, 2, 5; current=5, window=3 →
        # only the iteration-5 bucket is retained; windowed count is 1,
        # NOT the lifetime 3 (operator example, design §3.8).
        prev = {"m": [_entry(occurrences=[(1, 1), (2, 1), (5, 1)])]}
        merged = merge_fingerprint_history(prev, {}, 5, POLICY)
        [entry] = merged["m"]
        assert [(o.iteration, o.count) for o in entry.occurrences] == [(5, 1)]
        assert entry.windowed_count(POLICY.minimum_retained_iter(5)) == 1

    def test_exact_boundary_inclusive_total(self):
        # current=5, window=3 → minimum retained iteration is 3:
        # a bucket at 3 survives, a bucket at 2 is removed.
        prev = {"m": [_entry(occurrences=[(2, 4), (3, 2)])]}
        merged = merge_fingerprint_history(prev, {}, 5, POLICY)
        [entry] = merged["m"]
        assert [(o.iteration, o.count) for o in entry.occurrences] == [(3, 2)]

    def test_window_one_retains_only_current(self):
        policy = HealthFeedbackRetentionPolicy(history_window_iterations=1)
        prev = {"m": [_entry(occurrences=[(4, 2)])]}
        merged = merge_fingerprint_history(prev, {"m": [(_fp(), "e1")]}, 5, policy)
        [entry] = merged["m"]
        assert [(o.iteration, o.count) for o in entry.occurrences] == [(5, 1)]

    def test_longer_window_retains_more(self):
        policy = HealthFeedbackRetentionPolicy(history_window_iterations=5)
        prev = {"m": [_entry(occurrences=[(1, 1), (2, 1), (5, 1)])]}
        merged = merge_fingerprint_history(prev, {}, 5, policy)
        [entry] = merged["m"]
        assert [o.iteration for o in entry.occurrences] == [1, 2, 5]

    def test_entry_dropped_when_no_buckets_remain(self):
        prev = {"m": [_entry(occurrences=[(1, 3)])]}
        assert merge_fingerprint_history(prev, {}, 5, POLICY) == {}


# ---------------------------------------------------------------------------
# History merge: aggregation, isolation, ordering, trim, determinism (§3.8)
# ---------------------------------------------------------------------------


class TestHistoryMerge:
    def test_current_iteration_aggregates_into_one_bucket(self):
        fp = _fp()
        merged = merge_fingerprint_history({}, {"m": [(fp, "e1"), (fp, "e2")]}, 7, POLICY)
        [entry] = merged["m"]
        assert [(o.iteration, o.count) for o in entry.occurrences] == [(7, 2)]
        assert entry.occurrences[0].source_exp_ids == ["e1", "e2"]

    def test_model_isolation(self):
        # Same signature under two models never crosses keys.
        merged = merge_fingerprint_history(
            {"a": [_entry(occurrences=[(6, 1)])]}, {"b": [(_fp(), "e1")]}, 7, POLICY
        )
        assert set(merged) == {"a", "b"}
        assert merged["a"][0].occurrences[0].iteration == 6
        assert merged["b"][0].occurrences[0].iteration == 7

    def test_representative_observation_latest_wins(self):
        # Two same-signature observations in chronological order: entry
        # metrics/human_readable take the LATER raw values (§3.8 rule),
        # while the signature (bucketed) is unchanged.
        a = CollapseFingerprint(
            check_name="amplitude_collapse_blocking",
            signature="amplitude_collapse_blocking:dominant_mode_fraction=0.96",
            metrics={"dominant_mode_fraction": 0.9612},
            human_readable="first",
        )
        b = a.model_copy(
            update={"metrics": {"dominant_mode_fraction": 0.9634}, "human_readable": "second"}
        )
        merged = merge_fingerprint_history({}, {"m": [(a, "e1"), (b, "e2")]}, 3, POLICY)
        [entry] = merged["m"]
        assert entry.metrics == {"dominant_mode_fraction": 0.9634}
        assert entry.human_readable == "second"

    def test_source_exp_ids_latest_eight_oldest_trimmed(self):
        fp = _fp()
        current = {"m": [(fp, f"e{i:02d}") for i in range(SOURCE_EXP_IDS_BOUND + 3)]}
        merged = merge_fingerprint_history({}, current, 1, POLICY)
        [entry] = merged["m"]
        ids = entry.occurrences[0].source_exp_ids
        assert len(ids) == SOURCE_EXP_IDS_BOUND
        assert ids[0] == "e03" and ids[-1] == "e10"  # oldest trimmed first

    def test_deterministic_ordering_and_trim(self):
        policy = HealthFeedbackRetentionPolicy(max_entries_per_model=2)
        prev = {
            "m": [
                _entry(sig="old_frequent", occurrences=[(5, 5)]),
                _entry(sig="recent_rare", occurrences=[(7, 1)]),
                _entry(sig="recent_frequent", occurrences=[(7, 3)]),
            ]
        }
        merged = merge_fingerprint_history(prev, {}, 7, policy)
        # last_retained desc, windowed_count desc, signature asc — then trim.
        assert [e.signature for e in merged["m"]] == ["recent_frequent", "recent_rare"]

    def test_merge_is_deterministic(self):
        prev = {"m": [_entry(sig="s1", occurrences=[(6, 2)])]}
        current = {"m": [(_fp(sig="s2"), "e1"), (_fp(sig="s1"), "e2")]}
        once = merge_fingerprint_history(prev, current, 7, POLICY)
        twice = merge_fingerprint_history(prev, current, 7, POLICY)
        assert once == twice
        # And the inputs were not mutated (pure function).
        assert prev["m"][0].occurrences[0].count == 2

    def test_prompt_counts_use_windowed_not_lifetime(self):
        # Fixture whose lifetime total (6) differs from the windowed
        # value (2): derived accessors must expose the windowed one.
        prev = {"m": [_entry(occurrences=[(1, 4), (7, 2)])]}
        merged = merge_fingerprint_history(prev, {}, 7, POLICY)
        [entry] = merged["m"]
        min_iter = POLICY.minimum_retained_iter(7)
        assert entry.windowed_count(min_iter) == 2
        assert sum(o.count for o in entry.occurrences) == 2  # expired bucket GONE
