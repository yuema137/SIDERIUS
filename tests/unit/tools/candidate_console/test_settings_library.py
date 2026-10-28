"""Write-once library uploads and the owner-derived profile/advice cards."""

import json
import stat
from pathlib import Path

import pytest

from tests.unit.tools.candidate_console.test_settings_page import (
    _client,
    _load,
    _put,
    workspace,
)

REPO = Path(__file__).resolve().parents[4]


def _files(root: Path, kind: str) -> set[str]:
    return {path.name for path in (root / "library" / kind).iterdir()}


@pytest.mark.parametrize(
    ("kind", "content", "message"),
    [
        ("llm", '{"interpet": {}}', "Not an LLM profile: llm_config: unknown configuration keys"),
        ("advice", '{"propse": "x"}', "'propse'"),
        ("advice", "{}", "carries no recognised advice key"),
    ],
)
def test_invalid_uploads_are_refused_before_any_write(kind, content, message, workspace):
    """Defect: a typo profile or unconsumable advice file lands in the library."""
    before = _files(workspace, kind)
    response = _client(_load(workspace)).post(
        "/api/settings/library", json={"kind": kind, "label": "Mine", "content": content}
    )
    assert response.status_code == 422 and message in response.json()["error"]["message"]
    assert _files(workspace, kind) == before


def test_uploads_are_write_once_and_idempotent(workspace):
    """Defect: a re-upload duplicates or replaces a library file the settings reference."""
    api = _client(_load(workspace))
    content = json.dumps({"propose": "Explain the evidence.", "_note": "inert"})
    first = api.post(
        "/api/settings/library", json={"kind": "advice", "label": "My Notes!", "content": content}
    )
    assert first.status_code == 200, first.text
    ref = first.json()
    path = workspace / "library" / "advice" / ref["name"]
    assert ref["name"] == f"my-notes-{ref['sha256'][:12]}.json"
    assert path.read_text() == content and stat.S_IMODE(path.stat().st_mode) == 0o600
    again = api.post(
        "/api/settings/library", json={"kind": "advice", "label": "My Notes!", "content": content}
    )
    assert again.json() == ref and _files(workspace, "advice") == {ref["name"]}

    path.write_text(json.dumps({"propose": "tampered"}))  # same name, different bytes
    clash = api.post(
        "/api/settings/library", json={"kind": "advice", "label": "My Notes!", "content": content}
    )
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "exists"
    assert json.loads(path.read_text()) == {"propose": "tampered"}


def test_uploaded_file_is_selectable_and_survives_restart(workspace):
    """Defect: an uploaded ref cannot be selected, or unusable advice keys are hidden."""
    api = _client(_load(workspace))
    content = json.dumps({"implement": "Keep the model small.", "mindset": "Be careful."})
    ref = api.post(
        "/api/settings/library", json={"kind": "advice", "label": "notes", "content": content}
    ).json()
    view = api.get("/api/settings").json()
    (card,) = [card for card in view["advice_files"] if card["ref"] == ref]
    assert card["present_keys"] == ["implement", "mindset"]
    assert card["unsupported_keys"] == ["mindset"]  # shown, never silently dropped
    saved = _put(
        api, view["settings_sha256"], llm_profile=view["pending"]["llm_profile"], advice=ref
    )
    assert saved.status_code == 200, saved.text
    active = _load(workspace).settings.settings
    assert active is not None and active.advice is not None
    assert active.advice.model_dump() == ref


def test_default_profile_card_names_routes_and_required_keys(workspace):
    """Defect: the card hides which provider keys the shipped default needs."""
    view = _client(_load(workspace)).get("/api/settings").json()
    (default,) = [
        card for card in view["llm_profiles"] if card["ref"]["name"].startswith("default-")
    ]
    library = workspace / "library" / "llm" / default["ref"]["name"]
    assert library.read_bytes() == (REPO / "configs/llm/default.json").read_bytes()
    assert "OPENAI_API_KEY" in default["required_names"]
    assert {route["name"].partition(".")[0] for route in default["routes"]} >= {
        "propose",
        "implement",
    }


def test_upload_requires_a_writable_console(workspace):
    """Defect: a read-only console still lets the browser add library files."""
    config = workspace / "settings" / "console.json"
    config.write_text(
        json.dumps(
            json.loads(config.read_text()) | {"global_settings": {"browser_writable": False}}
        )
    )
    before = _files(workspace, "llm")
    response = _client(_load(workspace)).post(
        "/api/settings/library", json={"kind": "llm", "label": "x", "content": "{}"}
    )
    assert response.status_code == 403 and _files(workspace, "llm") == before


def test_inert_profile_secrets_are_never_echoed(workspace):
    """Defect: an upload response or the settings view returns profile file contents.

    A profile may carry an inert ``_``-prefixed block; the console shows routes and
    credential names only, never the stored text.
    """
    api = _client(_load(workspace))
    secret = "sk-DO-NOT-ECHO-0123456789"
    content = json.dumps({"_api_key": secret})
    upload = api.post(
        "/api/settings/library", json={"kind": "llm", "label": "mine", "content": content}
    )
    assert upload.status_code == 200, upload.text
    assert secret not in upload.text
    view = api.get("/api/settings")
    assert any(card["ref"] == upload.json() for card in view.json()["llm_profiles"])
    assert secret not in view.text
