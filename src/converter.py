"""协议转换模块 - OpenAI ↔ Google Gemini 格式转换"""
import copy
import json
import logging
import re
import time
import uuid
from typing import Dict, List, Tuple, Optional, AsyncGenerator, AsyncIterator

from src.image_storage import save_base64_image
from src.signature_cache import (
    get_reasoning_signature,
    get_tool_signature,
    set_reasoning_signature,
    set_tool_signature,
)
from src.tool_name_cache import (
    get_original_tool_name,
    set_tool_name_mapping,
)

# 配置日志
logger = logging.getLogger(__name__)


# Thought signature constants are required by upstream validation logic for tool calling / thinking models.
# These values are aligned with the NodeJS implementation.
CLAUDE_THOUGHT_SIGNATURE = (
    "RXVNQkNrZ0lDaEFDR0FJcVFLZGsvMnlyR0VTbmNKMXEyTFIrcWwyY2ozeHhoZHRPb0VOYWJ2VjZMSnE2MlBhcEQrUWdI"
    "M3ZWeHBBUG9rbGN1aXhEbXprZTcvcGlkbWRDQWs5MWcrTVNERnRhbWJFOU1vZWZGc1pWSGhvTUxsMXVLUzRoT3BIaWwy"
    "eXBJakNYa05EVElMWS9talprdUxvRjFtMmw5dnkrbENhSDNNM3BYNTM0K1lRZ0NaWTQvSUNmOXo4SkhZVzU2Sm1WcTZB"
    "cVNRUURBRGVMV1BQRXk1Q0JsS0dCZXlNdHp2NGRJQVlGbDFSMDBXNGhqNHNiSWNKeGY0UGZVQTBIeE1mZjJEYU5BRXdr"
    "WUJ4MmNzRFMrZGM1N1hnUlVNblpkZ0hTVHVNaGdod1lBUT09"
)
GEMINI_THOUGHT_SIGNATURE = (
    "EqAHCp0HAXLI2nygRbdzD4Vgzxxi7tbM87zIRkNgPLqTj+Jxv9mY8Q0G87DzbTtvsIFhWB0RZMoEK6ntm5GmUe6ADtxH"
    "k4zgHUs/FKqTu8tzUdPRDrKn3KCAtFW4LJqijZoFxNKMyQRmlgPUX4tGYE7pllD77UK6SjCwKhKZoSVZLMiPXP9YFktb"
    "ida1Q5upXMrzG1t8abPmpFo983T/rgWlNqJp+Fb+bsoH0zuSpmU4cPKO3LIGsxBhvRhM/xydahZD+VpEX7TEJAN58z1Ro"
    "mFyx9u0IR7ukwZr2UyoNA+uj8OChUDFupQsVwbm3XE1UAt22BGvfYIyyZ42fxgOgsFFY+AZ72AOufcmZb/8vIw3uEUgxH"
    "czdl+NGLuS4Hsy/AAntdcH9sojSMF3qTf+ZK1FMav23SPxUBtU5T9HCEkKqQWRnMsVGYV1pupFisWo85hRLDTUipxVy9u"
    "g1hN8JBYBNmGLf8KtWLhVp7Z11PIAZj3C6HzoVyiVeuiorwNrn0ZaaXNe+y5LHuDF0DNZhrIfnXByq6grLLSAv4fTLeCJ"
    "vfGzTWWyZDMbVXNx1HgumKq8calP9wv33t0hfEaOlcmfGIyh1J/N+rOGR0WXcuZZP5/VsFR44S2ncpwTPT+MmR0PsjocD"
    "enRY5m/X4EXbGGkZ+cfPnWoA64bn3eLeJTwxl9W1ZbmYS6kjpRGUMxExgRNOzWoGISddHCLcQvN7o50K8SF5k97rxiS5q"
    "4rqDmqgRPXzQTQnZyoL3dCxScX9cvLSjNCZDcotonDBAWHfkXZ0/EmFiONQcLJdANtAjwoA44Mbn50gubrTsNd7d0Rm/hb"
    "NEh/ZceUalV5MMcl6tJtahCJoybQMsnjWuBXl7cXiKmqAvxTDxIaBgQBYAo4FrbV4zQv35zlol+O3YiyjJn/U0oBeO5pEc"
    "H1d0vnLgYP71jZVY2FjWRKnDR9aw4JhiuqAa+i0tupkBy+H4/SVwHADFQq6wcsL8qvXlwktJL9MIAoaXDkIssw6gKE9EuG"
    "d7bSO9f+sA8CZ0I8LfJ3jcHUsE/3qd4pFrn5RaET56+1p8ZHZDDUQ0p1okApUCCYsC2WuL6O9P4fcg3yitAA/AfUUNjHKA"
    "NE+ANneQ0efMG7fx9bvI+iLbXgPupApoov24JRkmhHsrJiu9bp+G/pImd2PNv7ArunJ6upl0VAUWtRyLWyGfdl6etGuY8v"
    "VJ7JdWEQ8aWzRK3g6e+8YmDtP5DAfw=="
)
TOOL_THOUGHT_SIGNATURE = (
    "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"
    "+48="
)
DEFAULT_THOUGHT_SIGNATURE = CLAUDE_THOUGHT_SIGNATURE


def get_thought_signature_for_model(model: Optional[str]) -> str:
    model_name = (model or "").lower()
    if "gemini" in model_name:
        return GEMINI_THOUGHT_SIGNATURE
    if "claude" in model_name:
        return CLAUDE_THOUGHT_SIGNATURE
    return DEFAULT_THOUGHT_SIGNATURE


def get_tool_thought_signature_for_model(model: Optional[str]) -> str:
    model_name = (model or "").lower()
    if "claude" in model_name:
        return CLAUDE_THOUGHT_SIGNATURE
    return TOOL_THOUGHT_SIGNATURE


def sanitize_tool_name(name: Optional[str]) -> str:
    if not isinstance(name, str) or not name:
        return "tool"
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    cleaned = re.sub(r"^_+|_+$", "", cleaned)
    if not cleaned:
        cleaned = "tool"
    return cleaned[:128]


class RequestConverter:
    """请求格式转换器"""
    DEFAULT_STOP_SEQUENCES = [
        "<|user|>",
        "<|bot|>",
        "<|context_request|>",
        "<|endoftext|>",
        "<|end_of_turn|>"
    ]
    SCHEMA_TYPE_MAPPING = {
        "string": "string",
        "number": "number",
        "integer": "integer",
        "boolean": "boolean",
        "array": "array",
        "object": "object",
        "null": "null"
    }
    SUPPORTED_SCHEMA_TYPES = set(SCHEMA_TYPE_MAPPING.values())
    REASONING_EFFORT_MAP = {
        "low": 1024,
        "medium": 16000,
        "high": 32000,
    }
    EXCLUDED_SCHEMA_KEYS = {
        "$schema",
        "additionalProperties",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "uniqueItems",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "const",
        "anyOf",
        "oneOf",
        "allOf",
        "any_of",
        "one_of",
        "all_of",
    }

    @staticmethod
    def is_image_model(model: Optional[str]) -> bool:
        if not model:
            return False
        return str(model).lower().endswith("-image")

    @staticmethod
    def prepare_image_request(google_request: Dict) -> Dict:
        if not isinstance(google_request, dict):
            return google_request

        request = google_request.get("request")
        if not isinstance(request, dict):
            return google_request

        google_request["requestType"] = "image_gen"
        request["generationConfig"] = {"candidateCount": 1}

        request.pop("systemInstruction", None)
        request.pop("tools", None)
        request.pop("toolConfig", None)
        return google_request

    @staticmethod
    def openai_to_google(
        openai_request: Dict,
        project_id: str,
        session_id: Optional[str] = None,
    ) -> Tuple[Dict, str]:
        """
        将 OpenAI 格式请求转换为 Google Gemini 格式

        返回: (google_request, url_suffix)
        """
        messages = openai_request.get("messages", [])
        model = openai_request.get("model", "gemini-2.5-flash")
        stream = openai_request.get("stream", False)
        is_image_model = RequestConverter.is_image_model(model)
        enable_thinking = RequestConverter.is_enable_thinking(model)

        # 提取 system 消息和普通消息
        system_instruction, contents = RequestConverter.extract_system_instruction(
            messages,
            model=model,
            session_id=session_id,
            enable_thinking=enable_thinking,
        )
        RequestConverter.validate_contents_sequence(contents)

        # 构建 generationConfig
        generation_config = {}
        if "temperature" in openai_request:
            generation_config["temperature"] = openai_request["temperature"]
        if "max_tokens" in openai_request:
            generation_config["maxOutputTokens"] = openai_request["max_tokens"]
        if "top_p" in openai_request:
            generation_config["topP"] = openai_request["top_p"]
        if "top_k" in openai_request:
            generation_config["topK"] = openai_request["top_k"]
        if "frequency_penalty" in openai_request:
            generation_config["frequencyPenalty"] = openai_request["frequency_penalty"]
        if "presence_penalty" in openai_request:
            generation_config["presencePenalty"] = openai_request["presence_penalty"]
        if "stop" in openai_request:
            stop = openai_request["stop"]
            # stop 可以是字符串或数组
            if isinstance(stop, str):
                generation_config["stopSequences"] = [stop]
            elif isinstance(stop, list):
                generation_config["stopSequences"] = stop
        elif "stopSequences" not in generation_config:
            generation_config["stopSequences"] = list(RequestConverter.DEFAULT_STOP_SEQUENCES)
        if "n" in openai_request:
            generation_config["candidateCount"] = openai_request["n"]
        if "response_format" in openai_request:
            response_format = openai_request["response_format"]
            if isinstance(response_format, dict) and response_format.get("type") == "json_object":
                generation_config["responseMimeType"] = "application/json"

        generation_config["thinkingConfig"] = {
            "includeThoughts": enable_thinking,
            "thinkingBudget": RequestConverter.get_thinking_budget(openai_request, enable_thinking),
        }
        if enable_thinking and "claude" in str(model).lower():
            generation_config.pop("topP", None)

        # 构建 Google 请求
        google_request = {
            "project": project_id,
            "requestId": f"agent-{uuid.uuid4()}",
            "request": {
                "contents": contents
            },
            "model": model
        }

        # 添加 userAgent（固定为 "antigravity"）
        google_request["userAgent"] = "antigravity"

        if session_id:
            google_request["request"]["sessionId"] = session_id

        # 添加 systemInstruction
        if system_instruction:
            google_request["request"]["systemInstruction"] = system_instruction

        # 添加 generationConfig
        if generation_config:
            google_request["request"]["generationConfig"] = generation_config

        # Convert tools (function calling).
        openai_tools = openai_request.get("tools") or []
        google_tools = RequestConverter.convert_tools(openai_tools, session_id=session_id, model=model)
        if google_tools:
            google_request["request"]["tools"] = google_tools
            google_request["request"]["toolConfig"] = {
                "functionCallingConfig": {"mode": "VALIDATED"}
            }

        if is_image_model:
            google_request = RequestConverter.prepare_image_request(google_request)

        RequestConverter.log_conversion_summary(openai_request, google_request)

        # URL 后缀
        # 流式：使用 streamGenerateContent + alt=sse
        # 非流式：使用 generateContent
        url_suffix = "/v1internal:generateContent" if is_image_model else (
            "/v1internal:streamGenerateContent?alt=sse" if stream else "/v1internal:generateContent"
        )

        return google_request, url_suffix

    @staticmethod
    def determine_thinking_config(model: Optional[str]) -> Optional[Dict]:
        if not model:
            return None

        model_name = str(model).lower()

        if "gemini" in model_name:
            return {
                "includeThoughts": True,
                "thinkingBudget": -1
            }

        if "claude" in model_name:
            has_thinking_suffix = model_name.endswith("-thinking") or "-thinking-" in model_name
            if has_thinking_suffix:
                return {
                    "includeThoughts": True,
                    "thinkingBudget": 1024
                }
            return {
                "includeThoughts": False,
                "thinkingBudget": 0
            }

        return None

    @staticmethod
    def is_enable_thinking(model: Optional[str]) -> bool:
        if not model:
            return False
        name = str(model).lower()
        return (
            "-thinking" in name
            or name == "gemini-2.5-pro"
            or name.startswith("gemini-3-pro-")
            or name == "rev19-uic3-1p"
            or name == "gpt-oss-120b-medium"
        )

    @staticmethod
    def get_thinking_budget(openai_request: Dict, enable_thinking: bool) -> int:
        if not enable_thinking:
            return 0

        raw_budget = openai_request.get("thinking_budget")
        if raw_budget is not None:
            try:
                return int(raw_budget)
            except (TypeError, ValueError):
                return 1024

        effort = openai_request.get("reasoning_effort")
        if isinstance(effort, str):
            mapped = RequestConverter.REASONING_EFFORT_MAP.get(effort.lower())
            if mapped is not None:
                return mapped

        return 1024

    @staticmethod
    def extract_system_instruction(
        messages: List[Dict],
        model: Optional[str] = None,
        session_id: Optional[str] = None,
        enable_thinking: Optional[bool] = None,
    ) -> Tuple[Optional[Dict], List[Dict]]:
        """
        从消息列表中提取 system 消息和普通消息

        返回: (system_instruction, contents)
        """
        system_messages = []
        contents = []
        tool_call_info_map: Dict[str, Dict[str, str]] = {}
        collecting_system = True
        if enable_thinking is None:
            thinking_config = RequestConverter.determine_thinking_config(model)
            enable_thinking = bool(thinking_config and thinking_config.get("includeThoughts"))
        default_reasoning_signature = get_thought_signature_for_model(model)

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "system" and collecting_system:
                if isinstance(content, str):
                    system_messages.append(content)
                elif isinstance(content, list):
                    for part in content:
                        if part.get("type") == "text":
                            text_value = RequestConverter.extract_text_value(part.get("text"))
                            if text_value:
                                system_messages.append(text_value)
                elif isinstance(content, dict):
                    text_value = RequestConverter.extract_text_value(content)
                    if text_value:
                        system_messages.append(text_value)
                continue
            else:
                collecting_system = False

            if role == "system":
                role = "user"

            if role == "user":
                contents.append({
                    "role": "user",
                    "parts": RequestConverter.convert_content_to_parts(content)
                })
            elif role == "assistant":
                parts: List[Dict] = []

                if enable_thinking:
                    reasoning_text = msg.get("reasoning_content")
                    if not isinstance(reasoning_text, str) or not reasoning_text:
                        reasoning_text = " "
                    reasoning_signature = msg.get("thoughtSignature") or msg.get("thought_signature")
                    if not isinstance(reasoning_signature, str) or not reasoning_signature:
                        reasoning_signature = (
                            get_reasoning_signature(session_id, model)
                            or default_reasoning_signature
                        )
                    parts.append({"text": reasoning_text, "thought": True})
                    parts.append({"text": " ", "thoughtSignature": reasoning_signature})

                if content is not None and not (isinstance(content, str) and content == ""):
                    parts.extend(RequestConverter.convert_content_to_parts(content))
                tool_calls = msg.get("tool_calls", [])
                for tool_call in tool_calls:
                    if tool_call.get("type") != "function":
                        continue
                    func = tool_call.get("function", {})
                    func_name = func.get("name")
                    if not func_name:
                        continue
                    tool_call_id = tool_call.get("id") or f"call_{uuid.uuid4().hex}"
                    safe_name = sanitize_tool_name(func_name)
                    if session_id and model and safe_name != func_name:
                        set_tool_name_mapping(session_id, model, safe_name, func_name)

                    signature = tool_call.get("thoughtSignature") or tool_call.get("thought_signature")
                    if enable_thinking and (not isinstance(signature, str) or not signature):
                        signature = get_tool_signature(session_id, model) or get_tool_thought_signature_for_model(model)
                    tool_call_info_map[tool_call_id] = {
                        "name": safe_name,
                        "thoughtSignature": signature if isinstance(signature, str) else None,
                    }

                    args_data = func.get("arguments", {})
                    if isinstance(args_data, str):
                        try:
                            args = json.loads(args_data) if args_data.strip() else {}
                        except (json.JSONDecodeError, ValueError):
                            args = {"query": args_data}
                    elif isinstance(args_data, dict):
                        args = args_data
                    else:
                        args = {}

                    part_entry = {
                        "functionCall": {
                            "id": tool_call_id,
                            "name": safe_name,
                            "args": args
                        }
                    }
                    if enable_thinking:
                        part_entry["thoughtSignature"] = signature
                    parts.append(part_entry)

                contents.append({
                    "role": "model",
                    "parts": parts or [{"text": ""}]
                })
            elif role == "tool":
                function_response = RequestConverter.convert_tool_message(msg, tool_call_info_map)
                last_entry = contents[-1] if contents else None
                if (
                    isinstance(last_entry, dict)
                    and last_entry.get("role") == "user"
                    and isinstance(last_entry.get("parts"), list)
                    and any("functionResponse" in part for part in last_entry["parts"])
                ):
                    last_entry["parts"].append(function_response)
                else:
                    contents.append({
                        "role": "user",
                        "parts": [function_response]
                    })
            else:
                contents.append({
                    "role": "user",
                    "parts": RequestConverter.convert_content_to_parts(content)
                })

        system_instruction = None
        if system_messages:
            system_text = "\n\n".join(system_messages)
            system_instruction = {
                "parts": [{"text": system_text}]
            }

        return system_instruction, contents

    @staticmethod
    def validate_contents_sequence(contents: List[Dict]) -> None:
        invalid_indices = []
        for idx, entry in enumerate(contents):
            if entry.get("role") != "model":
                continue
            parts = entry.get("parts", [])
            has_function_call = any("functionCall" in part for part in parts)
            if not has_function_call and idx != len(contents) - 1:
                invalid_indices.append(idx)
        if invalid_indices:
            logger.debug("Detected model entries without functionCall at positions: %s", invalid_indices)


    @staticmethod
    def extract_text_value(value) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            if "text" in value:
                return RequestConverter.extract_text_value(value.get("text"))
            if "value" in value:
                return RequestConverter.extract_text_value(value.get("value"))
        return ""

    @staticmethod
    def convert_content_to_parts(content) -> List[Dict]:
        """
        将 OpenAI 的 content 字段转换为 Gemini 的 parts 数组

        支持:
        - 纯文本: "Hello"
        - 多模态: [{"type": "text", "text": "Hello"}, {"type": "image_url", "image_url": {...}}]
        """
        if isinstance(content, str):
            # 纯文本
            return [{"text": content}]
        elif isinstance(content, dict):
            text_value = RequestConverter.extract_text_value(content)
            return [{"text": text_value}] if text_value else [{"text": ""}]
        elif isinstance(content, list):
            # 多模态内容
            parts = []
            for item in content:
                item_type = item.get("type")
                if item_type == "text":
                    text_value = RequestConverter.extract_text_value(item.get("text"))
                    parts.append({"text": text_value})
                elif item_type == "image_url":
                    # 图片 URL
                    image_url = item.get("image_url", {})
                    url = image_url.get("url", "")

                    # 判断是内联 base64 还是外部链接
                    if url.startswith("data:image/"):
                        # data:image/jpeg;base64,/9j/4AAQ...
                        parts_split = url.split(",", 1)
                        if len(parts_split) == 2:
                            mime_type = parts_split[0].split(";")[0].replace("data:", "")
                            data = parts_split[1]
                            parts.append({
                                "inlineData": {
                                    "mimeType": mime_type,
                                    "data": data
                                }
                            })
                    else:
                        # 外部 URL，Gemini 需要先上传文件才能使用
                        parts.append({
                            "fileData": {
                                "fileUri": url
                            }
                        })
            return parts if parts else [{"text": ""}]
        else:
            # 其他类型，返回空文本
            return [{"text": ""}]

    @staticmethod
    def convert_tool_message(msg: Dict, tool_call_info_map: Dict[str, Dict[str, str]]) -> Dict:
        """
        将 OpenAI 的 tool role 消息转换为 Gemini 的 functionResponse
        """
        tool_call_id = msg.get("tool_call_id", "")
        info = tool_call_info_map.get(tool_call_id) if tool_call_id else None

        # functionResponse.name must match the previous functionCall.name (safe name).
        tool_name = (info or {}).get("name") or msg.get("name", "")
        if tool_name:
            tool_name = sanitize_tool_name(tool_name)

        if not tool_name:
            tool_name = "unknown_function"

        content = msg.get("content")
        if isinstance(content, (dict, list)):
            output = json.dumps(content, ensure_ascii=False)
        elif content is None:
            output = ""
        else:
            output = str(content)

        function_response: Dict = {
            "name": tool_name,
            "response": {"output": output},
        }
        if tool_call_id:
            function_response["id"] = tool_call_id

        return {"functionResponse": function_response}

    def normalize_schema(schema: Dict) -> Dict:
        """
        规范化 OpenAI 的 JSON Schema 中的 type 字段，确保符合 Google Gemini 的要求
        """
        if not isinstance(schema, dict):
            return schema

        schema_type = schema.get("type")
        if isinstance(schema_type, str):
            mapped = RequestConverter.SCHEMA_TYPE_MAPPING.get(schema_type.lower(), schema_type.lower())
            schema["type"] = mapped
        elif isinstance(schema_type, list):
            normalized = []
            for item in schema_type:
                if isinstance(item, str):
                    normalized.append(RequestConverter.SCHEMA_TYPE_MAPPING.get(item.lower(), item.lower()))
                else:
                    normalized.append(item)
            schema["type"] = normalized

        items = schema.get("items")
        if isinstance(items, dict):
            RequestConverter.normalize_schema(items)
        elif isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    RequestConverter.normalize_schema(item)

        prefix_items = schema.get("prefixItems")
        if isinstance(prefix_items, list):
            for item in prefix_items:
                if isinstance(item, dict):
                    RequestConverter.normalize_schema(item)

        for key in ("properties", "patternProperties", "definitions", ""):
            section = schema.get(key)
            if isinstance(section, dict):
                for subschema in section.values():
                    if isinstance(subschema, dict):
                        RequestConverter.normalize_schema(subschema)

        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            RequestConverter.normalize_schema(additional)

        for key in ("anyOf", "allOf", "oneOf"):
            options = schema.get(key)
            if isinstance(options, list):
                for option in options:
                    if isinstance(option, dict):
                        RequestConverter.normalize_schema(option)

        not_schema = schema.get("not")
        if isinstance(not_schema, dict):
            RequestConverter.normalize_schema(not_schema)

        for key in ("if", "then", "else"):
            conditional = schema.get(key)
            if isinstance(conditional, dict):
                RequestConverter.normalize_schema(conditional)

        RequestConverter.ensure_schema_defaults(schema)
        return schema
    @staticmethod
    def ensure_schema_defaults(schema: Dict) -> None:
        schema_type = schema.get("type")
        if schema_type == "object":
            properties = schema.get("properties")
            if properties is None or not isinstance(properties, dict):
                schema["properties"] = {} if properties is None else {}
            required = schema.get("required")
            if isinstance(required, list):
                schema["required"] = [str(item) for item in required if isinstance(item, str)]
            elif required is not None:
                schema["required"] = [str(required)]
        elif schema_type == "array":
            items = schema.get("items")
            if items is None or not isinstance(items, (dict, list)):
                schema["items"] = {}
            elif isinstance(items, list):
                schema["items"] = [item if isinstance(item, dict) else {} for item in items]

        enum_values = schema.get("enum")
        if enum_values is not None and not isinstance(enum_values, list):
            schema["enum"] = [enum_values]

    @staticmethod
    def validate_schema(schema: Dict, context: str) -> bool:
        errors: List[str] = []
        RequestConverter._validate_schema_recursive(schema, context, errors)
        if errors:
            for err in errors:
                logger.warning("Schema issue for %s: %s", context, err)
            return False
        return True

    @staticmethod
    def _validate_schema_recursive(schema: Dict, path: str, errors: List[str]) -> None:
        if not isinstance(schema, dict):
            errors.append(f"{path}: schema must be an object")
            return
        schema_type = schema.get("type")
        if isinstance(schema_type, str) and schema_type not in RequestConverter.SUPPORTED_SCHEMA_TYPES:
            errors.append(f"{path}: unsupported type '{schema_type}'")

        if schema_type == "object":
            properties = schema.get("properties")
            if properties is not None and not isinstance(properties, dict):
                errors.append(f"{path}: properties must be an object")
            required = schema.get("required")
            if required is not None:
                if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
                    errors.append(f"{path}: required must be an array of strings")
        if schema_type == "array":
            items = schema.get("items")
            if items is not None and not isinstance(items, (dict, list)):
                errors.append(f"{path}: items must be an object or array")

        for key in ("properties", "patternProperties", "definitions", ""):
            section = schema.get(key)
            if isinstance(section, dict):
                for name, subschema in section.items():
                    RequestConverter._validate_schema_recursive(subschema, f"{path}.{key}.{name}", errors)

        items = schema.get("items")
        if isinstance(items, dict):
            RequestConverter._validate_schema_recursive(items, f"{path}.items", errors)
        elif isinstance(items, list):
            for idx, subschema in enumerate(items):
                RequestConverter._validate_schema_recursive(subschema, f"{path}.items[{idx}]", errors)

        for key in ("anyOf", "allOf", "oneOf"):
            options = schema.get(key)
            if isinstance(options, list):
                for idx, subschema in enumerate(options):
                    RequestConverter._validate_schema_recursive(subschema, f"{path}.{key}[{idx}]", errors)

        for key in ("additionalProperties", "not", "if", "then", "else"):
            subschema = schema.get(key)
            if isinstance(subschema, dict):
                RequestConverter._validate_schema_recursive(subschema, f"{path}.{key}", errors)

    @staticmethod
    def clean_schema_metadata(schema: Dict) -> Dict:
        """
        移除 Google API 不支持的 JSON Schema 元数据字段

        Args:
            schema: JSON Schema 对象

        Returns:
            清理后的 schema
        """
        if not isinstance(schema, dict):
            return schema

        # Remove unsupported metadata fields while keeping structural refs ($ref/$defs).
        metadata_fields = ['$schema', '$id', '$comment']
        for field in metadata_fields:
            schema.pop(field, None)

        # 递归清理嵌套对象
        for key in ('properties', 'patternProperties', 'additionalProperties', 'items', 'prefixItems'):
            if key in schema:
                value = schema[key]
                if isinstance(value, dict):
                    if key in ('properties', 'patternProperties'):
                        # properties 是字典的字典
                        for prop_name, prop_schema in value.items():
                            if isinstance(prop_schema, dict):
                                RequestConverter.clean_schema_metadata(prop_schema)
                    else:
                        # 其他是单个 schema
                        RequestConverter.clean_schema_metadata(value)
                elif isinstance(value, list):
                    # items/prefixItems 可能是数组
                    for item in value:
                        if isinstance(item, dict):
                            RequestConverter.clean_schema_metadata(item)

        # 清理 anyOf/allOf/oneOf
        for key in ('anyOf', 'allOf', 'oneOf'):
            if key in schema and isinstance(schema[key], list):
                for item in schema[key]:
                    if isinstance(item, dict):
                        RequestConverter.clean_schema_metadata(item)

        # 清理 not
        if 'not' in schema and isinstance(schema['not'], dict):
            RequestConverter.clean_schema_metadata(schema['not'])

        return schema

    @staticmethod
    def clean_tool_parameters_schema(obj):
        """
        Clean tool JSON schema to match upstream expectations.

        Aligned with NodeJS implementation: drop unsupported keys aggressively.
        """
        if isinstance(obj, dict):
            cleaned = {}
            for key, value in obj.items():
                if key in RequestConverter.EXCLUDED_SCHEMA_KEYS:
                    continue
                cleaned[key] = RequestConverter.clean_tool_parameters_schema(value)
            return cleaned
        if isinstance(obj, list):
            return [RequestConverter.clean_tool_parameters_schema(item) for item in obj]
        return obj

    @staticmethod
    def convert_tool_choice(tool_choice, tools: List[Dict] = None) -> Dict:
        """
        将 OpenAI 的 tool_choice 转换为 Google Gemini 的 toolConfig

        Args:
            tool_choice: OpenAI 的 tool_choice 参数
                - "auto": 模型自动决定是否调用函数
                - "required": 强制模型必须调用至少一个函数
                - "none": 禁止模型调用函数
                - {"type": "function", "function": {"name": "xxx"}}: 强制调用指定函数
            tools: 工具列表（用于提取函数名）

        Returns:
            Google 格式的 toolConfig
        """
        _ = tool_choice
        _ = tools
        return {"functionCallingConfig": {"mode": "VALIDATED"}}

    @staticmethod
    def convert_tools(
        openai_tools: List[Dict],
        session_id: Optional[str] = None,
        model: Optional[str] = None,
    ) -> List[Dict]:
        """
        将 OpenAI 格式的 tools 转换为 Google Gemini 格式

        OpenAI 格式:
        [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "...",
                "parameters": {...}
            }
        }]

        Gemini 格式:
        [{
            "functionDeclarations": [{
                "name": "get_weather",
                "description": "...",
                "parameters": {...}
            }]
        }]
        """
        if not openai_tools:
            return []

        converted: List[Dict] = []
        for tool in openai_tools:
            if tool.get("type") != "function":
                continue

            func = tool.get("function") or {}
            original_name = func.get("name") or "unnamed_function"
            safe_name = sanitize_tool_name(original_name)
            if session_id and model and safe_name != original_name:
                set_tool_name_mapping(session_id, model, safe_name, original_name)

            parameters = func.get("parameters") or {}
            if isinstance(parameters, dict):
                parameters = copy.deepcopy(parameters)
                parameters = RequestConverter.clean_tool_parameters_schema(parameters)
            else:
                parameters = {}

            if parameters.get("type") is None:
                parameters["type"] = "object"
            if parameters.get("type") == "object" and not isinstance(parameters.get("properties"), dict):
                parameters["properties"] = {}

            parameters = RequestConverter.normalize_schema(parameters)

            if not RequestConverter.validate_schema(parameters, safe_name):
                logger.warning("Skipping tool %s due to invalid schema", safe_name)
                continue

            converted.append(
                {
                    "functionDeclarations": [
                        {
                            "name": safe_name,
                            "description": func.get("description", ""),
                            "parameters": parameters,
                        }
                    ]
                }
            )

        return converted

    @staticmethod
    def log_conversion_summary(openai_request: Dict, google_request: Dict) -> None:
        """
        打印一次请求转换的摘要，帮助排查 400 问题
        """
        try:
            openai_roles = [msg.get("role", "unknown") for msg in openai_request.get("messages", [])]
            google_roles = [content.get("role", "unknown") for content in google_request.get("request", {}).get("contents", [])]
            tools = []
            for tool in google_request.get("request", {}).get("tools", []):
                for decl in tool.get("functionDeclarations", []):
                    tools.append(decl.get("name"))

            logger.debug("Conversion summary - OpenAI roles: %s", openai_roles)
            logger.debug("Conversion summary - Google roles: %s", google_roles)
            logger.debug(
                "Conversion summary - tools=%s, toolConfig=%s, hasSystemInstruction=%s",
                tools or "none",
                google_request.get("request", {}).get("toolConfig"),
                "systemInstruction" in google_request.get("request", {})
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to log conversion summary: %s", exc)


class ResponseConverter:
    """响应格式转换器"""

    @staticmethod
    async def google_sse_to_openai(
        google_stream: AsyncIterator[str],
        model: str,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        将 Google SSE 流式响应转换为 OpenAI 格式

        Args:
            google_stream: Google API 的 SSE 流（字符串迭代器）
            model: 模型名称
            request_id: 请求ID（可选）

        Yields:
            OpenAI 格式的 SSE 数据行
        """
        if request_id is None:
            request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

        created = int(time.time())
        finish_reason = None
        usage_metadata = None
        state_reasoning_signature = get_reasoning_signature(session_id, model) if session_id else None

        async for line in google_stream:
            line = line.strip()

            # 跳过空行
            if not line:
                continue

            # 移除 "data: " 或 "data:" 前缀
            json_str = None
            if line.startswith('data: '):
                json_str = line[6:]  # 移除 "data: "（6个字符）
            elif line.startswith('data:'):
                json_str = line[5:]  # 移除 "data:"（5个字符）
            else:
                # 不是 SSE 数据行，跳过
                logger.debug(f"Skipping non-SSE line: {line[:50]}...")
                continue

            # 跳过 [DONE] 标记
            if json_str.strip() == '[DONE]':
                continue

            try:
                # 解析 Google 响应
                google_data = json.loads(json_str)
                response = google_data.get("response", {})
                candidates = response.get("candidates", [])

                if not candidates:
                    continue

                candidate = candidates[0]
                content_data = candidate.get("content", {})
                parts = content_data.get("parts", [])

                # 检查是否有 finishReason
                if "finishReason" in candidate:
                    finish_reason = ResponseConverter.map_finish_reason(
                        candidate["finishReason"]
                    )

                # 检查是否有 usageMetadata
                if "usageMetadata" in response:
                    usage_metadata = response["usageMetadata"]

                # 提取内容（文本、思考或函数调用）
                delta: Dict = {}
                text_parts: List[str] = []
                reasoning_parts: List[str] = []
                reasoning_signature: Optional[str] = None

                for part in parts:
                    if part.get("thought") is True:
                        reasoning_parts.append(part.get("text", ""))
                        sig = part.get("thoughtSignature")
                        if isinstance(sig, str) and sig:
                            reasoning_signature = sig
                        continue

                    if "functionCall" in part:
                        func_call = part.get("functionCall") or {}
                        thought_signature = part.get("thoughtSignature") or func_call.get("thoughtSignature")
                        if "tool_calls" not in delta:
                            delta["tool_calls"] = []

                        call_id = func_call.get("id") or f"call_{uuid.uuid4().hex[:24]}"
                        name = func_call.get("name", "")
                        if session_id and name:
                            original = get_original_tool_name(session_id, model, name)
                            if original:
                                name = original

                        tool_call_entry = {
                            "index": len(delta["tool_calls"]),
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(func_call.get("args", {})),
                            },
                        }
                        if thought_signature:
                            tool_call_entry["thoughtSignature"] = thought_signature
                            if session_id:
                                set_tool_signature(session_id, model, thought_signature)
                        delta["tool_calls"].append(tool_call_entry)
                        continue

                    if "thoughtSignature" in part:
                        sig = part.get("thoughtSignature")
                        if isinstance(sig, str) and sig:
                            reasoning_signature = sig
                        continue

                    if "text" in part:
                        text_parts.append(part.get("text", ""))

                if text_parts:
                    delta["content"] = "".join(text_parts)
                if reasoning_parts:
                    delta["reasoning_content"] = "".join(reasoning_parts)
                if reasoning_signature:
                    state_reasoning_signature = reasoning_signature
                    if session_id:
                        set_reasoning_signature(session_id, model, reasoning_signature)
                if state_reasoning_signature and (reasoning_parts or reasoning_signature):
                    delta["thoughtSignature"] = state_reasoning_signature

                # 构建 OpenAI 格式的 chunk
                openai_chunk = {
                    "id": request_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": delta,
                        "finish_reason": finish_reason
                    }]
                }

                # 添加 usage 统计（仅在最后一个 chunk 中）
                if usage_metadata and finish_reason:
                    openai_chunk["usage"] = {
                        "prompt_tokens": usage_metadata.get("promptTokenCount", 0),
                        "completion_tokens": usage_metadata.get("candidatesTokenCount", 0),
                        "total_tokens": usage_metadata.get("totalTokenCount", 0)
                    }

                yield f"data: {json.dumps(openai_chunk)}\n\n"

            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                logger.error(f"Problematic line: {repr(line[:200])}")
                logger.error(f"JSON string: {repr(json_str[:200])}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error in SSE processing: {e}")
                logger.error(f"Line: {repr(line[:200])}")
                continue

        # 发送 [DONE] 标记
        yield "data: [DONE]\n\n"

    @staticmethod
    def map_finish_reason(google_reason: str) -> str:
        """
        映射 Google 的 finishReason 到 OpenAI 格式
        """
        mapping = {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "content_filter",
            "RECITATION": "content_filter",
            "OTHER": "stop"
        }
        return mapping.get(google_reason, "stop")

    @staticmethod
    def google_non_stream_to_openai(
        google_response: Dict,
        model: str,
        session_id: Optional[str] = None,
        image_base_url: Optional[str] = None,
        image_dir: str = "data/images",
        max_images: int = 10,
    ) -> Dict:
        """
        将 Google 非流式响应转换为 OpenAI 格式

        Args:
            google_response: Google API 返回的完整响应
            model: 模型名称

        Returns:
            OpenAI 格式的聊天补全响应
        """
        request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())
        state_reasoning_signature = get_reasoning_signature(session_id, model) if session_id else None

        # 提取响应内容（Google 非流式响应可能包装在 "response" 字段中）
        if "response" in google_response:
            # 格式: {"response": {"candidates": [...], "usageMetadata": {...}}}
            response_data = google_response["response"]
            candidates = response_data.get("candidates", [])
            usage_metadata = response_data.get("usageMetadata", {})
        else:
            # 格式: {"candidates": [...], "usageMetadata": {...}}
            candidates = google_response.get("candidates", [])
            usage_metadata = google_response.get("usageMetadata", {})

        if not candidates:
            # 没有候选响应，返回空响应
            return {
                "id": request_id,
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [],
                "usage": {
                    "prompt_tokens": usage_metadata.get("promptTokenCount", 0),
                    "completion_tokens": 0,
                    "total_tokens": usage_metadata.get("promptTokenCount", 0)
                }
            }

        # 构建 choices
        choices = []
        for idx, candidate in enumerate(candidates):
            content_data = candidate.get("content", {})
            parts = content_data.get("parts", [])

            # 提取内容（文本或函数调用）
            message = {"role": "assistant"}
            text_parts: List[str] = []
            reasoning_parts: List[str] = []
            tool_calls = []
            image_urls: List[str] = []
            reasoning_signature: Optional[str] = None

            for part in parts:
                if part.get("thought") is True:
                    reasoning_parts.append(part.get("text", ""))
                    sig = part.get("thoughtSignature")
                    if isinstance(sig, str) and sig:
                        reasoning_signature = sig
                elif "text" in part:
                    text_parts.append(part.get("text", ""))
                elif "functionCall" in part:
                    func_call = part.get("functionCall") or {}
                    thought_signature = part.get("thoughtSignature") or func_call.get("thoughtSignature")
                    call_id = func_call.get("id") or f"call_{uuid.uuid4().hex[:24]}"
                    name = func_call.get("name", "")
                    if session_id and name:
                        original = get_original_tool_name(session_id, model, name)
                        if original:
                            name = original
                    tool_call_entry = {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(func_call.get("args", {}))
                        }
                    }
                    if thought_signature:
                        tool_call_entry["thoughtSignature"] = thought_signature
                        if session_id:
                            set_tool_signature(session_id, model, thought_signature)
                    tool_calls.append(tool_call_entry)
                elif "inlineData" in part:
                    inline = part.get("inlineData") or {}
                    data_b64 = inline.get("data")
                    mime_type = inline.get("mimeType")
                    if not data_b64:
                        continue
                    try:
                        filename = save_base64_image(
                            base64_data=str(data_b64),
                            mime_type=str(mime_type) if mime_type is not None else None,
                            image_dir=image_dir,
                            max_images=max_images,
                        )
                        base = (image_base_url or "").rstrip("/")
                        image_urls.append(f"{base}/images/{filename}" if base else f"/images/{filename}")
                    except Exception as exc:
                        logger.info(
                            "Failed to save inlineData image: %s (mime_type=%s, data_len=%s)",
                            exc,
                            mime_type,
                            len(str(data_b64)),
                        )
                    sig = part.get("thoughtSignature")
                    if isinstance(sig, str) and sig:
                        reasoning_signature = sig
                elif "thoughtSignature" in part:
                    sig = part.get("thoughtSignature")
                    if isinstance(sig, str) and sig:
                        reasoning_signature = sig

            # 添加内容到 message
            content_text = "".join(text_parts) if text_parts else ""
            if image_urls:
                chunks: List[str] = []
                if content_text:
                    chunks.append(content_text)
                chunks.extend([f"![image]({url})" for url in image_urls])
                message["content"] = "\n\n".join(chunks)
            elif content_text:
                message["content"] = content_text
            if reasoning_parts:
                message["reasoning_content"] = "".join(reasoning_parts)
            if reasoning_signature:
                state_reasoning_signature = reasoning_signature
                if session_id:
                    set_reasoning_signature(session_id, model, reasoning_signature)
            if state_reasoning_signature and (reasoning_parts or reasoning_signature):
                message["thoughtSignature"] = state_reasoning_signature
            if tool_calls:
                message["tool_calls"] = tool_calls

            # 映射 finishReason
            finish_reason = "stop"
            if "finishReason" in candidate:
                finish_reason = ResponseConverter.map_finish_reason(
                    candidate["finishReason"]
                )

            choices.append({
                "index": idx,
                "message": message,
                "finish_reason": finish_reason
            })

        # 构建完整响应
        return {
            "id": request_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": choices,
            "usage": {
                "prompt_tokens": usage_metadata.get("promptTokenCount", 0),
                "completion_tokens": usage_metadata.get("candidatesTokenCount", 0),
                "total_tokens": usage_metadata.get("totalTokenCount", 0)
            }
        }

    @staticmethod
    def google_models_to_openai(google_response: Dict) -> Dict:
        """
        将 Google 模型列表转换为 OpenAI 格式

        Args:
            google_response: Google API 返回的完整响应，格式为 {"models": {...}}

        Returns:
            OpenAI 格式的模型列表响应
        """
        openai_models = []

        # Google 返回的 models 是一个字典，key 是模型 ID
        models_dict = google_response.get("models", {})

        for model_id in models_dict.keys():
            # 推断所有者
            owner = "google"
            if "claude" in model_id.lower():
                owner = "anthropic"
            elif "gpt" in model_id.lower():
                owner = "openai"

            openai_models.append({
                "id": model_id,
                "object": "model",
                "created": int(time.time()),
                "owned_by": owner
            })

        return {
            "object": "list",
            "data": openai_models
        }
