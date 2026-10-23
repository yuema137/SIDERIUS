"""Authenticated editor routes preserve ordinary file authority and body bounds."""

import json

import pytest
from fastapi.testclient import TestClient

from tests.unit.tools.test_workflow_authoring import SOURCE
from tools.candidate_console.app import create_app
from tools.workflow_authoring.models import Project


@pytest.fixture
def editor_config(console_config, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = root / "workflow.py"
    source.write_text(SOURCE)
    recovery = root / "recovery"
    recovery.mkdir(mode=0o700)
    project = Project(
        project_id="example", project_root=root, source_file=source, recovery_directory=recovery
    )
    return console_config.model_copy(update={"editor_projects": (project,)})


def test_real_http_editor_save_and_admission(editor_config):
    """Fails if router bypasses console auth, changes destination, or loses source bytes."""
    app = create_app(editor_config)
    headers = {
        "Authorization": "Bearer " + open(editor_config.auth_token_file).read(),
        "Origin": editor_config.browser_origin,
        "Content-Type": "application/json",
    }
    with TestClient(app, base_url=editor_config.browser_origin) as client:
        assert client.get("/api/editor/example").status_code == 401
        base = client.get("/api/editor/example", headers=headers).json()
        proposed = SOURCE.replace("old.json", "gui.json")
        review = client.post(
            "/api/editor/example/review",
            headers=headers,
            json={
                "expected_sha256": base["sha256"],
                "proposal": {"kind": "source", "source": proposed},
            },
        )
        assert review.status_code == 200, review.text
        view = review.json()
        saved = client.post(
            "/api/editor/example/save",
            headers=headers,
            json={
                "expected_sha256": base["sha256"],
                "proposal_sha256": view["sha256"],
                "source": view["source"],
            },
        )
        assert saved.status_code == 200
        assert editor_config.editor_projects[0].source_file.read_text() == proposed
        assert client.get("/api/editor/unknown", headers=headers).status_code == 404
        assert (
            client.post(
                "/api/editor/example/save",
                headers=headers,
                json={"path": "/tmp/unapproved", "source": proposed},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/editor/example/review",
                headers=headers,
                json={
                    "expected_sha256": view["sha256"],
                    "proposal": {"kind": "source", "source": "x" * 32769},
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/editor/example/review", headers=headers, content=b"x" * 262145
            ).status_code
            == 413
        )
        assert (
            client.post("/api/editor/example/review", headers=headers, content="{").status_code
            == 422
        )


def test_empty_editor_selection_keeps_existing_console(console_config):
    """Old configs do not create source prerequisites for operations access."""
    headers = {"Authorization": "Bearer " + open(console_config.auth_token_file).read()}
    with TestClient(create_app(console_config), base_url=console_config.browser_origin) as client:
        assert client.get("/api/editor/projects", headers=headers).json() == []
        assert client.get("/api/choices", headers=headers).status_code == 200
        assert client.get("/editor.html").status_code == 200


def test_oversized_source_is_bounded_unavailable_not_console_startup_failure(editor_config):
    """A configured oversized file must return typed failure without truncating or hiding monitoring."""
    editor_config.editor_projects[0].source_file.write_bytes(b"x" * 32769)
    headers = {"Authorization": "Bearer " + open(editor_config.auth_token_file).read()}
    with TestClient(create_app(editor_config), base_url=editor_config.browser_origin) as client:
        response = client.get("/api/editor/example", headers=headers)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "limit"
        assert "source" not in response.json()
        assert client.get("/api/choices", headers=headers).status_code == 200
