"""Contract test: OpenAPI schema has /api/extract and response schema with required fields."""

import pytest
from fastapi.testclient import TestClient


def test_openapi_extract_path_exists():
    """OpenAPI schema defines POST for extract."""
    from app.main import app
    schema = app.openapi()
    paths = schema.get("paths", {})
    assert any("extract" in p for p in paths), f"Expected path containing 'extract', got {list(paths.keys())}"


def test_openapi_extract_response_schema():
    """Extract endpoint response schema includes required fields (e.g. document_id)."""
    from app.main import app
    schema = app.openapi()
    paths = schema.get("paths", {})
    for path_key, path_item in paths.items():
        if "extract" not in path_key:
            continue
        post = path_item.get("post")
        if not post:
            continue
        responses = post.get("responses", {})
        ok = responses.get("200", {})
        content = ok.get("content", {})
        json_content = content.get("application/json", {})
        schema_ref = json_content.get("schema") or {}
        ref = schema_ref.get("$ref") if isinstance(schema_ref, dict) else None
        if ref:
            ref_name = ref.split("/")[-1]
            resolved = schema.get("components", {}).get("schemas", {}).get(ref_name, {})
            required = resolved.get("required", [])
        else:
            required = (schema_ref.get("required", []) if isinstance(schema_ref, dict) else [])
        assert "document_id" in required, f"Expected document_id in required fields, got {required}"
        return
    pytest.fail("Could not find POST .../extract in OpenAPI paths")
