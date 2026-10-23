"""Setup-specific launch receipt publication; comparisons share native expectations."""

from pydantic import JsonValue

from core.durable_io import publish_bytes_write_once
from workflows.launch_expectations import LaunchExpectations
from workflows.reviewed_launch_binding import verify_binding


class ReviewedLaunchContext(LaunchExpectations):
    receipt_path: str
    receipt_fields: dict[str, JsonValue]

    def check_launch(self, launch) -> None:
        self.check_projection(launch, self.launch_settings)
        verify_binding(self.binding)
        self.publish("matched")

    def publish(self, outcome: str, reason: str | None = None) -> None:
        import json

        payload = {**self.receipt_fields, "outcome": outcome, "reason": reason}
        publish_bytes_write_once(self.receipt_path, (json.dumps(payload, indent=2) + "\n").encode())
