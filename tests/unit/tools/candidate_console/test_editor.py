"""Authenticated editor routes preserve ordinary file authority and body bounds."""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.unit.tools.test_workflow_authoring import SOURCE
from tools.candidate_console.app import create_app
from tools.workflow_authoring.models import Project
from workflows.definition import TaskBinding


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
        assert client.get("/api/editor/task-choices", headers=headers).json() == {"choices": []}
        assert client.get("/api/choices", headers=headers).status_code == 200
        assert client.get("/editor.html").status_code == 200


def test_binding_draft_disconnect_promote_and_conflict(editor_config):
    """Real routes must not publish an unbound draft or bypass native promotion/conflicts."""
    from tests.unit.workflows.test_workflow_definition import definition
    from workflows.definition import WorkflowDocument
    from workflows.definition.source import render_workflow_source

    path = editor_config.editor_projects[0].source_file
    original = render_workflow_source(WorkflowDocument(definition=definition()))
    path.write_text(original)
    headers = {
        "Authorization": "Bearer " + open(editor_config.auth_token_file).read(),
        "Origin": editor_config.browser_origin,
    }
    with TestClient(create_app(editor_config), base_url=editor_config.browser_origin) as client:
        base = client.get("/api/editor/example", headers=headers).json()
        draft = {
            "base_document": base["document"],
            "bindings": [{"node": "implement", "argument": "output", "source": None}],
        }
        inspected = client.post(
            "/api/editor/example/draft",
            headers=headers,
            json={"expected_sha256": base["sha256"], "draft": draft},
        )
        assert inspected.status_code == 200, inspected.text
        assert inspected.json()["inspection"]["status"] == "incomplete"
        assert inspected.json()["inspection"]["document"] is None
        body = {"expected_sha256": base["sha256"], "proposal": {"kind": "draft", "draft": draft}}
        refused = client.post("/api/editor/example/review", headers=headers, json=body)
        assert refused.status_code == 409, refused.text
        assert "required input is unbound" in refused.text
        assert path.read_text() == original
        assert not tuple(editor_config.editor_projects[0].recovery_directory.iterdir())
        # A typed but incompatible source must still reach the native validator.
        draft["bindings"][0]["source"] = {"kind": "result", "node": "validate", "port": "result"}
        refused = client.post("/api/editor/example/review", headers=headers, json=body)
        assert refused.status_code == 409
        assert "requires proposal.output" in refused.text
        draft["bindings"][0]["source"]["node"] = "propose"
        review = client.post("/api/editor/example/review", headers=headers, json=body)
        assert review.status_code == 200, review.text
        assert review.json()["source"] == original  # Reconnection preserves argument order.
        path.write_text("# external edit\n" + original)
        stale = client.post(
            "/api/editor/example/draft",
            headers=headers,
            json={"expected_sha256": base["sha256"], "draft": draft},
        )
        assert stale.status_code == 409, stale.text
        assert path.read_text().startswith("# external edit")


def test_task_choice_metadata_is_safe_and_inert(editor_config, monkeypatch):
    """Fails if GET leaks target paths, inspects task content, or starts native observation."""
    pin = TaskBinding(
        package_id="synthetic",
        revision="snapshot-one",
        task_data_path_id="synthetic-path",
        semantic_fingerprint="a" * 64,
    )
    task = editor_config.tasks[0].model_copy(update={"task_revision": pin})
    app = create_app(editor_config.model_copy(update={"tasks": (task,)}))

    def forbidden(*args, **kwargs):
        pytest.fail("metadata GET reached native observation/content inspection")

    monkeypatch.setattr("tools.workflow_authoring.task_publication.observe_target", forbidden)
    monkeypatch.setattr("tools.workflow_authoring.task_observation.observe_composition", forbidden)
    read_bytes, read_text = Path.read_bytes, Path.read_text
    protected = {Path(task.task_manifest), Path(task.llm_config_file)}
    monkeypatch.setattr(
        Path, "read_bytes", lambda path: forbidden() if path in protected else read_bytes(path)
    )
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda path, *args, **kwargs: (
            forbidden() if path in protected else read_text(path, *args, **kwargs)
        ),
    )
    headers = {"Authorization": "Bearer " + Path(editor_config.auth_token_file).read_text()}
    with TestClient(app, base_url=editor_config.browser_origin) as client:
        assert client.get("/api/editor/task-choices").status_code == 401
        response = client.get("/api/editor/task-choices", headers=headers)
        assert response.status_code == 200
        assert response.json() == {
            "choices": [{"choice_id": task.task_id, "binding": pin.model_dump(mode="json")}]
        }
        assert client.get("/editor-task-controls.js").status_code == 200


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


STATIC = Path(__file__).resolve().parents[4] / "src/tools/candidate_console/static"
# Capability names from the paper's discovery-loop figure (docs/assets/discovery-loop.svg).
PAPER_LABELS = {
    "interpretation": "INTERPRET",
    "literature": "LITERATURE",
    "proposal": "PROPOSE",
    "implementation": "IMPLEMENT",
    "validation": "VALIDATE",
    "tuning": "TRAIN & TUNE",
}


def presentation_entries() -> dict[str, tuple[str, str]]:
    """Parse ``{capability: (label, role)}`` from the browser's presentation table."""
    script = (STATIC / "editor-capability-presentation.js").read_text()
    block = re.search(r"const entries = Object\.freeze\(\{\n(.*?)\n  \}\);", script, re.S)
    assert block, "presentation entries table not found"
    rows = block.group(1).splitlines()
    parsed = [re.match(r"    (\w+): \{label: '([^']+)', role: '([^']+)'", row) for row in rows]
    assert all(parsed), f"unparsed presentation rows: {rows}"
    return {match[1]: (match[2], match[3]) for match in parsed if match}


def test_every_catalog_capability_has_its_paper_label_and_theme_role():
    """Fails if a catalog capability renders the generic CAPABILITY fallback (the
    interpretation gap), carries a non-paper name, or has no card style/theme tokens."""
    from workflows.definition.catalog import CAPABILITIES

    assert set(CAPABILITIES) == set(PAPER_LABELS)
    entries = presentation_entries()
    assert {name: label for name, (label, _) in entries.items()} == PAPER_LABELS
    card_css = (STATIC / "editor.css").read_text()
    theme = (STATIC / "theme.css").read_text()
    for capability, (_, role) in entries.items():
        assert role == capability
        assert f".circuit-card.capability-{role} {{" in card_css, role
        # One accent and one tint in each of the light and dark themes.
        assert theme.count(f"--capability-{role}:") == 2, role
        assert theme.count(f"--capability-{role}-tint:") == 2, role


def contract_presentation_entries() -> dict[str, tuple[str, str, str]]:
    """Parse ``{contract: (name, colour, shape)}`` from the browser's contract table."""
    script = (STATIC / "editor-contract-presentation.js").read_text()
    block = re.search(r"const entries = Object\.freeze\(\{\n(.*?)\n  \}\);", script, re.S)
    assert block, "contract presentation table not found"
    rows = block.group(1).splitlines()
    pattern = r"    '([^']+)': \{name: '([^']+)', colour: '([^']+)', shape: '([^']+)'\},"
    parsed = [re.fullmatch(pattern, row) for row in rows]
    assert all(parsed), f"unparsed contract rows: {rows}"
    return {match[1]: (match[2], match[3], match[4]) for match in parsed if match}


def test_every_catalog_contract_has_a_distinct_port_token_in_both_themes():
    """Fails if a catalog contract falls back to a hash token (which can collide), two
    contracts share a colour+shape or a readable name, or a colour lacks a CSS token."""
    from workflows.definition.catalog import CONTRACTS

    entries = contract_presentation_entries()
    assert set(entries) == set(CONTRACTS)
    tokens = [(colour, shape) for _, colour, shape in entries.values()]
    assert len(set(tokens)) == len(tokens)
    names = [name for name, _, _ in entries.values()]
    assert len(set(names)) == len(names)
    css = (STATIC / "editor-contract-presentation.css").read_text()
    for colour in {colour for colour, _ in tokens}:
        assert f"--contract-{colour}:" in css, colour
    for shape in {shape for _, shape in tokens}:
        assert f'.circuit-port[data-contract-shape="{shape}"] .circuit-socket' in css, shape
    # Literal colours (not theme aliases) need a dark-theme value too.
    light, dark = css.split(':root[data-theme="dark"]', 1)
    for literal in re.findall(r"(--contract-[\w-]+): #", light):
        assert f"{literal}: #" in dark, literal


def test_every_index_asset_is_served(console_config):
    """Fails if index.html references a static script or stylesheet the asset allowlist
    does not serve (the editor would load without it and break at runtime)."""
    index = (STATIC / "index.html").read_text()
    assets = re.findall(r'(?:src|href)="/([\w.-]+\.(?:js|css))"', index)
    assert "editor-contract-presentation.js" in assets
    with TestClient(create_app(console_config), base_url=console_config.browser_origin) as client:
        for asset in assets:
            assert client.get("/" + asset).status_code == 200, asset


def test_five_node_browser_fixture_saves_every_node_position():
    """Fails if the layout witness fixture stops parsing as the five-node authored loop
    or leaves a node to fallback placement instead of its saved coordinates."""
    from tests.browser.workflow_editor_server import five_node_source
    from workflows.definition import WorkflowDocument, parse_workflow_source

    document = parse_workflow_source(five_node_source())
    assert isinstance(document, WorkflowDocument)
    assert [node.capability for node in document.definition.nodes] == [
        "interpretation",
        "proposal",
        "implementation",
        "validation",
        "tuning",
    ]
    assert document.definition.loop is not None
    assert document.definition.loop.feedback.target == "interpret"
    assert sorted(position.node for position in document.positions) == sorted(
        node.id for node in document.definition.nodes
    )


def test_research_loop_add_limit_remove_round_trip_over_editor_routes(editor_config):
    """Fails if a GUI loop edit bypasses typed review/validation, drifts other source
    bytes (``2.0`` -> ``2`` via browser JSON) or keeps a removed loop."""
    from tests.browser.workflow_editor_server import interpretation_profile_source
    from workflows.definition import ReusableWorkflowDocument, parse_workflow_source
    from workflows.definition.source import render_workflow_source

    path = editor_config.editor_projects[0].source_file
    looped = parse_workflow_source(interpretation_profile_source())
    assert isinstance(looped, ReusableWorkflowDocument)
    plain_document = looped.model_copy(
        update={"definition": looped.definition.model_copy(update={"loop": None})}
    )
    plain = render_workflow_source(plain_document)
    assert "'trial_time_budget_minutes': 2.0" in plain  # a float JSON clients lose
    headers = {
        "Authorization": "Bearer " + open(editor_config.auth_token_file).read(),
        "Origin": editor_config.browser_origin,
    }
    feedback = {
        "source": {"kind": "result", "node": "fit", "port": "result"},
        "target": "interpret",
        "protocol": "tuning-to-interpretation",
        "history": "native-research/v1",
    }
    with TestClient(create_app(editor_config), base_url=editor_config.browser_origin) as client:

        def review(loop):
            base = client.get("/api/editor/example", headers=headers).json()
            proposal = {"kind": "loop", "source": base["source"], "loop": loop}
            body = {"expected_sha256": base["sha256"], "proposal": proposal}
            return base, client.post("/api/editor/example/review", headers=headers, json=body)

        def review_and_save(loop):
            base, response = review(loop)
            assert response.status_code == 200, response.text
            view = response.json()
            saved = client.post(
                "/api/editor/example/save",
                headers=headers,
                json={
                    "expected_sha256": base["sha256"],
                    "proposal_sha256": view["sha256"],
                    "source": view["source"],
                },
            )
            assert saved.status_code == 200, saved.text
            return view, saved.json()

        # A graph without one tuning/interpretation pair offers no one-click loop.
        assert "loop_template" not in client.get("/api/editor/example", headers=headers).json()
        path.write_text(plain)
        base = client.get("/api/editor/example", headers=headers).json()
        assert "loop" not in base["document"]["definition"]
        assert base["loop_template"] == {"final_iteration": 1, "feedback": feedback}

        # Saving a non-loop declaration without loop edits keeps exact bytes.
        view, saved = review_and_save(None)
        assert (view["diff"], saved["unchanged"], path.read_text()) == ("", True, plain)

        # Add the server template with an edited limit; nothing else changes.
        view, _ = review_and_save({**base["loop_template"], "final_iteration": 3})
        assert "final_iteration=3" in view["diff"]
        assert "2.0" not in "".join(
            line for line in view["diff"].splitlines(True) if line.startswith(("-", "+"))
        )
        saved_document = parse_workflow_source(path.read_text())
        assert saved_document.model_dump(mode="json")["definition"]["loop"] == {
            "final_iteration": 3,
            "feedback": feedback,
        }
        assert (
            saved_document.model_copy(
                update={"definition": saved_document.definition.model_copy(update={"loop": None})}
            )
            == plain_document
        )

        # Invalid limits and endpoints are refused by the declaration; disk is untouched.
        looped_bytes = path.read_bytes()
        for invalid in (0, -1, 2.5, "4", True, None):
            _, refused = review({"final_iteration": invalid, "feedback": feedback})
            assert refused.status_code == 422, (invalid, refused.text)
        _, refused = review(
            {"final_iteration": 2, "feedback": {**feedback, "target": "hypothesis"}}
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["diagnostics"][0]["field_path"] == ["definition"]
        assert path.read_bytes() == looped_bytes

        # Saving a loop declaration without edits keeps exact bytes; then edit the limit.
        view, saved = review_and_save({"final_iteration": 3, "feedback": feedback})
        assert (view["diff"], saved["unchanged"], path.read_bytes()) == ("", True, looped_bytes)
        review_and_save({"final_iteration": 5, "feedback": feedback})
        assert parse_workflow_source(path.read_text()).definition.loop.final_iteration == 5

        # Removing the loop restores the original non-loop bytes and declaration digest.
        review_and_save(None)
        assert path.read_text() == plain
        assert (
            parse_workflow_source(path.read_text()).declaration_digest()
            == plain_document.declaration_digest()
        )
        reopened = client.get("/api/editor/example", headers=headers).json()
        assert "loop" not in reopened["document"]["definition"]


def test_research_loop_stop_conditions_review_refuse_and_restore_bytes(editor_config):
    """Fails if a GUI stop-condition edit bypasses the typed declaration (invalid k,
    missing metric id, duplicate kind or the reserved judge reach disk), if a
    condition-free loop's bytes drift, or if add-then-remove does not restore them."""
    from tests.browser.workflow_editor_server import interpretation_profile_source
    from workflows.definition import parse_workflow_source

    path = editor_config.editor_projects[0].source_file
    path.write_text(interpretation_profile_source())
    headers = {
        "Authorization": "Bearer " + open(editor_config.auth_token_file).read(),
        "Origin": editor_config.browser_origin,
    }
    threshold = {"kind": "metric_threshold", "metric_id": "accuracy", "threshold": 0.85}
    patience = {"kind": "no_improvement", "completed_bodies": 1}
    with TestClient(create_app(editor_config), base_url=editor_config.browser_origin) as client:
        base = client.get("/api/editor/example", headers=headers).json()
        loop = base["document"]["definition"]["loop"]
        assert loop["final_iteration"] == 2 and "stop_conditions" not in loop

        def review(stops):
            current = client.get("/api/editor/example", headers=headers).json()
            proposal = {
                "kind": "loop",
                "source": current["source"],
                "loop": {**loop, "stop_conditions": stops},
            }
            body = {"expected_sha256": current["sha256"], "proposal": proposal}
            return current, client.post("/api/editor/example/review", headers=headers, json=body)

        def review_and_save(stops):
            current, response = review(stops)
            assert response.status_code == 200, response.text
            view = response.json()
            saved = client.post(
                "/api/editor/example/save",
                headers=headers,
                json={
                    "expected_sha256": current["sha256"],
                    "proposal_sha256": view["sha256"],
                    "source": view["source"],
                },
            )
            assert saved.status_code == 200, saved.text
            return view

        original = path.read_bytes()
        # An explicit empty list is the same declaration: no bytes move.
        assert review_and_save([])["diff"] == "" and path.read_bytes() == original

        # Each refusal is typed by the layer that owns it; the file is untouched.
        # Per-condition shape is refused by the request schema before any source work.
        for invalid in (
            [{"kind": "no_improvement", "completed_bodies": 0}],
            [{"kind": "no_improvement", "completed_bodies": 1.5}],
            [{"kind": "metric_threshold", "threshold": 0.85}],
            [{**threshold, "metric_id": ""}],
            [{**threshold, "threshold": "0.85"}],
            [{"kind": "judge"}],
        ):
            _, refused = review(invalid)
            assert refused.status_code == 422, (invalid, refused.text)
            assert refused.json()["error"]["code"] == "validation", (invalid, refused.text)
        # Cross-field rules (k below the final iteration, one condition per kind) are
        # refused by the declaration, located at the definition, not as a source error.
        for invalid in (
            [{"kind": "no_improvement", "completed_bodies": 2}],  # == final_iteration
            [threshold, {**threshold, "threshold": 0.9}],
        ):
            _, refused = review(invalid)
            assert refused.status_code == 422, (invalid, refused.text)
            body = refused.json()
            assert body["error"]["code"] == "source", (invalid, refused.text)
            assert [(item["code"], item["field_path"]) for item in body["diagnostics"]] == [
                ("validation", ["definition"])
            ], (invalid, refused.text)
        assert path.read_bytes() == original

        # Add both kinds: only the loop's stop conditions (and their constructors) move.
        view = review_and_save([threshold, patience])
        added = [line for line in view["diff"].splitlines() if line.startswith("+ ")]
        assert any("MetricThresholdStop(" in line for line in added), view["diff"]
        assert any("NoImprovementStop(" in line for line in added), view["diff"]
        assert not any(
            line.startswith("-") and not line.startswith("---")
            for line in view["diff"].splitlines()
        )
        saved = parse_workflow_source(path.read_text()).model_dump(mode="json")
        assert saved["definition"]["loop"]["stop_conditions"] == [threshold, patience]

        # Remove one, then the other: the condition-free bytes return exactly.
        review_and_save([patience])
        assert "MetricThresholdStop" not in path.read_text()
        review_and_save([])
        assert path.read_bytes() == original


def test_loop_proposal_against_a_stale_source_version_is_a_conflict(editor_config):
    """Fails if a loop proposal is reviewed against bytes other than the current file:
    an outdated ``expected_sha256`` must refuse with ``conflict`` and write nothing."""
    from tests.browser.workflow_editor_server import interpretation_profile_source

    path = editor_config.editor_projects[0].source_file
    path.write_text(interpretation_profile_source())
    headers = {
        "Authorization": "Bearer " + open(editor_config.auth_token_file).read(),
        "Origin": editor_config.browser_origin,
    }
    with TestClient(create_app(editor_config), base_url=editor_config.browser_origin) as client:
        stale = client.get("/api/editor/example", headers=headers).json()
        path.write_text(path.read_text() + "\n")  # another writer changes the file
        current = path.read_bytes()
        response = client.post(
            "/api/editor/example/review",
            headers=headers,
            json={
                "expected_sha256": stale["sha256"],
                "proposal": {
                    "kind": "loop",
                    "source": stale["source"],
                    "loop": stale["document"]["definition"]["loop"],
                },
            },
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "conflict"
        assert path.read_bytes() == current


def test_interpretation_fixture_saves_complete_disjoint_positions():
    """Fails if the browser ``interpretation`` fixture again leaves a node to fallback
    placement or saves cards closer than one card width plus gap (the UX walkthrough
    of 2026-10-27 showed interpret at x=-80 under build at x=120 and two cards off
    to the right). CI runs no browser, so this pins the fixture data itself."""
    from itertools import pairwise

    from tests.browser.workflow_editor_server import interpretation_profile_source
    from workflows.definition import parse_workflow_source

    document = parse_workflow_source(interpretation_profile_source())
    nodes = {node.id for node in document.definition.nodes}
    positions = {position.node: (position.x, position.y) for position in document.positions}
    assert set(positions) == nodes
    # editor.css owns a 215 px card; 300 px leaves a routing channel between columns.
    placed = sorted(positions.values())
    for (x1, y1), (x2, y2) in pairwise(placed):
        assert x2 - x1 >= 300 or abs(y2 - y1) >= 600, (placed, (x1, y1), (x2, y2))
