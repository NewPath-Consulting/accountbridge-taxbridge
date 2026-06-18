"""
Legacy Bedrock helpers (RJSF/form-specific). New code should use app.core.bedrock
for invocation and app.services.llm_service for IDP orchestration.
"""
from fastapi import UploadFile
from typing import List, Dict, Any
import re
import json
from app.adapters.aws_clients import aws_clients
from app.config.settings import settings
from app.prompts.rjfs_prompt import handle_other

bedrock = aws_clients.get_bedrock()

def clean_dict_string(input_string: str) -> str:
    start_index = input_string.find('{')
    end_index = input_string.rfind('}')
    
    if start_index != -1 and end_index != -1:
        return input_string[start_index:end_index+1]
    return input_string


def call_bedrock(prompt: Dict[str, Any]) -> Dict[str, Any]:
    for _ in range(3):
        body = json.dumps({
            **prompt,
            "system": "Prepare RSJF formated form using page's extracted data, use the extracted text and page image for formating refference. You want to replicate the page completely",
            "stop_sequences": ["\n\nHuman:"]
        })

        response = bedrock.invoke_model(
            modelId=settings.LLM_MODEL,
            body=body,
            contentType="application/json",
            accept="application/json"
        )
        result = json.loads(response['body'].read())
        text = result['content'][0]['text']
        
        other_values = ["other", "Other", "OTHER", "OTHERS", "Others", "others"]
        for value in other_values:
            if value in text:
                body = json.dumps({
                    **handle_other(text),
                    "stop_sequences": ["\n\nHuman:"]
                })

                response = bedrock.invoke_model(
                    modelId=settings.LLM_MODEL,
                    body=body,
                    contentType="application/json",
                    accept="application/json"
                )
                result = json.loads(response['body'].read())
                text = result['content'][0]['text']
                break
        
        cleaned_text = clean_dict_string(text)
        try:
            return json.loads(cleaned_text)
        except json.JSONDecodeError:
            continue
    
    return {}


def format_title(text: str) -> str:
    words = re.sub(r'(?<!^)(?=[A-Z])', ' ', text).replace('_', ' ')
    return words.title()


def replace_empty_with_space(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: replace_empty_with_space(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [replace_empty_with_space(v) for v in data]
    elif isinstance(data, str):
        return " " if data == "" else data
    return data


def combine_schemas(pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    combined_json_schema_properties = {}
    combined_json_schema_required = set()
    combined_json_schema_dependencies = {}
    combined_ui_schema = {}
    combined_form_schema = []
    combined_corrections = []

    combined_json_schema = {
        "type": "object",
        "title": "",
        "description": "",
        "properties": combined_json_schema_properties,
        "required": [],
        "dependencies": combined_json_schema_dependencies
    }

    for page_idx, page in enumerate(pages, start=1):
        if "title" in page.get("jsonSchema", {}):
            title = page["jsonSchema"]["title"]
            if page_idx == 1:
                combined_json_schema["title"] = title
            else:
                header_key = f"header_{page_idx}"
                combined_json_schema_properties[header_key] = {
                    "type": "string",
                    "title": " ",
                    "default": f"<h3 style='font-weight: bold;'>{title}</h3>"
                }
                combined_ui_schema[header_key] = {"ui:widget": "HtmlWidget"}

        prop_mapping = {}
        for key, value in page.get("jsonSchema", {}).get("properties", {}).items():
            if "title" not in value:
                value["title"] = format_title(key)
            unique_key = f"{key}_{page_idx}"
            combined_json_schema_properties[unique_key] = replace_empty_with_space(value)
            prop_mapping[key] = unique_key

        if "required" in page.get("jsonSchema", {}):
            for req in page["jsonSchema"]["required"]:
                combined_json_schema_required.add(f"{req}_{page_idx}")

        if "description" in page.get("jsonSchema", {}):
            combined_json_schema["description"] += page["jsonSchema"]["description"] + " "

        for key, value in page.get("uiSchema", {}).items():
            unique_key = f"{key}_{page_idx}"
            combined_ui_schema[unique_key] = replace_empty_with_space(value)

        form_schema = page.get("formSchema")
        if isinstance(form_schema, list):
            combined_form_schema.extend(replace_empty_with_space(form_schema))
        elif form_schema:
            combined_form_schema.append(replace_empty_with_space(form_schema))

        corrections = page.get("corrections")
        if corrections:
            if isinstance(corrections, list):
                combined_corrections.extend(replace_empty_with_space(corrections))
            elif isinstance(corrections, dict):
                page_id = page.get("page_id", f"Page {page_idx}")
                combined_corrections.append({page_id: replace_empty_with_space(corrections)})
            elif isinstance(corrections, str):
                combined_corrections.append(replace_empty_with_space(corrections))

        for dep_key, dep_val in page.get("jsonSchema", {}).get("dependencies", {}).items():
            new_dep_key = prop_mapping.get(dep_key)
            if not new_dep_key:
                continue

            def rewrite_keys(obj):
                if isinstance(obj, dict):
                    return {prop_mapping.get(k, k): rewrite_keys(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [rewrite_keys(i) for i in obj]
                return obj

            combined_json_schema_dependencies[new_dep_key] = rewrite_keys(dep_val)

    combined_json_schema["required"] = list(combined_json_schema_required)
    combined_json_schema = replace_empty_with_space(combined_json_schema)
    combined_ui_schema = replace_empty_with_space(combined_ui_schema)
    combined_form_schema = replace_empty_with_space(combined_form_schema)
    combined_corrections = replace_empty_with_space(combined_corrections)

    return {
        "jsonSchema": combined_json_schema,
        "uiSchema": combined_ui_schema,
        "formSchema": combined_form_schema,
        "corrections": combined_corrections
    }


def get_file_type(file: UploadFile) -> str:
    content_type = file.content_type.lower() if file.content_type else ""
    filename = file.filename.lower() if file.filename else ""

    if content_type.startswith("image/") or any(filename.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp']):
        return "image"
    elif content_type == "application/pdf" or filename.endswith('.pdf'):
        return "pdf"
    elif content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or filename.endswith('.docx'):
        return "docx"
    else:
        raise ValueError(f"Unsupported file type: {content_type or filename}")