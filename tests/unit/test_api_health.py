"""Tests for the API application factory and the health endpoint.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import create_app
from api.routers.health import SERVICE_NAME


def test_create_app_returns_a_fresh_instance() -> None:
    """The factory builds independent apps rather than sharing a singleton."""
    assert create_app() is not create_app()


def test_health_reports_ok() -> None:
    """GET /health answers 200 with the documented body."""
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == SERVICE_NAME
    assert body["version"]


def test_openapi_schema_is_served() -> None:
    """The OpenAPI document builds.

    Phase 1's codegen/gen_ts_api.sh will consume this, so a broken schema must
    fail here rather than in the generator.
    """
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "/health" in schema["paths"]
