"""Native capture policy over shared, receipt-free launch expectations."""

from contextlib import contextmanager

from pydantic import Field

from workflows.launch_expectations import LaunchExpectations
from workflows.reviewed_launch_binding import (
    InputFilePin,
    ReviewedLaunchRefusal,
    file_pin,
    verify_binding,
)


class NativeChainCaptureRefusal(ReviewedLaunchRefusal):
    """Capture refusal bypasses scientific-failure persistence and exits 78."""


@contextmanager
def _native_refusals():
    try:
        yield
    except ReviewedLaunchRefusal as error:
        raise NativeChainCaptureRefusal(str(error)) from error


class NativeChainLaunchContext(LaunchExpectations):
    iteration: int = Field(gt=0, strict=True)
    final_iteration: int = Field(gt=0, strict=True)
    run_name: str
    source_pin: InputFilePin

    def check_entry(self, args) -> None:
        with _native_refusals():
            super().check_entry(args)
            if (
                args.start_iteration != self.iteration
                or not 1 <= self.iteration <= self.final_iteration
            ):
                raise ReviewedLaunchRefusal("iteration_changed")
            if args.run_name != self.run_name:
                raise ReviewedLaunchRefusal("run_name_changed")

    def check_composition(self, composition) -> None:
        with _native_refusals():
            super().check_composition(composition)

    def resolve_watchdog(self, args):
        with _native_refusals():
            return super().resolve_watchdog(args)

    def check_invariants(self, invariants, llm_config, identity) -> None:
        with _native_refusals():
            super().check_invariants(invariants, llm_config, identity)

    def check_launch(self, launch, restored_state) -> None:
        with _native_refusals():
            if (
                launch.start_iteration != self.iteration
                or not 1 <= self.iteration <= self.final_iteration
                or launch.max_iterations != 1
                or launch.validation_fixed_candidate_plan is not None
            ):
                raise ReviewedLaunchRefusal("native_recipe_changed")
            paths = list(restored_state.resolved_source_paths)
            if launch.source_paths != paths:
                raise ReviewedLaunchRefusal("restoration_paths_changed")
            expected = dict(self.launch_settings)
            expected["start_iteration"] = self.iteration
            expected["source_paths"] = paths
            self.check_projection(launch, expected)
            verify_binding(self.binding)
            if file_pin(self.source_pin.path, self.binding.file_max_bytes) != self.source_pin:
                raise ReviewedLaunchRefusal("source_changed")
