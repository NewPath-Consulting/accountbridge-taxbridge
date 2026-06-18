"""Pytest fixtures and test env."""

import os

import pytest

# Set test env vars BEFORE any imports (needed for collection to work)
# Only set if not already set so unit tests can override
if "EXTRACTOR_TYPE" not in os.environ:
    os.environ["EXTRACTOR_TYPE"] = "goml_custom_extractor"
if "AUTH_METHOD" not in os.environ:
    os.environ["AUTH_METHOD"] = "none"
if "BUCKET_NAME" not in os.environ:
    os.environ["BUCKET_NAME"] = ""
if "LLM_PROVIDER" not in os.environ:
    os.environ["LLM_PROVIDER"] = "openai"
if "OPENAI_API_KEY" not in os.environ:
    os.environ["OPENAI_API_KEY"] = "sk-test-key"
if "MODEL_ID" not in os.environ:
    os.environ["MODEL_ID"] = ""


@pytest.fixture
def app():
    """FastAPI app for TestClient (import after env is set)."""
    from app.main import app as fastapi_app
    return fastapi_app
