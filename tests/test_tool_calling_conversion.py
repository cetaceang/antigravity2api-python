import asyncio
import json
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.converter import (  # noqa: E402
    CLAUDE_THOUGHT_SIGNATURE,
    RequestConverter,
    ResponseConverter,
    TOOL_THOUGHT_SIGNATURE,
)
from src.signature_cache import (  # noqa: E402
    clear_signature_caches,
    get_reasoning_signature,
    get_tool_signature,
    set_reasoning_signature,
    set_tool_signature,
)
from src.tool_name_cache import clear_tool_name_mappings, set_tool_name_mapping  # noqa: E402
from src.token_manager import TokenManager  # noqa: E402


def assert_no_excluded_schema_keys(obj, excluded_keys):
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key not in excluded_keys, f"unexpected schema key: {key}"
            assert_no_excluded_schema_keys(value, excluded_keys)
    elif isinstance(obj, list):
        for item in obj:
            assert_no_excluded_schema_keys(item, excluded_keys)


def test_tools_request_protocol():
    clear_tool_name_mappings()
    clear_signature_caches()

    openai_request = {
        "model": "gemini-2.5-flash",
        "stream": False,
        "messages": [{"role": "user", "content": "Hello"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get weather!",
                    "description": "Get weather",
                    "parameters": {
                        "$schema": "http://json-schema.org/draft-07/schema#",
                        "type": "object",
                        "additionalProperties": False,
                        "minProperties": 1,
                        "properties": {
                            "location": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 50,
                                "const": "Tokyo",
                            }
                        },
                        "anyOf": [{"type": "object"}],
                        "required": ["location"],
                    },
                },
            }
        ],
    }

    google_request, _suffix = RequestConverter.openai_to_google(
        openai_request=openai_request,
        project_id="proj",
        session_id="s123",
    )

    assert google_request["request"]["sessionId"] == "s123"
    assert google_request["request"]["toolConfig"]["functionCallingConfig"]["mode"] == "VALIDATED"

    tools = google_request["request"]["tools"]
    assert isinstance(tools, list) and len(tools) == 1
    decls = tools[0]["functionDeclarations"]
    assert isinstance(decls, list) and len(decls) == 1
    assert decls[0]["name"] == "get_weather"
    assert_no_excluded_schema_keys(decls[0]["parameters"], RequestConverter.EXCLUDED_SCHEMA_KEYS)

    openai_request_no_tools = {
        "model": "gemini-2.5-flash",
        "stream": False,
        "messages": [{"role": "user", "content": "Hello"}],
    }
    google_request_no_tools, _suffix = RequestConverter.openai_to_google(
        openai_request=openai_request_no_tools,
        project_id="proj",
        session_id="s123",
    )
    assert "tools" not in google_request_no_tools["request"]
    assert "toolConfig" not in google_request_no_tools["request"]


def test_session_id_is_runtime_only():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_file = Path(tmpdir) / "tokens.json"
        data_file.write_text(
            json.dumps(
                {
                    "oauth_config": {
                        "client_id": "x",
                        "client_secret": "y",
                        "token_url": "https://oauth2.googleapis.com/token",
                    },
                    "projects": [
                        {
                            "project_id": "proj",
                            "refresh_token": "rt",
                            "access_token": None,
                            "expires_at": None,
                            "enabled": True,
                            "disabled_reason": None,
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        manager = TokenManager(data_file=str(data_file))
        assert len(manager.projects) == 1
        session_id = manager.projects[0].session_id
        assert isinstance(session_id, str) and session_id.startswith("-")

        manager.save_tokens()
        saved = json.loads(data_file.read_text(encoding="utf-8"))
        assert "session_id" not in json.dumps(saved), "session_id must not be persisted"


def test_request_thought_signature_fallback_and_tool_response_linking():
    clear_tool_name_mappings()
    clear_signature_caches()

    session_id = "s123"
    model = "gemini-2.5-flash-thinking"
    tool_call_id = "call_abc"

    openai_request = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "user", "content": "Call a tool"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": tool_call_id,
                        "type": "function",
                        "function": {"name": "get weather!", "arguments": "{\"location\":\"Tokyo\"}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": "get weather!",
                "content": {"ok": True},
            },
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get weather!",
                    "description": "Get weather",
                    "parameters": {"type": "object", "properties": {"location": {"type": "string"}}},
                },
            }
        ],
    }

    google_request, _suffix = RequestConverter.openai_to_google(
        openai_request=openai_request,
        project_id="proj",
        session_id=session_id,
    )

    contents = google_request["request"]["contents"]
    model_entries = [c for c in contents if c.get("role") == "model"]
    assert model_entries, "expected at least one model entry"
    model_parts = model_entries[0]["parts"]
    assert any("thoughtSignature" in p for p in model_parts), "missing injected thoughtSignature part"

    tool_call_parts = [p for p in model_parts if "functionCall" in p]
    assert tool_call_parts and tool_call_parts[0]["functionCall"]["id"] == tool_call_id
    assert tool_call_parts[0].get("thoughtSignature") == TOOL_THOUGHT_SIGNATURE

    user_entries = [c for c in contents if c.get("role") == "user"]
    assert user_entries, "expected user entries"
    function_responses = []
    for entry in user_entries:
        for part in entry.get("parts", []):
            if "functionResponse" in part:
                function_responses.append(part["functionResponse"])
    assert function_responses, "expected functionResponse parts"
    fr = function_responses[-1]
    assert fr["id"] == tool_call_id
    assert fr["name"] == "get_weather"
    assert isinstance(fr["response"]["output"], str)

    clear_signature_caches()
    set_reasoning_signature(session_id, model, "cached_reasoning")
    set_tool_signature(session_id, model, "cached_tool")

    google_request_cached, _suffix = RequestConverter.openai_to_google(
        openai_request=openai_request,
        project_id="proj",
        session_id=session_id,
    )
    model_parts_cached = [c for c in google_request_cached["request"]["contents"] if c.get("role") == "model"][0][
        "parts"
    ]
    signature_parts = [p for p in model_parts_cached if "thoughtSignature" in p and p.get("text") == " "]
    assert signature_parts and signature_parts[0]["thoughtSignature"] == "cached_reasoning"
    tool_call_parts_cached = [p for p in model_parts_cached if "functionCall" in p]
    assert tool_call_parts_cached[0].get("thoughtSignature") == "cached_tool"


def test_claude_tool_signature_fallback_uses_claude_signature():
    clear_tool_name_mappings()
    clear_signature_caches()

    session_id = "s123"
    model = "claude-opus-4-5-thinking"
    tool_call_id = "call_abc"

    openai_request = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "user", "content": "Call a tool"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": tool_call_id,
                        "type": "function",
                        "function": {"name": "get weather!", "arguments": "{\"location\":\"Tokyo\"}"},
                    }
                ],
            },
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get weather!",
                    "description": "Get weather",
                    "parameters": {"type": "object", "properties": {"location": {"type": "string"}}},
                },
            }
        ],
    }

    google_request, _suffix = RequestConverter.openai_to_google(
        openai_request=openai_request,
        project_id="proj",
        session_id=session_id,
    )

    model_entry = [c for c in google_request["request"]["contents"] if c.get("role") == "model"][0]
    tool_call_parts = [p for p in model_entry["parts"] if "functionCall" in p]
    assert tool_call_parts, "expected functionCall parts"
    assert tool_call_parts[0].get("thoughtSignature") == CLAUDE_THOUGHT_SIGNATURE


def test_response_signature_passthrough_and_cache_write_non_stream():
    clear_tool_name_mappings()
    clear_signature_caches()

    session_id = "s123"
    model = "gemini-2.5-flash-thinking"
    set_tool_name_mapping(session_id, model, "safe_name", "original_name")

    google_response = {
        "response": {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "reason", "thoughtSignature": "sig_reason"},
                            {
                                "functionCall": {
                                    "id": "call_1",
                                    "name": "safe_name",
                                    "args": {"x": 1},
                                },
                                "thoughtSignature": "sig_tool",
                            },
                            {"text": "ok"},
                        ]
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
        }
    }

    openai_response = ResponseConverter.google_non_stream_to_openai(
        google_response=google_response,
        model=model,
        session_id=session_id,
    )
    message = openai_response["choices"][0]["message"]
    assert message["reasoning_content"] == "reason"
    assert message["thoughtSignature"] == "sig_reason"
    assert message["content"] == "ok"

    tool_calls = message["tool_calls"]
    assert tool_calls and tool_calls[0]["id"] == "call_1"
    assert tool_calls[0]["thoughtSignature"] == "sig_tool"
    assert tool_calls[0]["function"]["name"] == "original_name"

    assert get_reasoning_signature(session_id, model) == "sig_reason"
    assert get_tool_signature(session_id, model) == "sig_tool"


async def _agen(items):
    for item in items:
        yield item


def test_response_signature_passthrough_stream():
    clear_tool_name_mappings()
    clear_signature_caches()

    session_id = "s123"
    model = "gemini-2.5-flash-thinking"
    set_tool_name_mapping(session_id, model, "safe_name", "original_name")

    google_payload = {
        "response": {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "r", "thoughtSignature": "sig_reason"},
                            {
                                "functionCall": {"id": "call_1", "name": "safe_name", "args": {"x": 1}},
                                "thoughtSignature": "sig_tool",
                            },
                            {"text": "t"},
                        ]
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
        }
    }

    async def run():
        chunks = []
        async for out in ResponseConverter.google_sse_to_openai(
            _agen([f"data: {json.dumps(google_payload)}", "data: [DONE]"]),
            model=model,
            request_id="chatcmpl-test",
            session_id=session_id,
        ):
            chunks.append(out)
        return chunks

    chunks = asyncio.run(run())
    data_lines = [c for c in chunks if c.startswith("data: {")]
    assert data_lines, "expected at least one json chunk"
    payload = json.loads(data_lines[0][6:].strip())
    delta = payload["choices"][0]["delta"]
    assert delta["reasoning_content"] == "r"
    assert delta["thoughtSignature"] == "sig_reason"
    assert delta["content"] == "t"
    assert delta["tool_calls"][0]["id"] == "call_1"
    assert delta["tool_calls"][0]["thoughtSignature"] == "sig_tool"
    assert delta["tool_calls"][0]["function"]["name"] == "original_name"

    assert get_reasoning_signature(session_id, model) == "sig_reason"
    assert get_tool_signature(session_id, model) == "sig_tool"


def test_signature_cache_ttl_and_size_limits():
    import src.signature_cache as sig_cache

    sig_cache.clear_signature_caches()
    original_time = sig_cache.time.time
    now = 1000.0

    def fake_time():
        return now

    sig_cache.time.time = fake_time
    try:
        sig_cache.set_reasoning_signature("s1", "m", "sig")
        assert sig_cache.get_reasoning_signature("s1", "m") == "sig"

        now += sig_cache.ENTRY_TTL_SECONDS + 1
        assert sig_cache.get_reasoning_signature("s1", "m") is None

        now = 2000.0
        for i in range(sig_cache.MAX_REASONING_ENTRIES + 16):
            sig_cache.set_reasoning_signature(f"s{i}", "m", f"sig{i}")
        assert len(sig_cache._reasoning_cache) <= sig_cache.MAX_REASONING_ENTRIES
    finally:
        sig_cache.time.time = original_time


def main():
    test_tools_request_protocol()
    test_session_id_is_runtime_only()
    test_request_thought_signature_fallback_and_tool_response_linking()
    test_claude_tool_signature_fallback_uses_claude_signature()
    test_response_signature_passthrough_and_cache_write_non_stream()
    test_response_signature_passthrough_stream()
    test_signature_cache_ttl_and_size_limits()
    print("OK")


if __name__ == "__main__":
    main()
