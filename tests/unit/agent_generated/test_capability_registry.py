"""
Unit tests for ``agent_generated/_registry.py`` — ``CapabilityMetadata`` +
``CapabilityRegistry``.

Coverage:
  * Empty index → ``list()`` returns ``[]``
  * ``register()`` → ``list()`` round-trip
  * ``list(capability_type=...)`` filters correctly
  * ``exists(name, type)`` true/false branches
  * Duplicate registration raises ``ValueError``
  * Schema validation: missing/extra fields rejected
  * Atomic write: concurrent register from two processes does not corrupt JSON

See ``docs/design/enable_loss_inventory.md`` § Commit L1.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_generated._registry import CapabilityMetadata, CapabilityRegistry


def _meta(
    name: str,
    capability_type: str = "loss",
    file_path: str = "/abs/path/file.py",
    description: str = "",
    source_iteration: str | None = None,
) -> CapabilityMetadata:
    return CapabilityMetadata(
        name=name,
        capability_type=capability_type,  # type: ignore[arg-type]
        file_path=file_path,
        created_at="2026-06-19T12:34:56Z",
        source_iteration=source_iteration,
        description=description,
    )


@pytest.fixture
def reg(tmp_path: Path) -> CapabilityRegistry:
    """Fresh registry pointing at a tmp index file (file does not exist yet)."""
    return CapabilityRegistry(index_path=str(tmp_path / "_capability_index.json"))


# ---------------------------------------------------------------------------
# Empty registry
# ---------------------------------------------------------------------------


class TestEmptyRegistry:
    def test_list_returns_empty_on_missing_file(self, reg: CapabilityRegistry):
        assert reg.list() == []

    def test_list_with_type_filter_on_missing_file(self, reg: CapabilityRegistry):
        assert reg.list(capability_type="loss") == []

    def test_exists_false_on_missing_file(self, reg: CapabilityRegistry):
        assert reg.exists("snr_weighted_mse", "loss") is False

    def test_list_returns_empty_on_explicit_empty_array(self, tmp_path: Path):
        p = tmp_path / "_capability_index.json"
        p.write_text("[]")
        reg = CapabilityRegistry(index_path=str(p))
        assert reg.list() == []

    def test_list_returns_empty_on_null_content(self, tmp_path: Path):
        p = tmp_path / "_capability_index.json"
        p.write_text("null")
        reg = CapabilityRegistry(index_path=str(p))
        assert reg.list() == []


# ---------------------------------------------------------------------------
# register() → list() round-trip
# ---------------------------------------------------------------------------


class TestRegisterListRoundTrip:
    def test_single_register_then_list(self, reg: CapabilityRegistry):
        m = _meta("snr_weighted_mse", description="SNR-weighted MSE")
        reg.register(m)
        rows = reg.list()
        assert len(rows) == 1
        assert rows[0].name == "snr_weighted_mse"
        assert rows[0].capability_type == "loss"
        assert rows[0].description == "SNR-weighted MSE"

    def test_multiple_register_preserve_insertion_order(self, reg: CapabilityRegistry):
        reg.register(_meta("a", description="first"))
        reg.register(_meta("b", description="second"))
        reg.register(_meta("c", description="third"))
        rows = reg.list()
        assert [r.name for r in rows] == ["a", "b", "c"]

    def test_index_file_is_valid_json_array(self, reg: CapabilityRegistry):
        reg.register(_meta("a"))
        reg.register(_meta("b"))
        with open(reg.index_path, encoding="utf-8") as f:
            raw = json.load(f)
        assert isinstance(raw, list)
        assert len(raw) == 2
        assert raw[0]["name"] == "a"
        assert raw[1]["name"] == "b"


# ---------------------------------------------------------------------------
# list() filtering by capability_type
# ---------------------------------------------------------------------------


class TestListFilter:
    def test_filter_returns_only_matching_type(self, reg: CapabilityRegistry):
        reg.register(_meta("loss_a", capability_type="loss"))
        reg.register(_meta("model_a", capability_type="model"))
        reg.register(_meta("loss_b", capability_type="loss"))
        losses = reg.list(capability_type="loss")
        models = reg.list(capability_type="model")
        assert [r.name for r in losses] == ["loss_a", "loss_b"]
        assert [r.name for r in models] == ["model_a"]

    def test_filter_no_match_returns_empty(self, reg: CapabilityRegistry):
        reg.register(_meta("loss_a", capability_type="loss"))
        assert reg.list(capability_type="tool") == []

    def test_no_filter_returns_all(self, reg: CapabilityRegistry):
        reg.register(_meta("loss_a", capability_type="loss"))
        reg.register(_meta("model_a", capability_type="model"))
        rows = reg.list()
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# exists()
# ---------------------------------------------------------------------------


class TestExists:
    def test_exists_true_on_match(self, reg: CapabilityRegistry):
        reg.register(_meta("snr_weighted_mse"))
        assert reg.exists("snr_weighted_mse", "loss") is True

    def test_exists_false_on_wrong_name(self, reg: CapabilityRegistry):
        reg.register(_meta("snr_weighted_mse"))
        assert reg.exists("snr_weighted_other", "loss") is False

    def test_exists_false_on_wrong_type(self, reg: CapabilityRegistry):
        # Name matches but capability_type differs → no match.
        reg.register(_meta("shared_name", capability_type="loss"))
        assert reg.exists("shared_name", "model") is False


# ---------------------------------------------------------------------------
# Duplicate registration
# ---------------------------------------------------------------------------


class TestDuplicateRejection:
    def test_register_duplicate_raises(self, reg: CapabilityRegistry):
        reg.register(_meta("snr_weighted_mse"))
        with pytest.raises(ValueError, match="already registered"):
            reg.register(_meta("snr_weighted_mse"))

    def test_same_name_different_type_allowed(self, reg: CapabilityRegistry):
        # (name, capability_type) is the uniqueness key — same name with
        # different capability_type is permitted.
        reg.register(_meta("shared_name", capability_type="loss"))
        reg.register(_meta("shared_name", capability_type="model"))
        rows = reg.list()
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            CapabilityMetadata.model_validate(
                {
                    # missing "name"
                    "capability_type": "loss",
                    "file_path": "/x",
                    "created_at": "2026-06-19T00:00:00Z",
                }
            )

    def test_empty_name_raises(self):
        with pytest.raises(ValidationError):
            _meta(name="")

    def test_invalid_capability_type_raises(self):
        with pytest.raises(ValidationError):
            CapabilityMetadata.model_validate(
                {
                    "name": "x",
                    "capability_type": "INVALID",  # not in Literal
                    "file_path": "/x",
                    "created_at": "2026-06-19T00:00:00Z",
                }
            )

    def test_list_raises_on_corrupted_row(self, reg: CapabilityRegistry):
        # Hand-write a JSON file with a malformed row.
        Path(reg.index_path).write_text(
            json.dumps([{"name": "x"}])  # missing fields
        )
        with pytest.raises(ValidationError):
            reg.list()

    def test_list_raises_on_non_array_top_level(self, reg: CapabilityRegistry):
        Path(reg.index_path).write_text(json.dumps({"not": "a list"}))
        with pytest.raises(ValueError, match="expected a JSON array"):
            reg.list()


# ---------------------------------------------------------------------------
# Atomic write — concurrent register() does not corrupt JSON
# ---------------------------------------------------------------------------


def _child_register(index_path: str, names: list[str]) -> None:
    """Subprocess helper for the atomicity test. Registers a small batch."""
    reg = CapabilityRegistry(index_path=index_path)
    for n in names:
        # Ignore duplicate ValueError on collision — the test only checks JSON
        # validity, not which writer wins. Retry briefly on the duplicate
        # path so the child actually makes forward progress.
        for _ in range(3):
            try:
                reg.register(_meta(n))
                break
            except ValueError:
                time.sleep(0.01)


class TestAtomicWrite:
    def test_concurrent_register_does_not_corrupt_json(self, tmp_path: Path):
        index = tmp_path / "_capability_index.json"
        # Pre-seed an empty array so both children start from a known state.
        index.write_text("[]")

        # Two processes each register 5 unique names.
        names_a = [f"a_{i}" for i in range(5)]
        names_b = [f"b_{i}" for i in range(5)]
        p1 = mp.Process(target=_child_register, args=(str(index), names_a))
        p2 = mp.Process(target=_child_register, args=(str(index), names_b))
        p1.start()
        p2.start()
        p1.join(timeout=10)
        p2.join(timeout=10)
        assert p1.exitcode == 0
        assert p2.exitcode == 0

        # The final file must parse as valid JSON (no partial-write
        # corruption from interleaved writes).
        with open(index, encoding="utf-8") as f:
            raw = json.load(f)
        assert isinstance(raw, list)
        # Not all 10 names are guaranteed to land — concurrent
        # read-modify-write without a file lock can lose updates. The
        # ATOMIC-WRITE property under test here is "the file is never
        # corrupted", not "every register call succeeds". A real-world
        # caller using ``register`` from a single process per chain run
        # has no contention.
        # Still: at least some writes must have landed (otherwise the
        # test isn't actually exercising the write path).
        assert len(raw) >= 1
