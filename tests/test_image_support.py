import base64
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.converter import RequestConverter, ResponseConverter  # noqa: E402


def _png_1x1_base64() -> str:
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/xcAAn8B9p0iZQAAAABJRU5ErkJggg=="
    )
    return base64.b64encode(png_bytes).decode("ascii")


def _urlsafe_base64_no_padding() -> str:
    raw = b"\xff\xff"
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_image_request_is_converted_to_image_gen():
    openai_request = {
        "model": "gemini-3-pro-image",
        "stream": True,
        "messages": [{"role": "user", "content": "Generate an image"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "noop",
                    "description": "noop",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    }

    google_request, url_suffix = RequestConverter.openai_to_google(
        openai_request=openai_request,
        project_id="proj",
        session_id="s123",
    )

    assert url_suffix == "/v1internal:generateContent"
    assert google_request.get("requestType") == "image_gen"
    assert google_request["request"]["generationConfig"] == {"candidateCount": 1}
    assert "tools" not in google_request["request"]
    assert "toolConfig" not in google_request["request"]
    assert "systemInstruction" not in google_request["request"]


def test_inline_data_is_persisted_and_returned_as_markdown():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        google_response = {
            "response": {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {"text": "Here is an image:"},
                                {"inlineData": {"mimeType": "image/png", "data": _png_1x1_base64()}},
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
            }
        }

        openai_response = ResponseConverter.google_non_stream_to_openai(
            google_response=google_response,
            model="gemini-3-pro-image",
            session_id="s123",
            image_base_url="http://localhost:8000",
            image_dir=str(tmp),
            max_images=10,
        )

        message = openai_response["choices"][0]["message"]
        assert "![image](" in message.get("content", "")
        assert "/images/" in message.get("content", "")

        created_files = list(tmp.iterdir())
        assert len(created_files) == 1
        assert created_files[0].suffix == ".png"


def test_inline_data_urlsafe_without_padding_is_persisted():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        google_response = {
            "response": {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {"inlineData": {"mimeType": "image/png", "data": _urlsafe_base64_no_padding()}},
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
            }
        }

        openai_response = ResponseConverter.google_non_stream_to_openai(
            google_response=google_response,
            model="gemini-3-pro-image",
            session_id="s123",
            image_base_url="http://localhost:8000",
            image_dir=str(tmp),
            max_images=10,
        )

        message = openai_response["choices"][0]["message"]
        assert "![image](" in message.get("content", "")
        assert "/images/" in message.get("content", "")

        created_files = list(tmp.iterdir())
        assert len(created_files) == 1
        assert created_files[0].suffix == ".png"


def test_inline_data_with_thought_signature_is_persisted():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        google_response = {
            "response": {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "inlineData": {"mimeType": "image/png", "data": _png_1x1_base64()},
                                    "thoughtSignature": "sig-123",
                                }
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
            }
        }

        openai_response = ResponseConverter.google_non_stream_to_openai(
            google_response=google_response,
            model="gemini-3-pro-image",
            session_id="s123",
            image_base_url="http://localhost:8000",
            image_dir=str(tmp),
            max_images=10,
        )

        message = openai_response["choices"][0]["message"]
        assert "![image](" in message.get("content", "")
        assert "/images/" in message.get("content", "")
        assert message.get("thoughtSignature") == "sig-123"

        created_files = list(tmp.iterdir())
        assert len(created_files) == 1
        assert created_files[0].suffix == ".png"


def main():
    test_image_request_is_converted_to_image_gen()
    test_inline_data_is_persisted_and_returned_as_markdown()
    test_inline_data_urlsafe_without_padding_is_persisted()
    test_inline_data_with_thought_signature_is_persisted()
    print("OK")


if __name__ == "__main__":
    main()
