"""协议转换模块 - OpenAI ↔ Google Gemini 格式转换"""
import copy
import json
import logging
import time
import uuid
from typing import Dict, List, Tuple, Optional, AsyncGenerator, AsyncIterator

# 配置日志
logger = logging.getLogger(__name__)


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

    @staticmethod
    def openai_to_google(
        openai_request: Dict,
        project_id: str
    ) -> Tuple[Dict, str]:
        """
        将 OpenAI 格式请求转换为 Google Gemini 格式

        返回: (google_request, url_suffix)
        """
        messages = openai_request.get("messages", [])
        model = openai_request.get("model", "gemini-2.5-flash")
        stream = openai_request.get("stream", False)

        # 提取 system 消息和普通消息
        system_instruction, contents = RequestConverter.extract_system_instruction(messages)
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

        thinking_config = RequestConverter.determine_thinking_config(model)
        if thinking_config:
            generation_config["thinkingConfig"] = thinking_config

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

        # 添加 systemInstruction
        if system_instruction:
            google_request["request"]["systemInstruction"] = system_instruction

        # 添加 generationConfig
        if generation_config:
            google_request["request"]["generationConfig"] = generation_config

        # 转换 tools（函数调用）
        if "tools" in openai_request:
            google_tools = RequestConverter.convert_tools(openai_request["tools"])
            if google_tools:
                google_request["request"]["tools"] = google_tools

                # 添加 toolConfig（必需！）
                tool_choice = openai_request.get("tool_choice", "auto")
                tool_config = RequestConverter.convert_tool_choice(tool_choice, openai_request.get("tools", []))
                if tool_config:
                    google_request["request"]["toolConfig"] = tool_config

        RequestConverter.log_conversion_summary(openai_request, google_request)

        # URL 后缀
        # 流式：使用 streamGenerateContent + alt=sse
        # 非流式：使用 generateContent
        url_suffix = "/v1internal:streamGenerateContent?alt=sse" if stream else "/v1internal:generateContent"

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
    def extract_system_instruction(messages: List[Dict]) -> Tuple[Optional[Dict], List[Dict]]:
        """
        从消息列表中提取 system 消息和普通消息

        返回: (system_instruction, contents)
        """
        system_messages = []
        contents = []
        tool_call_info_map: Dict[str, Dict[str, str]] = {}
        collecting_system = True

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
                parts = RequestConverter.convert_content_to_parts(content)
                tool_calls = msg.get("tool_calls", [])
                for tool_call in tool_calls:
                    if tool_call.get("type") != "function":
                        continue
                    func = tool_call.get("function", {})
                    func_name = func.get("name")
                    if not func_name:
                        continue
                    tool_call_id = tool_call.get("id")
                    signature = tool_call.get("thought_signature") or tool_call.get("thoughtSignature")
                    if not signature and tool_call_id and not str(tool_call_id).startswith("call_"):
                        signature = str(tool_call_id)
                    if tool_call_id:
                        tool_call_info_map[tool_call_id] = {
                            "name": func_name,
                            "thoughtSignature": signature
                        }
                        logger.info(
                            "Mapped tool_call_id '%s' to function '%s' with signature '%s'",
                            tool_call_id,
                            func_name,
                            signature
                        )
                    args_data = func.get("arguments", "{}")
                    args = json.loads(args_data) if isinstance(args_data, str) else args_data
                    part_entry = {
                        "functionCall": {
                            "name": func_name,
                            "args": args
                        }
                    }
                    if signature:
                        part_entry["thoughtSignature"] = signature
                    parts.append(part_entry)

                contents.append({
                    "role": "model",
                    "parts": parts
                })
            elif role == "tool":
                function_response = RequestConverter.convert_tool_message(msg, tool_call_info_map)
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
        tool_name = msg.get("name", "")
        tool_call_id = msg.get("tool_call_id", "")
        thought_signature = (
            msg.get("thought_signature")
            or msg.get("thoughtSignature")
        )

        if tool_call_id and tool_call_id in tool_call_info_map:
            info = tool_call_info_map[tool_call_id]
            tool_name = tool_name or info.get("name", "")
            thought_signature = thought_signature or info.get("thoughtSignature")
        elif tool_call_id and not thought_signature and not str(tool_call_id).startswith("call_"):
            thought_signature = str(tool_call_id)

        if not tool_name:
            logger.warning("Tool message missing 'name' field: %s", msg)
            if tool_call_id:
                logger.warning("Found tool_call_id: %s, but cannot map to function name without context", tool_call_id)
            tool_name = "unknown_function"

        response_data = msg.get("content")
        if isinstance(response_data, str):
            try:
                response_data = json.loads(response_data)
            except (json.JSONDecodeError, ValueError):
                response_data = {"result": response_data}
        elif not isinstance(response_data, dict):
            response_data = {"result": str(response_data)}

        part = {
            "functionResponse": {
                "name": tool_name,
                "response": response_data
            }
        }
        if thought_signature:
            part["thoughtSignature"] = thought_signature
        return part

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

        # 去除多余元数据字段（保留 $ref/$defs 等结构性引用）
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
        if not tool_choice:
            # 默认为 AUTO
            return {
                "functionCallingConfig": {
                    "mode": "AUTO"
                }
            }

        if isinstance(tool_choice, str):
            # 字符串模式: "auto", "required", "none"
            mode_mapping = {
                "auto": "AUTO",
                "required": "ANY",
                "none": "NONE"
            }
            mode = mode_mapping.get(tool_choice.lower(), "AUTO")
            return {
                "functionCallingConfig": {
                    "mode": mode
                }
            }

        elif isinstance(tool_choice, dict):
            # 对象模式: {"type": "function", "function": {"name": "xxx"}}
            if tool_choice.get("type") == "function":
                func_name = tool_choice.get("function", {}).get("name")
                if func_name:
                    return {
                        "functionCallingConfig": {
                            "mode": "ANY",
                            "allowedFunctionNames": [func_name]
                        }
                    }

        # 默认返回 AUTO
        return {
            "functionCallingConfig": {
                "mode": "AUTO"
            }
        }

    @staticmethod
    def convert_tools(openai_tools: List[Dict]) -> List[Dict]:
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

        function_declarations = []
        for tool in openai_tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                parameters = func.get("parameters", {})
                if isinstance(parameters, dict):
                    parameters = copy.deepcopy(parameters)
                    parameters = RequestConverter.clean_schema_metadata(parameters)
                    parameters = RequestConverter.normalize_schema(parameters)
                else:
                    parameters = {}

                tool_name = func.get("name") or "unnamed_function"
                if not RequestConverter.validate_schema(parameters, tool_name):
                    logger.warning("Skipping tool %s due to invalid schema", tool_name)
                    continue

                function_declarations.append({
                    "name": func.get("name"),
                    "description": func.get("description", ""),
                    "parameters": parameters
                })
        if not function_declarations:
            return []

        return [{
            "functionDeclarations": function_declarations
        }]

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
        request_id: Optional[str] = None
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
                reasoning_parts: List[Dict] = []

                for part in parts:
                    if part.get("thought") is True:
                        reasoning_entry = {
                            "type": "text",
                            "text": part.get("text", "")
                        }
                        thought_signature = part.get("thoughtSignature")
                        if thought_signature:
                            reasoning_entry["thought_signature"] = thought_signature
                        reasoning_parts.append(reasoning_entry)
                        continue

                    if "text" in part:
                        # 文本内容
                        text_parts.append(part.get("text", ""))
                    elif "functionCall" in part:
                        # 函数调用
                        func_call = part["functionCall"]
                        thought_signature = part.get("thoughtSignature") or func_call.get("thoughtSignature")
                        if "tool_calls" not in delta:
                            delta["tool_calls"] = []
                        call_id = thought_signature or f"call_{uuid.uuid4().hex[:24]}"
                        tool_call_entry = {
                            "index": len(delta["tool_calls"]),
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": func_call.get("name", ""),
                                "arguments": json.dumps(func_call.get("args", {}))
                            }
                        }
                        if thought_signature:
                            tool_call_entry["thought_signature"] = thought_signature
                        delta["tool_calls"].append(tool_call_entry)

                if text_parts:
                    delta["content"] = "".join(text_parts)
                if reasoning_parts:
                    delta["reasoning_content"] = reasoning_parts

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
    def google_non_stream_to_openai(google_response: Dict, model: str) -> Dict:
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
            reasoning_parts: List[Dict] = []
            tool_calls = []

            for part in parts:
                if part.get("thought") is True:
                    reasoning_entry = {
                        "type": "text",
                        "text": part.get("text", "")
                    }
                    thought_signature = part.get("thoughtSignature")
                    if thought_signature:
                        reasoning_entry["thought_signature"] = thought_signature
                    reasoning_parts.append(reasoning_entry)
                elif "text" in part:
                    text_parts.append(part.get("text", ""))
                elif "functionCall" in part:
                    func_call = part["functionCall"]
                    thought_signature = part.get("thoughtSignature") or func_call.get("thoughtSignature")
                    call_id = thought_signature or f"call_{uuid.uuid4().hex[:24]}"
                    tool_call_entry = {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": func_call.get("name", ""),
                            "arguments": json.dumps(func_call.get("args", {}))
                        }
                    }
                    if thought_signature:
                        tool_call_entry["thought_signature"] = thought_signature
                    tool_calls.append(tool_call_entry)

            # 添加内容到 message
            if text_parts:
                message["content"] = "".join(text_parts)
            if reasoning_parts:
                message["reasoning_content"] = reasoning_parts
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
