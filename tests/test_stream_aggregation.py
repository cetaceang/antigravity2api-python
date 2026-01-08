import asyncio
import base64
import json
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.converter import ResponseConverter  # noqa: E402


async def _agen(items):
    for item in items:
        yield item


def _png_1x1_base64() -> str:
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/xcAAn8B9p0iZQAAAABJRU5ErkJggg=="
    )
    return base64.b64encode(png_bytes).decode("ascii")


def test_openai_sse_aggregation_with_inline_data():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        google_events = [
            {
                "response": {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"text": "Here is an image:"},
                                    {"inlineData": {"mimeType": "image/png", "data": _png_1x1_base64()}},
                                ]
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
                }
            }
        ]

        async def run():
            openai_chunks = ResponseConverter.google_sse_to_openai(
                _agen([f"data: {json.dumps(google_events[0])}", "data: [DONE]"]),
                model="gemini-3-pro-image",
                request_id="chatcmpl-test",
                session_id="s123",
                image_base_url="http://localhost:8000",
                image_dir=str(tmp),
                max_images=10,
            )
            return await ResponseConverter.openai_sse_to_non_stream(openai_chunks)

        response = asyncio.run(run())
        message = response["choices"][0]["message"]
        assert "Here is an image:" in message.get("content", "")
        assert "![image](" in message.get("content", "")
        assert "/images/" in message.get("content", "")

        created_files = list(tmp.iterdir())
        assert len(created_files) == 1
        assert created_files[0].suffix == ".png"


def test_openai_sse_aggregation_tool_calls():
    google_payload = {
        "response": {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "a"},
                            {"functionCall": {"id": "call_1", "name": "tool", "args": {"x": 1}}},
                            {"text": "b"},
                        ]
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
        }
    }

    async def run():
        openai_chunks = ResponseConverter.google_sse_to_openai(
            _agen([f"data: {json.dumps(google_payload)}", "data: [DONE]"]),
            model="gemini-2.5-flash",
            request_id="chatcmpl-test",
            session_id=None,
        )
        return await ResponseConverter.openai_sse_to_non_stream(openai_chunks)

    response = asyncio.run(run())
    message = response["choices"][0]["message"]
    assert message.get("content") == "ab"
    tool_calls = message.get("tool_calls") or []
    assert len(tool_calls) == 1
    assert tool_calls[0]["id"] == "call_1"
    assert tool_calls[0]["function"]["name"] == "tool"
    assert json.loads(tool_calls[0]["function"]["arguments"]) == {"x": 1}

