"""
测试工具调用功能

使用 OpenAI SDK 测试 antigravity2api 的工具调用功能
"""

from openai import OpenAI
import json

# 配置客户端
client = OpenAI(
    api_key="Xuhaoan19780904",  # 替换为你的 API key
    base_url="http://localhost:8000/v1"
)

# 定义工具
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather in a given location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state, e.g. San Francisco, CA"
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "The temperature unit"
                    }
                },
                "required": ["location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_meeting",
            "description": "Schedule a meeting with specified attendees",
            "parameters": {
                "type": "object",
                "properties": {
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of people attending"
                    },
                    "date": {
                        "type": "string",
                        "description": "Date of the meeting (e.g., '2024-07-29')"
                    },
                    "time": {
                        "type": "string",
                        "description": "Time of the meeting (e.g., '15:00')"
                    },
                    "topic": {
                        "type": "string",
                        "description": "The subject or topic of the meeting"
                    }
                },
                "required": ["attendees", "date", "time", "topic"]
            }
        }
    }
]

def test_basic_function_calling():
    """测试基础工具调用（tool_choice="auto"）"""
    print("\n=== 测试 1: 基础工具调用 (tool_choice='auto') ===")

    try:
        response = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[
                {"role": "user", "content": "What's the weather like in Beijing?"}
            ],
            tools=tools,
            tool_choice="auto",
            stream=False
        )

        print(f"✓ 请求成功")
        print(f"Response: {response.choices[0].message}")

        if response.choices[0].message.tool_calls:
            print(f"✓ 模型调用了工具:")
            for tool_call in response.choices[0].message.tool_calls:
                print(f"  - {tool_call.function.name}({tool_call.function.arguments})")
        else:
            print(f"✓ 模型没有调用工具，直接回复: {response.choices[0].message.content}")

    except Exception as e:
        print(f"✗ 请求失败: {e}")
        return False

    return True

def test_required_function_calling():
    """测试强制工具调用（tool_choice="required"）"""
    print("\n=== 测试 2: 强制工具调用 (tool_choice='required') ===")

    try:
        response = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[
                {"role": "user", "content": "Schedule a meeting with Bob and Alice for tomorrow at 10 AM about Q3 planning"}
            ],
            tools=tools,
            tool_choice="required",
            stream=False
        )

        print(f"✓ 请求成功")

        if response.choices[0].message.tool_calls:
            print(f"✓ 模型调用了工具:")
            for tool_call in response.choices[0].message.tool_calls:
                print(f"  - {tool_call.function.name}({tool_call.function.arguments})")
        else:
            print(f"✗ 模型没有调用工具（应该强制调用）")
            return False

    except Exception as e:
        print(f"✗ 请求失败: {e}")
        return False

    return True

def test_specific_function_calling():
    """测试指定函数调用"""
    print("\n=== 测试 3: 指定函数调用 (tool_choice=specific) ===")

    try:
        response = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[
                {"role": "user", "content": "What's the weather?"}
            ],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "get_weather"}},
            stream=False
        )

        print(f"✓ 请求成功")

        if response.choices[0].message.tool_calls:
            tool_call = response.choices[0].message.tool_calls[0]
            if tool_call.function.name == "get_weather":
                print(f"✓ 模型调用了指定的工具: {tool_call.function.name}")
            else:
                print(f"✗ 模型调用了错误的工具: {tool_call.function.name}")
                return False
        else:
            print(f"✗ 模型没有调用工具")
            return False

    except Exception as e:
        print(f"✗ 请求失败: {e}")
        return False

    return True

def test_multi_turn_conversation():
    """测试多轮对话（工具调用 + 工具响应）"""
    print("\n=== 测试 4: 多轮对话 ===")

    try:
        # 第一轮：用户请求
        response1 = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[
                {"role": "user", "content": "What's the weather in Tokyo?"}
            ],
            tools=tools,
            tool_choice="auto",
            stream=False
        )

        print(f"✓ 第一轮请求成功")

        if not response1.choices[0].message.tool_calls:
            print(f"✗ 模型没有调用工具")
            return False

        tool_call = response1.choices[0].message.tool_calls[0]
        print(f"✓ 模型调用了工具: {tool_call.function.name}")

        # 模拟工具执行
        tool_response = {
            "location": "Tokyo",
            "temperature": 22,
            "unit": "celsius",
            "condition": "sunny"
        }

        # 第二轮：发送工具响应
        response2 = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[
                {"role": "user", "content": "What's the weather in Tokyo?"},
                response1.choices[0].message,
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": json.dumps(tool_response)
                }
            ],
            tools=tools,
            stream=False
        )

        print(f"✓ 第二轮请求成功")
        print(f"✓ 模型回复: {response2.choices[0].message.content}")

    except Exception as e:
        print(f"✗ 请求失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True

def test_streaming_function_calling():
    """测试流式工具调用"""
    print("\n=== 测试 5: 流式工具调用 ===")

    try:
        stream = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[
                {"role": "user", "content": "What's the weather in Paris?"}
            ],
            tools=tools,
            tool_choice="auto",
            stream=True
        )

        print(f"✓ 流式请求成功")

        tool_calls = []
        for chunk in stream:
            if chunk.choices[0].delta.tool_calls:
                tool_calls.extend(chunk.choices[0].delta.tool_calls)

        if tool_calls:
            print(f"✓ 收到工具调用:")
            for tool_call in tool_calls:
                if hasattr(tool_call, 'function') and tool_call.function:
                    print(f"  - {tool_call.function.name}")
        else:
            print(f"✓ 没有工具调用（流式响应正常）")

    except Exception as e:
        print(f"✗ 请求失败: {e}")
        return False

    return True

if __name__ == "__main__":
    print("开始测试工具调用功能...")
    print("=" * 60)

    results = []

    # 运行所有测试
    results.append(("基础工具调用", test_basic_function_calling()))
    results.append(("强制工具调用", test_required_function_calling()))
    results.append(("指定函数调用", test_specific_function_calling()))
    results.append(("多轮对话", test_multi_turn_conversation()))
    results.append(("流式工具调用", test_streaming_function_calling()))

    # 输出总结
    print("\n" + "=" * 60)
    print("测试总结:")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{status} - {name}")

    print(f"\n总计: {passed}/{total} 测试通过")

    if passed == total:
        print("\n🎉 所有测试通过！工具调用功能正常工作。")
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败，请检查日志。")
