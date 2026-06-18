"""Integration test: POST to /api/v1/extract with small file, expect 200 and response schema."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_extract_txt_returns_200_and_schema(client: TestClient):
    """POST a small text file to /api/v1/extract with process_with_llm=false returns 200 and valid schema."""
    response = client.post(
        "/api/extract",
        files={"file": ("sample.txt", b"Hello from integration test.", "text/plain")},
        data={"process_with_llm": "false"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "document_id" in data
    assert "file_name" in data
    assert "status" in data
    assert "total_pages" in data
    assert "pages_processed" in data
    assert "pages_data" in data
    assert data["file_name"] == "sample.txt"
    # assert data["status"] in ("completed", "processing", "pending")
