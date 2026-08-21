"""Step 10 / P5+P6 — C1: ``project_vocab_link_confirmations``.

Design:
``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p5_6_lifecycle_and_three_task_closure.md`` §7.1, §8.1, §8.2, §13 C1.

The resume half of the confirmations lifecycle, tested in isolation while
NOTHING consumes it — so the merge rule and the failure policy are reviewable
against the four siblings without a workflow in the way.

The defect class only this module catches: a projection that transports
promotion state with the WRONG merge rule or the WRONG failure policy. Both are
invisible to any end-to-end test, which sees only a final mapping and cannot
tell a latest-wins result from a union that happened to agree, nor a
fail-closed refusal from a silently-dropped digest.

Frozen policy under test (§7.1 / §8.2):

    merge            latest valid mapping wins, WHOLE dict
    missing key      {}          (pre-activation digest — compatible default)
    empty mapping    a value, not an absence — it OVERWRITES
    malformed value  RAISE       (promotion state fails closed)
    unusable digest  warn + skip (the sibling shape)
    run lists        pass through unvalidated — the producer owns the count
"""

from __future__ import annotations

import pytest

from core.committed_digests import DigestRead
from core.resume import project_vocab_link_confirmations

KEY = "dilated_stack:long_range_context"
OTHER = "gated_activation:sharp_transients"


def _ok(iter_idx: int, payload: dict) -> DigestRead:
    return DigestRead(
        iter_idx=iter_idx,
        path=f"/ws/iter_{iter_idx:03d}/interpretation_iter_{iter_idx:03d}.json",
        status="ok",
        payload=payload,
    )


def _unreadable(iter_idx: int) -> DigestRead:
    return DigestRead(
        iter_idx=iter_idx,
        path=f"/ws/iter_{iter_idx:03d}/interpretation_iter_{iter_idx:03d}.json",
        status="unreadable",
        detail="Expecting value: line 1 column 1 (char 0)",
    )


# ---------------------------------------------------------------------------
# The merge rule
# ---------------------------------------------------------------------------


class TestLatestWinsOnTheWholeDict:
    def test_no_digests_projects_empty(self):
        assert project_vocab_link_confirmations([]) == {}

    def test_one_digest_projects_its_mapping(self):
        reads = [_ok(1, {"vocab_link_confirmations": {KEY: ["wavenet"]}})]
        assert project_vocab_link_confirmations(reads) == {KEY: ["wavenet"]}

    def test_agreeing_digests_project_the_shared_mapping(self):
        mapping = {KEY: ["wavenet", "punet"]}
        reads = [
            _ok(1, {"vocab_link_confirmations": dict(mapping)}),
            _ok(2, {"vocab_link_confirmations": dict(mapping)}),
        ]
        assert project_vocab_link_confirmations(reads) == mapping

    def test_the_later_digest_wins_outright_including_a_pair_it_dropped(self):
        """What makes latest-wins OBSERVABLE, and a union detectably wrong.

        Iteration 1 confirmed two pairs; iteration 2's mapping no longer
        carries ``OTHER``. Latest-wins drops it. A union would resurrect a pair
        a later iteration legitimately stopped carrying — and would be a second
        accumulation authority besides the producer.
        """
        reads = [
            _ok(1, {"vocab_link_confirmations": {KEY: ["wavenet"], OTHER: ["punet"]}}),
            _ok(2, {"vocab_link_confirmations": {KEY: ["wavenet", "fcnet"]}}),
        ]
        assert project_vocab_link_confirmations(reads) == {KEY: ["wavenet", "fcnet"]}

    def test_an_empty_mapping_in_the_latest_digest_overwrites_a_non_empty_one(self):
        """``{}`` is a legitimate cleared state, distinct from an absent key.
        A projection that treated empty as "nothing to say" would resurrect
        state the run had cleared."""
        reads = [
            _ok(1, {"vocab_link_confirmations": {KEY: ["wavenet", "punet"]}}),
            _ok(2, {"vocab_link_confirmations": {}}),
        ]
        assert project_vocab_link_confirmations(reads) == {}

    def test_a_later_digest_missing_the_key_does_NOT_overwrite(self):
        """The distinction the previous test depends on, from the other side:
        an ABSENT key is a pre-activation digest and says nothing, so the last
        digest that DID carry a mapping still wins."""
        reads = [
            _ok(1, {"vocab_link_confirmations": {KEY: ["wavenet"]}}),
            _ok(2, {"key_findings": ["a legacy digest with no confirmations"]}),
        ]
        assert project_vocab_link_confirmations(reads) == {KEY: ["wavenet"]}

    def test_ascending_digest_order_is_what_latest_means(self):
        """The siblings assume ascending committed order; asserted here rather
        than inherited, since 'latest' is meaningless without it."""
        ascending = [
            _ok(1, {"vocab_link_confirmations": {KEY: ["first"]}}),
            _ok(2, {"vocab_link_confirmations": {KEY: ["second"]}}),
        ]
        assert project_vocab_link_confirmations(ascending) == {KEY: ["second"]}
        assert project_vocab_link_confirmations(list(reversed(ascending))) == {KEY: ["first"]}

    def test_run_lists_pass_through_without_dedup(self):
        """The producer is the ONLY authority on the promotion count.

        De-duplicating here would silently change WHEN a pair graduates, so a
        stored duplicate survives the hop verbatim even though the producer
        would never have written one.
        """
        reads = [_ok(1, {"vocab_link_confirmations": {KEY: ["wavenet", "wavenet"]}})]
        assert project_vocab_link_confirmations(reads) == {KEY: ["wavenet", "wavenet"]}

    def test_the_projection_does_not_alias_the_payload(self):
        """Mutating the result must not corrupt the digest read."""
        payload = {"vocab_link_confirmations": {KEY: ["wavenet"]}}
        result = project_vocab_link_confirmations([_ok(1, payload)])
        result[KEY].append("mutated")
        assert payload["vocab_link_confirmations"] == {KEY: ["wavenet"]}


# ---------------------------------------------------------------------------
# The failure policy (§8.2 — RAISE)
# ---------------------------------------------------------------------------


class TestMalformedValuesFailClosed:
    """Promotion state fails closed — ``project_prediction_memory``'s policy,
    one level up."""

    @pytest.mark.parametrize(
        ("garbage", "fragment"),
        [
            ("not-a-mapping", "expected a mapping, got str"),
            (["a", "list"], "expected a mapping, got list"),
            ({KEY: "a bare string, not a list"}, "maps to str, expected a list"),
            ({KEY: [1, 2, 3]}, "contains non-string run name 1"),
            ({7: ["numeric key"]}, "non-string key 7"),
        ],
    )
    def test_each_malformed_shape_raises_with_a_diagnosing_message(self, garbage, fragment):
        reads = [_ok(3, {"vocab_link_confirmations": garbage})]
        with pytest.raises(ValueError) as excinfo:
            project_vocab_link_confirmations(reads)

        message = str(excinfo.value)
        assert fragment in message
        # Names the digest so an operator can act on it, and says why it
        # refused rather than degrading.
        assert "iter 003" in message
        assert "interpretation_iter_003.json" in message
        assert "promotion state" in message

    def test_a_malformed_LATER_digest_refuses_rather_than_keeping_the_earlier_one(
        self,
    ):
        """The whole point of failing closed: silently keeping iteration 1's
        mapping would change WHEN the pair graduates."""
        reads = [
            _ok(1, {"vocab_link_confirmations": {KEY: ["wavenet", "punet"]}}),
            _ok(2, {"vocab_link_confirmations": "corrupted"}),
        ]
        with pytest.raises(ValueError):
            project_vocab_link_confirmations(reads)


class TestUnusableDigestsWarnAndSkip:
    """An UNREADABLE digest is not a malformed VALUE — it takes the siblings'
    warn-and-skip path, so one corrupt file does not sink a whole restore."""

    def test_an_unreadable_digest_warns_in_the_sibling_shape_and_is_skipped(self):
        reads = [
            _ok(1, {"vocab_link_confirmations": {KEY: ["wavenet"]}}),
            _unreadable(2),
        ]
        with pytest.warns(UserWarning) as record:
            result = project_vocab_link_confirmations(reads)

        assert result == {KEY: ["wavenet"]}
        message = str(record[0].message)
        assert "cannot read interpretation digest" in message
        # Its OWN carry-over label, so an operator can tell which value was
        # affected — the one thing that varies between the sibling messages.
        assert "vocab-link-confirmations" in message


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestPreActivationDigestsRestoreQuietly:
    def test_a_whole_pre_activation_digest_set_projects_empty_with_no_warning(self, recwarn):
        """Every digest written before this lifecycle existed lacks the key.
        That must be silent: it is a compatible default, not a fault."""
        reads = [
            _ok(1, {"key_findings": ["f1"], "runtime_vocab": []}),
            _ok(2, {"key_findings": ["f2"], "runtime_vocab": []}),
        ]
        assert project_vocab_link_confirmations(reads) == {}
        assert [w for w in recwarn if issubclass(w.category, UserWarning)] == []
