import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.converter import RequestConverter, UPSTREAM_REQUIRED_SYSTEM_PROMPT  # noqa: E402


def test_system_prompt_is_fixed_and_system_role_is_downgraded_to_user():
    openai_request = {
        "model": "gemini-2.5-flash",
        "stream": False,
        "messages": [
            {"role": "system", "content": "client system message"},
            {"role": "user", "content": "hello"},
        ],
    }

    google_request, _suffix = RequestConverter.openai_to_google(
        openai_request=openai_request,
        project_id="proj",
        session_id="s123",
    )

    assert google_request.get("requestType") == "agent"

    system_text = google_request["request"]["systemInstruction"]["parts"][0]["text"]
    assert system_text == UPSTREAM_REQUIRED_SYSTEM_PROMPT
    assert google_request["request"]["systemInstruction"]["role"] == "user"

    contents = google_request["request"]["contents"]
    assert contents[0]["role"] == "user"
    assert contents[0]["parts"] == [{"text": "client system message"}]
    assert contents[1]["role"] == "user"
    assert contents[1]["parts"] == [{"text": "hello"}]


def main():
    test_system_prompt_is_fixed_and_system_role_is_downgraded_to_user()
    print("OK")


if __name__ == "__main__":
    main()
