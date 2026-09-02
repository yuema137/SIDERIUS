"""
RT2-B unit tests: provenance capture (§2.2).

Pins the explicit-degradation contract (missing counters → ``None`` /
``"unknown"``, never fabricated values) and the measured cache-state
classification.
"""

from __future__ import annotations

from core.runtime_control.provenance import (
    capture_environment_provenance,
    capture_storage_provenance,
    classify_cache_state,
    read_process_read_bytes,
    read_process_rss_bytes,
)
from execute_tools.dataset_config import DatasetProfile
from execute_tools.task_data_path import StorageReadScope
from execute_tools.train_engine_sandbox import _setup_storage_provenance


class TestEnvironmentProvenance:
    def test_required_keys_present(self):
        prov = capture_environment_provenance()
        for key in (
            "hostname",
            "platform",
            "python_version",
            "timestamp",
            "torch_version",
            "cuda_version",
            "gpu_name",
        ):
            assert key in prov
        assert prov["hostname"]
        assert prov["python_version"][0].isdigit()


class TestProcessCounters:
    def test_read_bytes_is_int_or_none(self):
        v = read_process_read_bytes()
        assert v is None or (isinstance(v, int) and v >= 0)

    def test_rss_is_int_or_none(self):
        v = read_process_rss_bytes()
        assert v is None or (isinstance(v, int) and v > 0)


class TestStorageProvenance:
    def test_counts_and_bytes(self, tmp_path):
        f1 = tmp_path / "a.h5"
        f1.write_bytes(b"\x00" * 100)
        missing = tmp_path / "b.h5"
        prov = capture_storage_provenance(str(tmp_path), [str(f1), str(missing)])
        assert prov["file_count"] == 2
        assert prov["files_present"] == 1
        assert prov["expected_raw_bytes"] == 100
        assert prov["dataset_root"] == str(tmp_path)
        assert isinstance(prov["filesystem_type"], str)

    def test_opaque_task_scope_uses_task_owned_physical_read_description(self, tmp_path):
        """Composed tasks must not degrade to an empty storage claim."""
        source = tmp_path / "source.bin"
        source.write_bytes(b"x" * 80)

        class DataPath:
            def storage_read_scope(self, data_dir, scope):
                assert scope == object_scope
                return StorageReadScope(
                    file_paths=(str(source),),
                    expected_on_disk_bytes=20,
                )

        object_scope = object()
        observed = _setup_storage_provenance(
            str(tmp_path),
            None,
            DatasetProfile(
                partition_count=1,
                anchor_selection_files=[0],
                health_peek_files=[0],
            ),
            data_path=DataPath(),
            task_scope=object_scope,
        )

        assert observed["file_count"] == 1
        assert observed["files_present"] == 1
        assert observed["total_file_bytes"] == 80
        assert observed["expected_raw_bytes"] == 20


class TestCacheStateClassification:
    def test_unknown_when_counters_missing(self):
        assert classify_cache_state(None, 100) == "unknown"
        assert classify_cache_state(100, None) == "unknown"
        assert classify_cache_state(100, 0) == "unknown"

    def test_cold_when_read_dominates(self):
        assert classify_cache_state(90, 100) == "cold_first_access"
        assert classify_cache_state(50, 100) == "cold_first_access"  # boundary inclusive

    def test_warm_when_read_negligible(self):
        assert classify_cache_state(0, 100) == "warm_page_cache"
        assert classify_cache_state(10, 100) == "warm_page_cache"

    def test_unknown_when_process_counter_cannot_observe_backing_reads(self):
        assert classify_cache_state(0, 100, filesystem_type="fuse.s3fs") == "unknown"
        assert classify_cache_state(0, 100, filesystem_type="virtiofs") == "unknown"
