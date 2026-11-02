"""Browser fixture: an ``init`` workspace (browser setup creation on) with one synthetic task.

Prints ``{"origin", "token", "workspace"}`` and serves the console until killed. No setup
exists at start; the witness creates them through the browser (``POST /api/tasks/.../setups``).
Native preparation is never started here.
"""

import json
import socket
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import uvicorn

from tests.browser.fixture_metadata import emit_metadata
from tests.unit.tools.candidate_console.conftest import console_config
from tests.unit.tools.candidate_console.test_settings_page import workspace
from tests.unit.tools.candidate_prepare.conftest import selection
from tools.candidate_console.app import create_app
from tools.candidate_console.config import load_console


def error_projections() -> None:
    """Inject private failures only in the explicit offline error witness process."""
    from types import SimpleNamespace

    from tools.setup_review.composition_models import CompositionResult

    def observe(job, task):
        return SimpleNamespace(
            result=CompositionResult.failed(
                job, "composition", ValueError("private-browser-secret-sentinel")
            )
        )

    patch("tools.candidate_console.task_summary.observe", observe).start()
    from tests.unit.tools.candidate_console.test_editor_errors import failed_review
    from tools.candidate_console.setups import check_setup_project
    from tools.workflow_authoring.service import WorkflowAuthoring

    original_review = WorkflowAuthoring.review

    def check(project, config):
        if project.project_id == "failed-setup":
            raise ValueError("private-browser-secret-sentinel")
        return check_setup_project(project, config)

    def review(service, request):
        return failed_review(
            original_review(service, request),
            service.project.project_root,
            "private-browser-secret-sentinel",
        )

    patch("tools.candidate_console.setups.check_setup_project", check).start()
    patch.object(WorkflowAuthoring, "review", review).start()


def main() -> None:
    if "--error-projections" in sys.argv:
        error_projections()
    with tempfile.TemporaryDirectory(prefix="siderius-setups-browser-") as directory:
        tmp = Path(directory)
        (tmp / "base").mkdir()
        base = console_config.__wrapped__(selection.__wrapped__(tmp / "base"), tmp / "base")
        root = workspace.__wrapped__(base, tmp)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        path = root / "settings" / "console.json"
        document = json.loads(path.read_text())
        document |= {"port": port, "browser_origin": f"http://127.0.0.1:{port}"}
        # Reusable runs enabled: the task's run folder is derived from the workspace.
        for task in document["tasks"]:
            task.pop("reusable_runs_root", None)
        (root / "runs" / "synthetic").mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(json.dumps(document))
        resolved = load_console(str(path))
        config = resolved.config
        emit_metadata(
            {
                "origin": config.browser_origin,
                "token": Path(config.auth_token_file).read_text(),
                "workspace": str(root),
            }
        )
        uvicorn.run(
            create_app(config, resolved.settings),
            host="127.0.0.1",
            port=port,
            proxy_headers=False,
            access_log=False,
            log_level="error",
        )


if __name__ == "__main__":
    main()
