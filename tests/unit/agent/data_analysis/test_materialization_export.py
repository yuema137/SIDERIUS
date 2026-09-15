from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent.data_analysis.materialization import (
    AnalysisMaterializationError,
    export_materialized_view_content,
)
from agent.schemas.data_analysis.assets import (
    AnalysisAuthorizationReceipt,
    MaterializedAnalysisView,
)
from agent.schemas.data_analysis.common import CertifiedArtifactRef


def _view(payload: bytes, *, byte_size: int | None = None) -> MaterializedAnalysisView:
    digest = hashlib.sha256(payload).hexdigest()
    return MaterializedAnalysisView(
        materialization_id="materialization-export",
        invocation_id="invocation-export",
        binding_id="binding-export",
        slot_id="values",
        asset_id="asset-export",
        split_id="validation",
        content_ref=CertifiedArtifactRef(
            logical_ref="opaque://task-owned/object-17",
            sha256=digest,
            media_type="application/x-npz",
            byte_size=len(payload) if byte_size is None else byte_size,
        ),
        format_id="siderius.numeric-array.v1",
        population_unit="examples",
        total_available=1,
        materialized_count=1,
        certified_information=({"information_class": "data"},),
        selection_identity={
            "selection_id": "selection-export",
            "selection_sha256": "4" * 64,
            "sampling_policy_sha256": "5" * 64,
            "sampling_mode": "full_if_feasible",
            "sampling_strategy": "uniform",
            "sampling_seed": 0,
            "population_unit": "examples",
            "total_available": 1,
            "selected_count": 1,
        },
        source_digests=(digest,),
        authorization_receipt=AnalysisAuthorizationReceipt(
            invocation_id="invocation-export",
            binding_id="binding-export",
            slot_id="values",
            request_digest="1" * 64,
            policy_digest="2" * 64,
            asset_digest="3" * 64,
            authorized_at="2026-09-14T00:00:00+00:00",
        ),
    )


class _Exporter:
    def __init__(self, payload: bytes, *, symlink_target: Path | None = None) -> None:
        self.payload = payload
        self.symlink_target = symlink_target
        self.seen_ref = None

    def export_analysis_materialization(self, content_ref, destination: Path) -> None:
        self.seen_ref = content_ref
        if self.symlink_target is not None:
            destination.symlink_to(self.symlink_target)
        else:
            destination.write_bytes(self.payload)


def test_opaque_logical_ref_is_exported_to_executor_owned_verified_path(tmp_path: Path) -> None:
    payload = b"task-owned-materialization"
    view = _view(payload)
    exporter = _Exporter(payload)

    paths = export_materialized_view_content(
        exporter,
        views=(view,),
        destination_root=tmp_path / "executor-materializations",
    )

    assert exporter.seen_ref == view.content_ref
    exported = Path(paths[view.binding_id])
    assert exported.read_bytes() == payload
    assert exported.parent == (tmp_path / "executor-materializations").resolve()
    assert view.content_ref.logical_ref not in str(exported)


@pytest.mark.parametrize(
    ("exported", "byte_size", "message"),
    [
        (b"wrong", None, "digest"),
        (b"right", 999, "byte size"),
    ],
)
def test_exported_bytes_must_match_certified_ref(
    tmp_path: Path, exported: bytes, byte_size: int | None, message: str
) -> None:
    view = _view(b"right", byte_size=byte_size)
    with pytest.raises(AnalysisMaterializationError, match=message):
        export_materialized_view_content(
            _Exporter(exported),
            views=(view,),
            destination_root=tmp_path / "executor-materializations",
        )


def test_exported_content_must_be_regular_file_not_symlink(tmp_path: Path) -> None:
    payload = b"content"
    source = tmp_path / "task-private-object"
    source.write_bytes(payload)
    with pytest.raises(AnalysisMaterializationError, match="non-symlink"):
        export_materialized_view_content(
            _Exporter(payload, symlink_target=source),
            views=(_view(payload),),
            destination_root=tmp_path / "executor-materializations",
        )


def test_exporter_must_create_destination(tmp_path: Path) -> None:
    class MissingExporter:
        def export_analysis_materialization(self, content_ref, destination: Path) -> None:
            del content_ref, destination

    with pytest.raises(AnalysisMaterializationError, match="regular"):
        export_materialized_view_content(
            MissingExporter(),
            views=(_view(b"content"),),
            destination_root=tmp_path / "executor-materializations",
        )
