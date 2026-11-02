"""Prevent browser profile drift and source-level duplication of the identifier."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tools.candidate_console.app import create_app

SOURCE = Path(__file__).resolve().parents[4] / "src"


@pytest.mark.parametrize(
    "profile",
    (
        "native-interpretation-candidate/v1",
        "native-literature-candidate/v1",
        "native-proposal-families/v1",
        "native-proposal-fanout/v1",
    ),
)
def test_profile_literal_has_one_source_owner(profile):
    """Reverting any consumer to a literal defeats the shared owner."""
    owners = {
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*")
        if path.suffix in {".py", ".js"} and profile in path.read_text()
    }
    assert owners == {"workflows/definition/models.py"}


def test_browser_profile_binding_precedes_consumers(console_config):
    """A missing route/load order breaks both browser consumers despite valid schemas."""
    with TestClient(create_app(console_config), base_url=console_config.browser_origin) as client:
        response = client.get("/execution-profiles.js")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/javascript")
        assert response.text == (
            "window.executionProfiles = Object.freeze("
            '{"nativeInterpretation": "native-interpretation-candidate/v1", '
            '"nativeLiterature": "native-literature-candidate/v1", '
            '"nativeProposalFamilies": "native-proposal-families/v1"});\n'
        )
        index = client.get("/").text
        for consumer in ("editor-loop-controls.js", "reusable-run.js"):
            assert index.index("/execution-profiles.js") < index.index("/" + consumer)
            assert (
                "window.executionProfiles.nativeInterpretation" in client.get("/" + consumer).text
            )
        reusable_run = client.get("/reusable-run.js").text
        for name in ("nativeLiterature", "nativeProposalFamilies"):
            assert f"window.executionProfiles.{name}" in reusable_run
