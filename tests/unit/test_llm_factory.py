"""Unit tests for LLMFactory."""

import pytest
from unittest.mock import patch, MagicMock

from app.adapters.llm.factory import LLMFactory


@patch("app.adapters.llm.factory.settings")
def test_llm_factory_creates_openai_invoker_when_configured(mock_settings):
    """When LLM_PROVIDER=openai and keys set, factory returns OpenAIInvoker."""
    mock_settings.LLM_PROVIDER = "openai"
    mock_settings.OPENAI_API_KEY = "sk-test"
    mock_settings.OPENAI_MODEL = "gpt-4o"
    mock_settings.LLM_TIMEOUT = 60
    with patch("app.adapters.llm.providers.openai.OpenAIInvoker") as mock_openai:
        instance = MagicMock()
        mock_openai.return_value = instance
        result = LLMFactory.create()
        assert result is instance
        mock_openai.assert_called_once_with(
            api_key="sk-test",
            model_id="gpt-4o",
            timeout_seconds=60,
        )


@patch("app.adapters.llm.factory.settings")
def test_llm_factory_raises_when_openai_missing_api_key(mock_settings):
    """When LLM_PROVIDER=openai and OPENAI_API_KEY empty, factory raises ValueError."""
    mock_settings.LLM_PROVIDER = "openai"
    mock_settings.OPENAI_API_KEY = ""
    mock_settings.OPENAI_MODEL = "gpt-4o"
    with pytest.raises(ValueError) as exc_info:
        LLMFactory.create()
    assert "OPENAI_API_KEY" in str(exc_info.value)


@patch("app.adapters.llm.factory.settings")
def test_llm_factory_raises_when_openai_missing_model(mock_settings):
    """When LLM_PROVIDER=openai and OPENAI_MODEL empty, factory raises ValueError."""
    mock_settings.LLM_PROVIDER = "openai"
    mock_settings.OPENAI_API_KEY = "sk-test"
    mock_settings.OPENAI_MODEL = ""
    with pytest.raises(ValueError) as exc_info:
        LLMFactory.create()
    assert "OPENAI_MODEL" in str(exc_info.value)


@patch("app.adapters.llm.factory.settings")
def test_llm_factory_raises_for_unsupported_provider(mock_settings):
    """When LLM_PROVIDER is not bedrock or openai, factory raises ValueError."""
    mock_settings.LLM_PROVIDER = "azure"
    with pytest.raises(ValueError) as exc_info:
        LLMFactory.create()
    assert "Unsupported LLM_PROVIDER" in str(exc_info.value)
    assert "azure" in str(exc_info.value)


@patch("app.adapters.llm.factory.settings")
def test_llm_factory_creates_bedrock_invoker_when_configured(mock_settings):
    """When LLM_PROVIDER=bedrock and MODEL_ID set, factory returns BedrockInvoker."""
    mock_settings.LLM_PROVIDER = "bedrock"
    mock_settings.MODEL_ID = "anthropic.claude-3-sonnet-v1"
    mock_settings.LLM_TIMEOUT = 60
    with patch("app.adapters.aws_clients.aws_clients") as mock_aws_clients:
        mock_aws_clients.get_bedrock.return_value = MagicMock()
        with patch("app.adapters.llm.providers.bedrock.BedrockInvoker") as mock_bedrock:
            instance = MagicMock()
            mock_bedrock.return_value = instance
            result = LLMFactory.create()
            assert result is instance
            mock_bedrock.assert_called_once()
            assert mock_bedrock.call_args[1]["model_id"] == "anthropic.claude-3-sonnet-v1"


@patch("app.adapters.llm.factory.settings")
def test_llm_factory_raises_when_bedrock_missing_model_id(mock_settings):
    """When LLM_PROVIDER=bedrock and MODEL_ID empty, factory raises ValueError."""
    mock_settings.LLM_PROVIDER = "bedrock"
    mock_settings.MODEL_ID = ""
    with pytest.raises(ValueError) as exc_info:
        LLMFactory.create()
    assert "MODEL_ID" in str(exc_info.value)
