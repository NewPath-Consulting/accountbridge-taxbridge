import asyncio
import json
from typing import Dict, Any, List, Optional
import logging

# from app.adapters.aws_clients import aws_clients
# from app.core.bedrock import BedrockInvoker
from app.config.settings import settings
from app.api.schemas.document import ExtractionResponse
from app.core.prompts.loader import get_prompt_builder
from app.core.model_gateway.aim_main import acompletion

logger = logging.getLogger(__name__)

# Optional in-memory token counter for metrics (no PII)
_llm_tokens_total: List[int] = [0]


class LLMService:
    """Service for processing extracted data with LLM (supports multiple providers)"""

    def __init__(self):
        logger.info(f"LLMService initialized with provider: {settings.LLM_PROVIDER}")

    async def enhance_extraction(
        self,
        extraction_response: ExtractionResponse,
        custom_prompt: str = None,
        custom_output_format: Optional[Dict[str, Any]] = None,
        prompt_version: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Process extraction results with LLM to get structured key-value output

        Args:
            extraction_response: The extraction results
            custom_prompt: Optional custom prompt to override default
            custom_output_format: Optional custom JSON structure for output
            prompt_version: Optional prompt version id (e.g. default, v1)
        """
        try:
            version_used = prompt_version or "default"
            logger.info(f"Enhancing extraction with LLM: {extraction_response.document_id}, prompt_version={version_used}")

            if custom_output_format:
                logger.info("Using custom output format provided by user")

            prompt_body = self._build_prompt_request(
                extraction_response,
                custom_prompt,
                custom_output_format,
                prompt_version=prompt_version,
                max_tokens=max_tokens,
            )

            try:
                response = await acompletion(
                    model=settings.LLM_MODEL,
                    custom_llm_provider=settings.LLM_PROVIDER,
                    timeout=settings.LLM_TIMEOUT,
                    **prompt_body
                )
            except asyncio.TimeoutError:
                logger.error(f"LLM call timed out after {settings.LLM_TIMEOUT}s")
                raise RuntimeError("LLM processing timed out")

            usage = response.get("usage", {})
            if usage:
                _llm_tokens_total[0] += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            llm_output = response.get("result", response)
            if custom_output_format:
                from app.utils.llm_json import coerce_llm_dict

                llm_output = coerce_llm_dict(llm_output)

            logger.info(f"LLM processing completed for {extraction_response.document_id}")
            return llm_output

        except Exception as e:
            logger.error(f"LLM enhancement failed: {str(e)}")
            raise

    async def process_pages_batch(
        self,
        pages_data: List[Dict[str, Any]],
        custom_prompt: str = None,
        custom_output_format: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Process multiple pages with LLM concurrently"""
        tasks = [
            self._process_single_page(page_data, custom_prompt, custom_output_format)
            for page_data in pages_data
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        successful_results = []
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Page {idx + 1} LLM processing failed: {str(result)}")
            else:
                successful_results.append(result)
        return successful_results

    async def _process_single_page(
        self,
        page_data: Dict[str, Any],
        custom_prompt: Optional[str] = None,
        custom_output_format: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Process a single page with LLM"""
        text = page_data.get('text_content', '')
        forms = page_data.get('forms', [])
        tables = page_data.get('tables', [])

        if custom_prompt:
            prompt_body = {
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": custom_prompt}],
                "temperature": 0.1,
            }
        else:
            builder = get_prompt_builder(None)
            prompt_body = builder(
                text=text,
                forms=forms,
                tables=tables,
                file_name=f"Page {page_data.get('page_number', 1)}",
                file_type="",
                pages_processed=1,
                total_pages=1,
                custom_output_format=custom_output_format
            )

        try:
            response = await acompletion(
                model=settings.LLM_MODEL,
                custom_llm_provider=settings.LLM_PROVIDER,
                timeout=settings.LLM_TIMEOUT,
                **prompt_body
            )
        except asyncio.TimeoutError:
            raise RuntimeError("LLM call timed out")

        usage = response.get("usage", {})
        if usage:
            _llm_tokens_total[0] += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        return response.get("result", response)

    def _build_prompt_request(
        self,
        extraction_response: ExtractionResponse,
        custom_prompt: str = None,
        custom_output_format: Optional[Dict[str, Any]] = None,
        prompt_version: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Build prompt request body using prompt_builder with structured output support."""
        token_limit = max_tokens or 4096

        if custom_prompt:
            document_context = self._format_extraction_context(extraction_response)
            prompt_with_context = custom_prompt
            if document_context:
                prompt_with_context = (
                    f"{custom_prompt}\n\n# DOCUMENT TEXT (OCR)\n\n{document_context}"
                )

            prompt_body = {
                "max_tokens": token_limit,
                "messages": [{"role": "user", "content": prompt_with_context}],
                "temperature": 0.1,
            }
            if custom_output_format:
                try:
                    from app.core.prompts.templates import convert_to_json_schema
                    json_schema = convert_to_json_schema(custom_output_format)
                    prompt_body["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "schema": json_schema,
                            "strict": True,
                            "name": "extraction_output",
                            "description": "Structured document extraction output matching the exact format specified"
                        }
                    }
                    logger.info("Attempting Bedrock structured output with custom format (will fallback if not supported)")
                except Exception as e:
                    logger.warning(f"Failed to create JSON schema for structured output: {str(e)}, using prompt instructions instead")
                enhanced_prompt = f"""{prompt_with_context}

IMPORTANT: You must return your response as a valid JSON object that matches this EXACT structure:
{json.dumps(custom_output_format, indent=2)}

Return ONLY the JSON object, no markdown, no explanations."""
                prompt_body["messages"][0]["content"] = enhanced_prompt
            return prompt_body

        all_text = []
        all_forms = []
        all_tables = []
        for page in extraction_response.pages_data:
            if page.text_content:
                all_text.append(f"=== Page {page.page_number} ===\n{page.text_content}")
            for form in page.forms:
                all_forms.append({"key": form.key, "value": form.value, "page": page.page_number})
            for table in page.tables:
                all_tables.append({
                    "page": page.page_number,
                    "table_id": table.table_id,
                    "headers": table.headers,
                    "rows": table.rows[:5]
                })
        full_text = "\n\n".join(all_text)
        builder = get_prompt_builder(prompt_version)
        return builder(
            text=full_text,
            forms=all_forms,
            tables=all_tables,
            file_name=extraction_response.file_name,
            file_type=extraction_response.file_type,
            pages_processed=extraction_response.pages_processed,
            total_pages=extraction_response.total_pages,
            custom_output_format=custom_output_format
        )

    def _format_extraction_context(self, extraction_response: ExtractionResponse) -> str:
        """Build OCR text context from extracted pages for custom prompts."""
        all_text = []
        for page in extraction_response.pages_data:
            if page.text_content:
                all_text.append(f"=== Page {page.page_number} ===\n{page.text_content}")
            for form in page.forms:
                all_text.append(f"Form field (page {page.page_number}): {form.key} = {form.value}")
            for table in page.tables:
                headers = ", ".join(table.headers or [])
                all_text.append(f"Table (page {page.page_number}) headers: {headers}")
                for row in (table.rows or [])[:20]:
                    all_text.append(f"  {' | '.join(str(cell) for cell in row)}")
        return "\n\n".join(all_text)
