"""Configured native-chain consumer; recovery precedes every mutable-input read."""

from pathlib import Path
from uuid import uuid4

from tools.candidate_operations import (
    NativeChainAdmission,
    NativeChainOperation,
    OperationHandle,
    lookup_operation_request,
    operation_request_digest,
    review_native_chain_operation,
)
from tools.candidate_operations.models import OperationFailure
from tools.workflow_authoring.versions import version_record_path

from .files import credentials
from .native_chain_models import (
    NativeChainChoice,
    NativeChainChoiceSelection,
    NativeChainChoiceView,
    NativeChainLaunchSelection,
    NativeChainReviewView,
)
from .readiness import named_credential_readiness
from .seed_labels import review_label
from .service import CandidateConsole


def check_editor_separation(
    console: CandidateConsole, choice: NativeChainChoice, admission: NativeChainAdmission
) -> None:
    """Protect pinned inputs and output directories from actual authoring write targets."""
    inputs = [Path(choice.request.capture_path), *(Path(f.path) for f in admission.input_files)]
    destinations = [Path(choice.request.envelope), Path(admission.workspace)]
    # Read live: a setup created after startup is protected like a configured one.
    for project in console.setups.projects():
        source = project.source_file
        files = (
            source,
            source.with_name(f".{source.name}.authoring.lock"),
            version_record_path(source),
        )
        recovery = project.recovery_directory
        pinned_overlap = any(p in files or p.is_relative_to(recovery) for p in inputs)
        output_overlap = any(
            recovery.is_relative_to(d)
            or d.is_relative_to(recovery)
            or any(f.is_relative_to(d) or d.is_relative_to(f) for f in files)
            for d in destinations
        )
        if pinned_overlap or output_overlap:
            raise OperationFailure("native_chain_policy", "native choice overlaps authoring writes")


class NativeChainConsole:
    def __init__(self, console: CandidateConsole):
        self.console = console

    def choices(self) -> tuple[NativeChainChoiceView, ...]:
        return tuple(
            NativeChainChoiceView(choice_id=c.choice_id, label=c.label)
            for c in self.console.config.native_chain_choices
        )

    def _choice(self, choice_id: str) -> NativeChainChoice:
        choice = next(
            (c for c in self.console.config.native_chain_choices if c.choice_id == choice_id), None
        )
        if choice is None:
            raise OperationFailure("native_chain_policy", "unknown configured native choice")
        return choice

    def review(self, selection: NativeChainChoiceSelection) -> NativeChainReviewView:
        selection = NativeChainChoiceSelection.model_validate_json(selection.model_dump_json())
        choice = self._choice(selection.choice_id)
        submission = NativeChainOperation(request_id=uuid4(), request=choice.request)
        admission = review_native_chain_operation(self.console.config.operation_store, submission)
        check_editor_separation(self.console, choice, admission)
        return NativeChainReviewView(
            choice_id=choice.choice_id,
            label=choice.label,
            request_digest=operation_request_digest(submission),
            admission=admission,
            **choice.request.model_dump(exclude={"capture_sha256"}),
            credential_readiness=named_credential_readiness(
                admission.required_environment_names,
                choice.request.environment_names,
                self.console.config.credential_file,
            ),
            seed=review_label(admission.run_seed),
        )

    def launch(self, selection: NativeChainLaunchSelection) -> OperationHandle:
        selection = NativeChainLaunchSelection.model_validate_json(selection.model_dump_json())
        store = self.console.config.operation_store
        prior = lookup_operation_request(store, selection.operation_id)
        if prior is not None:
            if (
                prior.kind != "native_chain"
                or operation_request_digest(prior) != selection.expected_request_digest
            ):
                raise OperationFailure("conflict", "operation identity differs")
            return self.console.submit(prior, launch_environment={})
        choice = self._choice(selection.choice_id)
        submission = NativeChainOperation(request_id=selection.operation_id, request=choice.request)
        if operation_request_digest(submission) != selection.expected_request_digest:
            raise OperationFailure("stale_review", "configured request changed")
        admission = review_native_chain_operation(store, submission)
        check_editor_separation(self.console, choice, admission)
        environment = credentials(
            self.console.config.credential_file, choice.request.environment_names
        )
        # Native chains are never reserved in the host ledger: they run serially.
        return self.console.submit(submission, launch_environment=environment)
