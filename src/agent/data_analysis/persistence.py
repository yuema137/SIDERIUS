"""Durable, append-only persistence for a standalone analysis attempt."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from pydantic import BaseModel

from agent.schemas.data_analysis.common import CertifiedArtifactRef, canonical_json_bytes
from agent.schemas.data_analysis.context import DataAnalysisInput
from agent.schemas.data_analysis.plan import AnalysisPlan
from agent.schemas.data_analysis.report import CertifiedResultRef, DataAnalysisReport
from agent.schemas.data_analysis.skills import ArtifactOutputContract, ProducedArtifact, SkillResult
from agent.schemas.data_analysis.trained_model import ModelInferenceReceipt
from agent.schemas.storage import StorageConfig
from core.campaign_identity import validate_path_component
from core.durable_io import append_line_durably, publish_bytes_write_once
from core.execution_deadline import ExecutionBudgetReceipt
from execute_tools.historical_model_inference import HistoricalPredictionRetentionReceipt

from .discovery import DiscoverySnapshot


class AnalysisPersistenceError(RuntimeError):
    """Canonical analysis evidence could not be safely persisted or resolved."""


class AnalysisRunStore:
    def __init__(self, storage: StorageConfig, *, request_id: str) -> None:
        if storage.backend != "local" or storage.local is None:
            raise NotImplementedError("Data Analysis currently requires a local StorageConfig")
        run_name = validate_path_component(storage.local.run_name, kind="analysis run name")
        request_name = validate_path_component(request_id, kind="analysis request id")
        self.run_root = Path(storage.local.workspace) / "data_analysis" / run_name
        self.root = self.run_root / request_name
        self.artifact_root = self.root / "artifacts"

    @property
    def generated_skill_registry_root(self) -> Path:
        return self.run_root / "generated_skill_registry"

    @property
    def skill_results_path(self) -> Path:
        return self.root / "skill_results.jsonl"

    @property
    def inference_receipts_path(self) -> Path:
        return self.root / "inference_receipts.jsonl"

    @property
    def prediction_retention_receipts_path(self) -> Path:
        return self.root / "prediction_retention_receipts.jsonl"

    @property
    def structured_output_receipts_path(self) -> Path:
        return self.root / "structured_output_receipts.jsonl"

    def _write_model_once(self, name: str, value: BaseModel) -> CertifiedArtifactRef:
        payload = canonical_json_bytes(value)
        path = self.root / name
        publish_bytes_write_once(str(path), payload)
        return CertifiedArtifactRef(
            logical_ref=str(path.relative_to(self.root)),
            sha256=hashlib.sha256(payload).hexdigest(),
            media_type="application/json",
            byte_size=len(payload),
        )

    def write_input(self, value: DataAnalysisInput) -> CertifiedArtifactRef:
        return self._write_model_once("input.json", value)

    def resume_completed_report(self, value: DataAnalysisInput) -> DataAnalysisReport | None:
        """Return an exact compatible completed report; refuse ambiguous partial reuse."""

        input_path = self.root / "input.json"
        if not input_path.exists():
            return None
        expected = canonical_json_bytes(value)
        observed = input_path.read_bytes()
        if observed != expected:
            raise AnalysisPersistenceError(
                "analysis request_id already exists with a different canonical input identity"
            )
        report_path = self.root / "report.json"
        if report_path.exists():
            try:
                return DataAnalysisReport.model_validate_json(report_path.read_bytes())
            except ValueError as exc:
                raise AnalysisPersistenceError("persisted analysis report is invalid") from exc
        raise AnalysisPersistenceError(
            "analysis attempt is incomplete; v0.1 refuses implicit partial replay"
        )

    def write_budget_receipt(self, value: ExecutionBudgetReceipt) -> CertifiedArtifactRef:
        return self._write_model_once("budget_receipt.json", value)

    def write_discovery(self, value: DiscoverySnapshot) -> CertifiedArtifactRef:
        return self._write_model_once("discovery.json", value)

    def write_plan(self, value: AnalysisPlan) -> CertifiedArtifactRef:
        return self._write_model_once("plan.json", value)

    def append_skill_result(self, value: SkillResult) -> CertifiedResultRef:
        payload = canonical_json_bytes(value)
        append_line_durably(str(self.skill_results_path), payload.decode("utf-8"))
        return CertifiedResultRef(
            result_id=value.result_id,
            logical_ref=f"skill_results.jsonl#{value.result_id}",
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    def append_inference_receipt(self, value: ModelInferenceReceipt) -> CertifiedArtifactRef:
        payload = canonical_json_bytes(value)
        append_line_durably(str(self.inference_receipts_path), payload.decode("utf-8"))
        return CertifiedArtifactRef(
            logical_ref=f"inference_receipts.jsonl#{value.inference_id}",
            sha256=hashlib.sha256(payload).hexdigest(),
            media_type="application/json",
            byte_size=len(payload),
        )

    def append_prediction_retention_receipt(
        self, value: HistoricalPredictionRetentionReceipt
    ) -> None:
        append_line_durably(
            str(self.prediction_retention_receipts_path),
            canonical_json_bytes(value).decode("utf-8"),
        )

    def append_structured_output_receipt(self, value: BaseModel) -> CertifiedArtifactRef:
        """Persist internal LLM-to-schema validation provenance append-only."""

        payload = canonical_json_bytes(value)
        append_line_durably(str(self.structured_output_receipts_path), payload.decode("utf-8"))
        digest = hashlib.sha256(payload).hexdigest()
        return CertifiedArtifactRef(
            logical_ref=f"structured_output_receipts.jsonl#{digest}",
            sha256=digest,
            media_type="application/json",
            byte_size=len(payload),
        )

    def append_synthesis_grounding_receipt(self, value: BaseModel) -> None:
        """Retain drafts and reference errors separately from schema-repair receipts."""
        append_line_durably(
            str(self.root / "synthesis_grounding_receipts.jsonl"),
            canonical_json_bytes(value).decode("utf-8"),
        )

    def read_skill_results(self) -> tuple[SkillResult, ...]:
        try:
            lines = self.skill_results_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return ()
        results: list[SkillResult] = []
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                results.append(SkillResult.model_validate_json(line))
            except ValueError as exc:
                raise AnalysisPersistenceError(
                    f"invalid skill result at line {line_number}: {exc}"
                ) from exc
        return tuple(results)

    def write_report(
        self,
        value: DataAnalysisReport,
        *,
        markdown: str,
    ) -> tuple[CertifiedArtifactRef, CertifiedArtifactRef]:
        report_ref = self._write_model_once("report.json", value)
        markdown_bytes = markdown.encode("utf-8")
        path = self.root / "report.md"
        publish_bytes_write_once(str(path), markdown_bytes)
        markdown_ref = CertifiedArtifactRef(
            logical_ref="report.md",
            sha256=hashlib.sha256(markdown_bytes).hexdigest(),
            media_type="text/markdown",
            byte_size=len(markdown_bytes),
        )
        return report_ref, markdown_ref

    def artifact_output_contract(
        self,
        invocation_id: str,
        *,
        allowed_media_types: tuple[str, ...],
        max_artifact_count: int = 16,
        max_total_bytes: int = 64 * 1024 * 1024,
    ) -> ArtifactOutputContract:
        name = validate_path_component(invocation_id, kind="analysis invocation id")
        return ArtifactOutputContract(
            output_directory_ref=f"staging/{name}",
            allowed_media_types=allowed_media_types,
            max_artifact_count=max_artifact_count,
            max_total_bytes=max_total_bytes,
        )

    def staging_directory(self, invocation_id: str) -> Path:
        name = validate_path_component(invocation_id, kind="analysis invocation id")
        path = self.root / "staging" / name
        path.mkdir(parents=True, exist_ok=False)
        return path

    def certify_artifacts(
        self,
        *,
        staging_directory: Path,
        declarations: tuple[ProducedArtifact, ...],
        contract: ArtifactOutputContract,
    ) -> tuple[CertifiedArtifactRef, ...]:
        if len(declarations) > contract.max_artifact_count:
            raise AnalysisPersistenceError("skill exceeded its artifact count limit")
        staging_root = staging_directory.resolve()
        observed: list[tuple[ProducedArtifact, Path, bytes]] = []
        total_bytes = 0
        logical_names: set[str] = set()
        for declaration in declarations:
            if declaration.logical_name in logical_names:
                raise AnalysisPersistenceError("skill emitted duplicate artifact logical names")
            logical_names.add(declaration.logical_name)
            if declaration.media_type not in contract.allowed_media_types:
                raise AnalysisPersistenceError(
                    f"skill artifact media type {declaration.media_type!r} is not allowed"
                )
            candidate = staging_root / declaration.relative_path
            current = candidate
            while current != staging_root:
                if current.is_symlink():
                    raise AnalysisPersistenceError(
                        "skill artifacts and their staging parents may not be symbolic links"
                    )
                current = current.parent
            path = candidate.resolve()
            if path == staging_root or staging_root not in path.parents:
                raise AnalysisPersistenceError("skill artifact path escapes staging")
            if not path.is_file():
                raise AnalysisPersistenceError(
                    f"declared artifact {declaration.relative_path!r} is missing relative to "
                    "output_directory; declare the exact relative path that was written"
                )
            payload = path.read_bytes()
            total_bytes += len(payload)
            if total_bytes > contract.max_total_bytes:
                raise AnalysisPersistenceError("skill exceeded its total artifact byte limit")
            observed.append((declaration, path, payload))

        refs: list[CertifiedArtifactRef] = []
        for declaration, _path, payload in observed:
            digest = hashlib.sha256(payload).hexdigest()
            suffix = Path(declaration.relative_path).suffix
            relative = Path("artifacts") / f"{digest}{suffix}"
            destination = self.root / relative
            try:
                publish_bytes_write_once(str(destination), payload)
            except FileExistsError:
                if destination.read_bytes() != payload:
                    raise AnalysisPersistenceError(
                        "content-addressed artifact collision has different bytes"
                    ) from None
            refs.append(
                CertifiedArtifactRef(
                    logical_ref=str(relative),
                    sha256=digest,
                    media_type=declaration.media_type,
                    byte_size=len(payload),
                )
            )
        return tuple(refs)

    def resolve_and_verify(self, ref: CertifiedArtifactRef) -> Path:
        path = (self.root / ref.logical_ref).resolve()
        root = self.root.resolve()
        if path == root or root not in path.parents:
            raise AnalysisPersistenceError("artifact ref escapes the analysis run root")
        payload = path.read_bytes()
        if ref.byte_size is not None and len(payload) != ref.byte_size:
            raise AnalysisPersistenceError("artifact byte size does not match its certified ref")
        if hashlib.sha256(payload).hexdigest() != ref.sha256:
            raise AnalysisPersistenceError("artifact digest does not match its certified ref")
        return path

    def cleanup_staging(self, staging_directory: Path) -> None:
        """Remove an executor-owned staging tree after artifacts are certified."""

        self._cleanup_executor_tree(staging_directory, root=self.root / "staging")

    def cleanup_materializations(self, materialization_directory: Path) -> None:
        """Remove verified private materialization copies after worker exit."""

        self._cleanup_executor_tree(materialization_directory, root=self.root / "materializations")

    @staticmethod
    def _cleanup_executor_tree(path: Path, *, root: Path) -> None:
        root = root.resolve()
        if not path.exists() and not path.is_symlink():
            return
        path = path.resolve()
        if root not in path.parents:
            raise AnalysisPersistenceError("refusing to clean a path outside executor storage")
        for child in sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if child.is_symlink() or child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        os.rmdir(path)
