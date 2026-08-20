"""Step 09.5a C1 — the committed-digest authority behaves like ONE reader.

Finding A-2 was that four functions implemented one read / parse / soft-fail
contract, so N committed iterations were opened and parsed 4N times and the
policy could drift in four places.

Defects only this file catches:

* **the "one authority" claim is cosmetic** — four functions became one
  *function* while production still calls it four times, so the file is still
  opened four times. A behavioural test cannot see this: four reads and one
  read return identical values.
* **a projection's own failure policy drifted** during the consolidation. The
  four policies genuinely differ (two raise, one warns-and-drops, one ignores a
  non-dict), and a "generic" merge would silently flatten them.
"""

from __future__ import annotations

import builtins
import json
import warnings
from pathlib import Path

import pytest

from core.committed_digests import interpretation_digest_path, read_committed_digests
from core.resume import (
    project_fingerprint_history,
    project_knowledge,
    project_knowledge_cache,
    project_prediction_memory,
)


def _write_digest(root: Path, iter_idx: int, payload: dict) -> Path:
    path = Path(interpretation_digest_path(str(root), iter_idx))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def _full_digest(tag: str) -> dict:
    """A digest carrying every one of the four projected values."""
    return {
        "key_findings": [f"finding-{tag}"],
        "runtime_vocab": [{"name": f"vocab_{tag}", "kind": "feature", "description": "d"}],
        "model_knowledge_cache": {f"model_{tag}": {"_stats": {}}},
        "collapse_fingerprint_history": {},
        "prediction_outcomes_history": {"confirmed": 1},
        "cumulative_information_gain": 0.5,
    }


class TestOneReadPerDigestPerPass:
    def test_the_whole_restoration_pass_opens_each_digest_exactly_once(self, tmp_path, monkeypatch):
        """The A-2 regression test.

        Before C1 this count was 4 per digest (one per loader); after C1 it is
        1, and every one of the four carried values still arrives.
        """
        for i in (1, 2, 3):
            _write_digest(tmp_path, i, _full_digest(str(i)))

        digest_paths = {interpretation_digest_path(str(tmp_path), i) for i in (1, 2, 3)}
        opens: list[str] = []
        real_open = builtins.open

        def counting_open(file, *a, **kw):
            if str(file) in digest_paths:
                opens.append(str(file))
            return real_open(file, *a, **kw)

        monkeypatch.setattr(builtins, "open", counting_open)

        # The production composition: ONE read, then four pure projections.
        reads = read_committed_digests(str(tmp_path), 4, [1, 2, 3])
        vocab, findings = project_knowledge(reads)
        cache = project_knowledge_cache(reads)
        history = project_fingerprint_history(reads)
        memory = project_prediction_memory(reads)

        assert len(opens) == 3, (
            f"expected exactly one open per committed digest, got {len(opens)}: {opens}"
        )
        # ...and the consolidation did not cost any carried value.
        assert [v.name for v in vocab] == ["vocab_3"]
        assert findings == ["finding-1", "finding-2", "finding-3"]
        assert set(cache) == {"model_3"}
        assert history == {}
        assert memory.prediction_outcomes_history == {"confirmed": 1}

    def test_the_open_counter_would_notice_a_second_reader(self, tmp_path, monkeypatch):
        """Anti-vacuity: the counter must actually count."""
        _write_digest(tmp_path, 1, _full_digest("1"))
        digest = interpretation_digest_path(str(tmp_path), 1)
        opens: list[str] = []
        real_open = builtins.open

        def counting_open(file, *a, **kw):
            if str(file) == digest:
                opens.append(str(file))
            return real_open(file, *a, **kw)

        monkeypatch.setattr(builtins, "open", counting_open)
        read_committed_digests(str(tmp_path), 2, [1])
        read_committed_digests(str(tmp_path), 2, [1])  # a planted second reader
        assert len(opens) == 2


class TestReaderClassification:
    def test_nothing_committed_reads_nothing(self, tmp_path):
        assert read_committed_digests(str(tmp_path), 1, [1, 2]) == []
        assert read_committed_digests(str(tmp_path), 5, []) == []

    def test_a_missing_digest_is_reported_not_dropped(self, tmp_path):
        reads = read_committed_digests(str(tmp_path), 2, [1])
        assert [r.status for r in reads] == ["missing"]
        assert reads[0].payload is None

    def test_an_unparseable_digest_is_reported_with_its_detail(self, tmp_path):
        path = _write_digest(tmp_path, 1, {})
        path.write_text("{ not json")
        reads = read_committed_digests(str(tmp_path), 2, [1])
        assert [r.status for r in reads] == ["unreadable"]
        assert reads[0].detail

    def test_reads_preserve_committed_order(self, tmp_path):
        for i in (1, 2, 3):
            _write_digest(tmp_path, i, _full_digest(str(i)))
        reads = read_committed_digests(str(tmp_path), 4, [1, 2, 3])
        assert [r.iter_idx for r in reads] == [1, 2, 3]


class TestWarningMultiplicityIsPreserved:
    """Amendment D: diagnostic multiplicity is behaviour and stays; the I/O
    behind it does not."""

    def test_one_corrupt_digest_still_warns_once_per_carried_value(self, tmp_path):
        path = _write_digest(tmp_path, 1, {})
        path.write_text("{ not json")
        reads = read_committed_digests(str(tmp_path), 2, [1])

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            project_knowledge(reads)
            project_knowledge_cache(reads)
            project_fingerprint_history(reads)
            project_prediction_memory(reads)

        messages = [str(w.message) for w in caught]
        assert len(messages) == 4, messages
        # ...and each still names ITS carry-over, which is why the duplication
        # is worth keeping: the operator learns which value was affected.
        for label in (
            "knowledge carry-over",
            "knowledge-cache carry-over",
            "fingerprint-history carry-over",
            "prediction-memory carry-over",
        ):
            assert any(label in m for m in messages), f"missing diagnostic for {label}"

    def test_a_missing_digest_uses_the_historical_wording(self, tmp_path):
        reads = read_committed_digests(str(tmp_path), 2, [1])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            project_knowledge(reads)
        assert "interpretation digest not found at" in str(caught[0].message)
        assert "Skipping for knowledge carry-over." in str(caught[0].message)


class TestProjectionPoliciesStayDifferent:
    """The four policies are not interchangeable, and a shared reader must not
    have made them so."""

    def test_knowledge_drops_a_malformed_vocab_entry_and_keeps_the_rest(self, tmp_path):
        _write_digest(
            tmp_path,
            1,
            {
                "runtime_vocab": [
                    {"name": "good", "kind": "feature", "description": "d"},
                    {"nope": True},
                ]
            },
        )
        reads = read_committed_digests(str(tmp_path), 2, [1])
        with pytest.warns(UserWarning, match="dropped malformed runtime_vocab entry"):
            vocab, _ = project_knowledge(reads)
        assert [v.name for v in vocab] == ["good"]

    def test_fingerprint_history_raises_on_a_malformed_entry(self, tmp_path):
        _write_digest(tmp_path, 1, {"collapse_fingerprint_history": {"m": [{"bad": 1}]}})
        reads = read_committed_digests(str(tmp_path), 2, [1])
        with pytest.raises(ValueError, match="corrupted collapse_fingerprint_history"):
            project_fingerprint_history(reads)

    def test_prediction_memory_raises_on_a_corrupted_record(self, tmp_path):
        _write_digest(tmp_path, 1, {"prediction_outcomes_history": "not-a-dict"})
        reads = read_committed_digests(str(tmp_path), 2, [1])
        with pytest.raises(ValueError, match="corrupted prediction memory"):
            project_prediction_memory(reads)

    def test_knowledge_cache_ignores_a_non_dict_without_raising(self, tmp_path):
        _write_digest(tmp_path, 1, {"model_knowledge_cache": "not-a-dict"})
        reads = read_committed_digests(str(tmp_path), 2, [1])
        assert project_knowledge_cache(reads) == {}

    def test_key_findings_accumulate_while_vocab_is_latest_wins(self, tmp_path):
        _write_digest(tmp_path, 1, _full_digest("1"))
        _write_digest(tmp_path, 2, _full_digest("2"))
        reads = read_committed_digests(str(tmp_path), 3, [1, 2])
        vocab, findings = project_knowledge(reads)
        assert findings == ["finding-1", "finding-2"], "union, first-occurrence"
        assert [v.name for v in vocab] == ["vocab_2"], "latest-wins"

    def test_an_empty_cache_on_disk_overwrites_but_a_missing_key_does_not(self, tmp_path):
        _write_digest(tmp_path, 1, {"model_knowledge_cache": {"m": {}}})
        _write_digest(tmp_path, 2, {})  # missing key -> keep running value
        reads = read_committed_digests(str(tmp_path), 3, [1, 2])
        assert set(project_knowledge_cache(reads)) == {"m"}

        _write_digest(tmp_path, 2, {"model_knowledge_cache": {}})  # explicit eviction
        reads = read_committed_digests(str(tmp_path), 3, [1, 2])
        assert project_knowledge_cache(reads) == {}
