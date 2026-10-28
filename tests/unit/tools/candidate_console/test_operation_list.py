"""Operation list route: authenticated, read-only and free of host paths."""

from tests.unit.tools.candidate_console.test_http import client
from tools.candidate_console.models import OperationListView


def test_list_route_requires_auth_and_leaks_no_paths(prepared, tmp_path):
    """Fails if the list bypasses the bearer boundary or projects receipts/paths."""
    service, selection, _ = prepared
    api = client(service.config)
    assert api.get("/api/operations", headers={"Authorization": ""}).status_code == 401
    assert api.get("/api/operations?limit=0").status_code == 422
    assert api.get("/api/operations?limit=201").status_code == 422
    response = api.get("/api/operations")
    assert response.status_code == 200, response.text
    body = response.json()
    OperationListView.model_validate_json(response.text)  # the route serves the typed list view
    assert [item["operation_id"] for item in body["operations"]] == [str(selection.operation_id)]
    item = body["operations"][0]
    assert (item["kind"], item["run_name"], item["state"], item["native_status"]) == (
        "prepare",
        "example",
        "completed",
        "prepared",
    )
    assert body["unreadable"] == 0
    # The prepared receipt carries output/log paths; none may reach the list.
    assert str(tmp_path) not in response.text
    assert "receipt" not in response.text and "request_digest" not in response.text
