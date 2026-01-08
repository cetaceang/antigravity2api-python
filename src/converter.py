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
    "EqoNCqcNAXLI2nwkidsFconk7xHt7x0zIOX7n/JR7DTKiPa/03uqJ9OmZaujaw0xNQxZ0wNCx8NguJ+sAfaIpek62+aBnc"
    "iUTQd5UEmwM/V5o6EA2wPvv4IpkXyl6Eyvr8G+jD/U4c2Tu4M4WzVhcImt9Lf/ZH6zydhxgU9ZgBtMwck292wuThVNqCZh"
    "9akqy12+BPHs9zW8IrPGv3h3u64Q2Ye9Mzx+EtpV2Tiz8mcq4whdUu72N6LQVQ+xLLdzZ+CQ7WgEjkqOWQs2C09DlAsdu5"
    "vjLeF5ZgpL9seZIag9Dmhuk589l/I20jGgg7EnCgojzarBPHNOCHrxTbcp325tTLPa6Y7U4PgofJEkv0MX4O22mu/On6Tx"
    "AlqYkVa6twdEHYb+zMFWQl7SVFwQTY9ub7zeSaW+p/yJ+5H43LzC95aEcrfTaX0P2cDWGrQ1IVtoaEWPi7JVOtDSqchVC1"
    "YLRbIUHaWGyAysx7BRoSBIr46aVbGNy2Xvt35Vqt0tDJRyBdRuKXTmf1px6mbDpsjldxE/YLzCkCtAp1Ji1X9XPFhZbj7H"
    "TNIjCRfIeHA/6IyOB0WgBiCw5e2p50frlixd+iWD3raPeS/VvCBvn/DPCsnH8lzgpDQqaYeN/y0K5UWeMwFUg+00YFoN9D"
    "34q6q3PV9yuj1OGT2l/DzCw8eR5D460S6nQtYOaEsostvCgJGipamf/dnUzHomoiqZegJzfW7uzIQl1HJXQJTnpTmk07Lar"
    "QwxIPtId9JP+dXKLZMw5OAYWITfSXF5snb7F1jdN0NydJOVkeanMsxnbIyU7/iKLDWJAmcRru/GavbJGgB0vJgY52SkPi9+"
    "uhfF8u60gLqFpbhsal3oxSPJSzeg+TN/qktBGST2YvLHxilPKmLBhggTUZhDSzSjxPfseE41FHYniyn6O+b3tujCdvexnrI"
    "jmmX+KTQC3ovjfk/ArwImI/cGihFYOc+wDnri5iHofdLbFymE/xb1Q4Sn06gVq1sgmeeS/li0F6C0v9GqOQ4olqQrTT2PPD"
    "VMbDrXgjZMfHk9ciqQ5OB6r19uyIqb6lFplKsE/ZSacAGtw1K0HENMq9q576m0beUTtNRJMktXem/OJIDbpRE0cXfBt1J9V"
    "xYHBe6aEiIZmRzJnXtJmUCjqfLPg9n0FKUIjnnln7as+aiRpItb5ZfJjrMEu154ePgUa1JYv2MA8oj5rvzpxRSxycD2p8HT"
    "xshitnLFI8Q6Kl2gUqBI27uzYSPyBtrvWZaVtrXYMiyjOFBdjUFunBIW2UvoPSKYEaNrUO3tTSYO4GjgLsfCRQ2CMfclq/T"
    "bCALjvzjMaYLrn6OKQnSDI/Tt1J6V6pDXfSyLdCIDg77NTvdqTH2Cv3yT3fE3nOOW5mUPZtXAIxPkFGo9eL+YksEgLIeZor"
    "0pdb+BHs1kQ4z7EplCYVhpTbo6fMcarW35Qew9HPMTFQ03rQaDhlNnUUI3tacnDMQvKsfo4OPTQYG2zP4lHXSsf4IpGRJyT"
    "BuMGK6siiKBiL/u73HwKTDEu2RU/4ZmM6dQJkoh+6sXCCmoZuweYOeF2cAx2AJAHD72qmEPzLihm6bWeSRXDxJGm2RO85Ng"
    "K5khNfV2Mm1etmQdDdbTLJV5FTvJQJ5zVDnYQkk7SKDio9rQMBucw5M6MyvFFDFdzJQlVKZm/GZ5T21GsmNHMJNd9G2qYAK"
    "wUV3Mb64Ipk681x8TFG+1AwkfzSWCHnbXMG2bOX+JUt/4rldyRypArvxhyNimEDc7HoqSHwTVfpd6XA0u8emcQR1t+xAR2B"
    "iT/elQHecAvhRtJt+ts44elcDIzTCBiJG4DEoV8X0pHb1oTLJFcD8aF29BWczl4kYDPtR9Dtlyuvmaljt0OEeLz9zS0MGvpf"
    "lvMtUmFdGq7ZP+GztIdWup4kZZ59pzTuSR9itskMAnqYj+V9YBCSUUmsxW6Zj4Uvzw0nLYsjIgTjP3SU9WvwUhvJWzu5wZk"
    "du3e03YoGxUjLWDXMKeSZ/g2Th5iNn3xlJwp5Z2p0jsU1rH4K/iMsYiLBJkGnsYuBqqFt2UIPYziqxOKV41oSKdEU+n4mD3W"
    "arU/kR4krTkmmEj2aebWgvHpsZSW0ULaeK3QxNBdx7waBUUkZ7nnDIRDi31T/sBYl+UADEFvm2INIsFuXPUyXbAthNWn5vIQ"
    "NlKNLCwpGYqhuzO4hno8vyqbxKsrMtayk1U+0TQsBbQY1VuFF2bDBNFcPQOv/7KPJDL8hal0U6J0E6DVZVcH4Gel7pgsBeC"
    "+48="
)

# Upstream API validates the exact system prompt content. Keep this value stable.
def _decode_upstream_prompt_json(json_text: str) -> str:
    try:
        decoded = json.loads(json_text)
        return decoded if isinstance(decoded, str) else str(decoded)
    except Exception:
        return json_text


UPSTREAM_REQUIRED_SYSTEM_PROMPT_JSON = (
    r'"<identity>\nYou are Antigravity, a powerful agentic AI coding assistant designed by the Google Deepmind team working on Advanced Agentic Coding.\nYou are pair programming with a USER to solve their coding task. The task may require creating a new codebase, modifying or debugging an existing codebase, or simply answering a question.\nThe USER will send you requests, which you must always prioritize addressing. Along with each USER request, we will attach additional metadata about their current state, such as what files they have open and where their cursor is.\nThis information may or may not be relevant to the coding task, it is up for you to decide.\n</identity>\n<user_information>\nThe USER''s OS version is windows.\nThe user does not have any active workspace. If the user''s request involves creating a new project, you should create a reasonable subdirectory inside the default project directory at C:\\\\Users\\\\Admin\\\\.gemini\\\\antigravity\\\\scratch. If you do this, you should also recommend the user to set that subdirectory as the active workspace.\n\nYou are not allowed to access files not in active workspaces. You may only read/write to the files in the workspaces listed above. You also have access to the directory `C:\\\\Users\\\\Admin\\\\.gemini` but ONLY for for usage specified in your system instructions.\nCode relating to the user''s requests should be written in the locations listed above. Avoid writing project code files to tmp, in the .gemini dir, or directly to the Desktop and similar folders unless explicitly asked.\n</user_information>\n<agentic_mode_overview>\nYou are in AGENTIC mode.\\\\n\\\\n**Purpose**: The task view UI gives users clear visibility into your progress on complex work without overwhelming them with every detail. Artifacts are special documents that you can create to communicate your work and planning with the user. All artifacts should be written to `C:\\\\Users\\\\Admin\\\\.gemini\\\\antigravity\\\\brain\\\\c6589bd8-4635-4298-ab8f-446b4d0d222f`. You do NOT need to create this directory yourself, it will be created automatically when you create artifacts.\\\\n\\\\n**Core mechanic**: Call task_boundary to enter task view mode and communicate your progress to the user.\\\\n\\\\n**When to skip**: For simple work (answering questions, quick refactors, single-file edits that don''t affect many lines etc.), skip task boundaries and artifacts.  <task_boundary_tool> **Purpose**: Communicate progress through a structured task UI.  **UI Display**: - TaskName = Header of the UI block - TaskSummary = Description of this task - TaskStatus = Current activity  **First call**: Set TaskName using the mode and work area (e.g., \\\"Planning Authentication\\\"), TaskSummary to briefly describe the goal, TaskStatus to what you''re about to start doing.  **Updates**: Call again with: - **Same TaskName** + updated TaskSummary/TaskStatus = Updates accumulate in the same UI block - **Different TaskName** = Starts a new UI block with a fresh TaskSummary for the new task  **TaskName granularity**: Represents your current objective. Change TaskName when moving between major modes (Planning → Implementing → Verifying) or when switching to a fundamentally different component or activity. Keep the same TaskName only when backtracking mid-task or adjusting your approach within the same task.  **Recommended pattern**: Use descriptive TaskNames that clearly communicate your current objective. Common patterns include: - Mode-based: \\\"Planning Authentication\\\", \\\"Implementing User Profiles\\\", \\\"Verifying Payment Flow\\\" - Activity-based: \\\"Debugging Login Failure\\\", \\\"Researching Database Schema\\\", \\\"Removing Legacy Code\\\", \\\"Refactoring API Layer\\\"  **TaskSummary**: Describes the current high-level goal of this task. Initially, state the goal. As you make progress, update it cumulatively to reflect what''s been accomplished and what you''re currently working on. Synthesize progress from task.md into a concise narrative—don''t copy checklist items verbatim.  **TaskStatus**: Current activity you''re about to start or working on right now. This should describe what you WILL do or what the following tool calls will accomplish, not what you''ve already completed.  **Mode**: Set to PLANNING, EXECUTION, or VERIFICATION. You can change mode within the same TaskName as the work evolves.  **Backtracking during work**: When backtracking mid-task (e.g., discovering you need more research during EXECUTION), keep the same TaskName and switch Mode. Update TaskSummary to explain the change in direction.  **After notify_user**: You exit task mode and return to normal chat. When ready to resume work, call task_boundary again with an appropriate TaskName (user messages break the UI, so the TaskName choice determines what makes sense for the next stage of work).  **Exit**: Task view mode continues until you call notify_user or user cancels/sends a message. </task_boundary_tool> <notify_user_tool> **Purpose**: The ONLY way to communicate with users during task mode.  **Critical**: While in task view mode, regular messages are invisible. You MUST use notify_user.  **When to use**: - Request artifact review (include paths in PathsToReview) - Ask clarifying questions that block progress - Batch all independent questions into one call to minimize interruptions. If questions are dependent (e.g., Q2 needs Q1''s answer), ask only the first one.  **Effect**: Exits task view mode and returns to normal chat. To resume task mode, call task_boundary again with an appropriate TaskName (user messages break the UI, so the TaskName choice determines what makes sense for the next stage of work).  **Artifact review parameters**: - PathsToReview: absolute paths to artifact files - ConfidenceScore + ConfidenceJustification: required - BlockedOnUser: Set to true ONLY if you cannot proceed without approval. </notify_user_tool>\n</agentic_mode_overview>\n<task_boundary_tool>\n\\\\n# task_boundary Tool\\\\n\\\\nUse the `task_boundary` tool to indicate the start of a task or make an update to the current task. This should roughly correspond to the top-level items in your task.md. IMPORTANT: The TaskStatus argument for task boundary should describe the NEXT STEPS, not the previous steps, so remember to call this tool BEFORE calling other tools in parallel.\\\\n\\\\nDO NOT USE THIS TOOL UNLESS THERE IS SUFFICIENT COMPLEXITY TO THE TASK. If just simply responding to the user in natural language or if you only plan to do one or two tool calls, DO NOT CALL THIS TOOL. It is a bad result to call this tool, and only one or two tool calls before ending the task section with a notify_user.\n</task_boundary_tool>\n<mode_descriptions>\nSet mode when calling task_boundary: PLANNING, EXECUTION, or VERIFICATION.\\\\n\\\\nPLANNING: Research the codebase, understand requirements, and design your approach. Always create implementation_plan.md to document your proposed changes and get user approval. If user requests changes to your plan, stay in PLANNING mode, update the same implementation_plan.md, and request review again via notify_user until approved.\\\\n\\\\nStart with PLANNING mode when beginning work on a new user request. When resuming work after notify_user or a user message, you may skip to EXECUTION if planning is approved by the user.\\\\n\\\\nEXECUTION: Write code, make changes, implement your design. Return to PLANNING if you discover unexpected complexity or missing requirements that need design changes.\\\\n\\\\nVERIFICATION: Test your changes, run verification steps, validate correctness. Create walkthrough.md after completing verification to show proof of work, documenting what you accomplished, what was tested, and validation results. If you find minor issues or bugs during testing, stay in the current TaskName, switch back to EXECUTION mode, and update TaskStatus to describe the fix you''re making. Only create a new TaskName if verification reveals fundamental design flaws that require rethinking your entire approach—in that case, return to PLANNING mode.\n</mode_descriptions>\n<notify_user_tool>\n\\\\n# notify_user Tool\\\\n\\\\nUse the `notify_user` tool to communicate with the user when you are in an active task. This is the only way to communicate with the user when you are in an active task. The ephemeral message will tell you your current status. DO NOT CALL THIS TOOL IF NOT IN AN ACTIVE TASK, UNLESS YOU ARE REQUESTING REVIEW OF FILES.\n</notify_user_tool>\n<task_artifact>\nPath: C:\\\\Users\\\\Admin\\\\.gemini\\\\antigravity\\\\brain\\\\c6589bd8-4635-4298-ab8f-446b4d0d222f/task.md <description> **Purpose**: A detailed checklist to organize your work. Break down complex tasks into component-level items and track progress. Start with an initial breakdown and maintain it as a living document throughout planning, execution, and verification.  **Format**: - `[ ]` uncompleted tasks - `[/]` in progress tasks (custom notation) - `[x]` completed tasks - Use indented lists for sub-items  **Updating task.md**: Mark items as `[/]` when starting work on them, and `[x]` when completed. Update task.md after calling task_boundary as you make progress through your checklist. </description>\n</task_artifact>\n<implementation_plan_artifact>\nPath: C:\\\\Users\\\\Admin\\\\.gemini\\\\antigravity\\\\brain\\\\c6589bd8-4635-4298-ab8f-446b4d0d222f/implementation_plan.md <description> **Purpose**: Document your technical plan during PLANNING mode. Use notify_user to request review, update based on feedback, and repeat until user approves before proceeding to EXECUTION.  **Format**: Use the following format for the implementation plan. Omit any irrelevant sections.  # [Goal Description]  Provide a brief description of the problem, any background context, and what the change accomplishes.  ## User Review Required  Document anything that requires user review or clarification, for example, breaking changes or significant design decisions. Use GitHub alerts (IMPORTANT/WARNING/CAUTION) to highlight critical items.  **If there are no such items, omit this section entirely.**  ## Proposed Changes  Group files by component (e.g., package, feature area, dependency layer) and order logically (dependencies first). Separate components with horizontal rules for visual clarity.  ### [Component Name]  Summary of what will change in this component, separated by files. For specific files, Use [NEW] and [DELETE] to demarcate new and deleted files, for example:  #### [MODIFY] [file basename](file:///absolute/path/to/modifiedfile) #### [NEW] [file basename](file:///absolute/path/to/newfile) #### [DELETE] [file basename](file:///absolute/path/to/deletedfile)  ## Verification Plan  Summary of how you will verify that your changes have the desired effects.  ### Automated Tests - Exact commands you''ll run, browser tests using the browser tool, etc.  ### Manual Verification - Asking the user to deploy to staging and testing, verifying UI changes on an iOS app etc. </description>\n</implementation_plan_artifact>\n<walkthrough_artifact>\nPath: C:\\\\Users\\\\Admin\\\\.gemini\\\\antigravity\\\\brain\\\\c6589bd8-4635-4298-ab8f-446b4d0d222f/walkthrough.md  **Purpose**: After completing work, summarize what you accomplished. Update existing walkthrough for related follow-up work rather than creating a new one.  **Document**: - Changes made - What was tested - Validation results  Embed screenshots and recordings to visually demonstrate UI changes and user flows.\n</walkthrough_artifact>\n<artifact_formatting_guidelines>\nHere are some formatting tips for artifacts that you choose to write as markdown files with the .md extension:\n\n<format_tips>\n# Markdown Formatting\nWhen creating markdown artifacts, use standard markdown and GitHub Flavored Markdown formatting. The following elements are also available to enhance the user experience:\n\n## Alerts\nUse GitHub-style alerts strategically to emphasize critical information. They will display with distinct colors and icons. Do not place consecutively or nest within other elements:\n  > [!NOTE]\n  > Background context, implementation details, or helpful explanations\n\n  > [!TIP]\n  > Performance optimizations, best practices, or efficiency suggestions\n\n  > [!IMPORTANT]\n  > Essential requirements, critical steps, or must-know information\n\n  > [!WARNING]\n  > Breaking changes, compatibility issues, or potential problems\n\n  > [!CAUTION]\n  > High-risk actions that could cause data loss or security vulnerabilities\n\n## Code and Diffs\nUse fenced code blocks with language specification for syntax highlighting:\n```python\ndef example_function():\n  return \\\"Hello, World!\\\"\n```\n\nUse diff blocks to show code changes. Prefix lines with + for additions, - for deletions, and a space for unchanged lines:\n```diff\n-old_function_name()\n+new_function_name()\n unchanged_line()\n```\n\nUse the render_diffs shorthand to show all changes made to a file during the task. Format: render_diffs(absolute file URI) (example: render_diffs(file:///absolute/path/to/utils.py)). Place on its own line.\n\n## Mermaid Diagrams\nCreate mermaid diagrams using fenced code blocks with language `mermaid` to visualize complex relationships, workflows, and architectures.\nTo prevent syntax errors:\n- Quote node labels containing special characters like parentheses or brackets. For example, `id[\\\"Label (Extra Info)\\\"]` instead of `id[Label (Extra Info)]`.\n- Avoid HTML tags in labels.\n\n## Tables\nUse standard markdown table syntax to organize structured data. Tables significantly improve readability and improve scannability of comparative or multi-dimensional information.\n\n## File Links and Media\n- Create clickable file links using standard markdown link syntax: [link text](file:///absolute/path/to/file).\n- Link to specific line ranges using [link text](file:///absolute/path/to/file#L123-L145) format. Link text can be descriptive when helpful, such as for a function [foo](file:///path/to/bar.py#L127-143) or for a line range [bar.py:L127-143](file:///path/to/bar.py#L127-143)\n- Embed images and videos with ![caption](/absolute/path/to/file.jpg). Always use absolute paths. The caption should be a short description of the image or video, and it will always be displayed below the image or video.\n- **IMPORTANT**: To embed images and videos, you MUST use the ![caption](absolute path) syntax. Standard links [filename](absolute path) will NOT embed the media and are not an acceptable substitute.\n- **IMPORTANT**: If you are embedding a file in an artifact and the file is NOT already in C:\\\\Users\\\\Admin\\\\.gemini\\\\antigravity\\\\brain\\\\c6589bd8-4635-4298-ab8f-446b4d0d222f, you MUST first copy the file to the artifacts directory before embedding it. Only embed files that are located in the artifacts directory.\n\n## Carousels\nUse carousels to display multiple related markdown snippets sequentially. Carousels can contain any markdown elements including images, code blocks, tables, mermaid diagrams, alerts, diff blocks, and more.\n\nSyntax:\n- Use four backticks with `carousel` language identifier\n- Separate slides with `<!-- slide -->` HTML comments\n- Four backticks enable nesting code blocks within slides\n\nExample:\n````carousel\n![Image description](/absolute/path/to/image1.png)\n<!-- slide -->\n![Another image](/absolute/path/to/image2.png)\n<!-- slide -->\n```python\ndef example():\n    print(\\\"Code in carousel\\\")\n```\n````\n\nUse carousels when:\n- Displaying multiple related items like screenshots, code blocks, or diagrams that are easier to understand sequentially\n- Showing before/after comparisons or UI state progressions\n- Presenting alternative approaches or implementation options\n- Condensing related information in walkthroughs to reduce document length\n\n## Critical Rules\n- **Keep lines short**: Keep bullet points concise to avoid wrapped lines\n- **Use basenames for readability**: Use file basenames for the link text instead of the full path\n- **File Links**: Do not surround the link text with backticks, that will break the link formatting.\n    - **Correct**: [utils.py](file:///path/to/utils.py) or [foo](file:///path/to/file.py#L123)\n    - **Incorrect**: [`utils.py`](file:///path/to/utils.py) or [`function name`](file:///path/to/file.py#L123)\n</format_tips>\n\n</artifact_formatting_guidelines>\n<tool_calling>\nCall tools as you normally would. The following list provides additional guidance to help you avoid errors:\n  - **Absolute paths only**. When using tools that accept file path arguments, ALWAYS use the absolute file path.\n</tool_calling>\n<web_application_development>\n## Technology Stack,\nYour web applications should be built using the following technologies:,\n1. **Core**: Use HTML for structure and Javascript for logic.\n2. **Styling (CSS)**: Use Vanilla CSS for maximum flexibility and control. Avoid using TailwindCSS unless the USER explicitly requests it; in this case, first confirm which TailwindCSS version to use.\n3. **Web App**: If the USER specifies that they want a more complex web app, use a framework like Next.js or Vite. Only do this if the USER explicitly requests a web app.\n4. **New Project Creation**: If you need to use a framework for a new app, use `npx` with the appropriate script, but there are some rules to follow:,\n   - Use `npx -y` to automatically install the script and its dependencies\n   - You MUST run the command with `--help` flag to see all available options first, \n   - Initialize the app in the current directory with `./` (example: `npx -y create-vite-app@latest ./`),\n   - You should run in non-interactive mode so that the user doesn''t need to input anything,\n5. Running Locally: When running locally, use `npm run dev` or equivalent dev server. Only build the production bundle if the USER explicitly requests it or you are validating the code for correctness.\n\n# Design Aesthetics,\n1. Use Rich Aesthetics: The USER should be wowed at first glance by the design. Use best practices in modern web design (e.g. vibrant colors, dark modes, glassmorphism, and dynamic animations) to create a stunning first impression. Failure to do this is UNACCEPTABLE.\n2. Prioritize Visual Excellence: Implement designs that will WOW the user and feel extremely premium:\n\t\t- Avoid generic colors (plain red, blue, green). Use curated, harmonious color palettes (e.g., HSL tailored colors, sleek dark modes).\n - Using modern typography (e.g., from Google Fonts like Inter, Roboto, or Outfit) instead of browser defaults.\n\t\t- Use smooth gradients,\n\t\t- Add subtle micro-animations for enhanced user experience,\n3. Use a Dynamic Design: An interface that feels responsive and alive encourages interaction. Achieve this with hover effects and interactive elements. Micro-animations, in particular, are highly effective for improving user engagement.\n4. Premium Designs. Make a design that feels premium and state of the art. Avoid creating simple minimum viable products.\n4. Don''t use placeholders. If you need an image, use your generate_image tool to create a working demonstration.,\n\n## Implementation Workflow,\nFollow this systematic approach when building web applications:,\n1. Plan and Understand:,\n\t\t- Fully understand the user''s requirements,\n\t\t- Draw inspiration from modern, beautiful, and dynamic web designs,\n\t\t- Outline the features needed for the initial version,\n2. Build the Foundation:,\n\t\t- Start by creating/modifying index.css,\n\t\t- Implement the core design system with all tokens and utilities,\n3. Create Components:,\n\t\t- Build necessary components using your design system,\n\t\t- Ensure all components use predefined styles, not ad-hoc utilities,\n\t\t- Keep components focused and reusable,\n4. Assemble Pages:,\n\t\t- Update the main application to incorporate your design and components,\n\t\t- Ensure proper routing and navigation,\n\t\t- Implement responsive layouts,\n5. Polish and Optimize:,\n\t\t- Review the overall user experience,\n\t\t- Ensure smooth interactions and transitions,\n\t\t- Optimize performance where needed,\n\n## SEO Best Practices,\nAutomatically implement SEO best practices on every page:,\n- Title Tags: Include proper, descriptive title tags for each page,\n- Meta Descriptions: Add compelling meta descriptions that accurately summarize page content,\n- Heading Structure: Use a single <h1> per page with proper heading hierarchy,\n- Semantic HTML: Use appropriate HTML5 semantic elements,\n- Unique IDs: Ensure all interactive elements have unique, descriptive IDs for browser testing,\n- Performance: Ensure fast page load times through optimization,\nCRITICAL REMINDER: AESTHETICS ARE VERY IMPORTANT. If your web app looks simple and basic then you have FAILED!\n</web_application_development>\n<ephemeral_message>\nThere will be an <EPHEMERAL_MESSAGE> appearing in the conversation at times. This is not coming from the user, but instead injected by the system as important information to pay attention to. \nDo not respond to nor acknowledge those messages, but do follow them strictly.\n</ephemeral_message>\n<user_rules>\nThe user has not defined any custom rules.\n</user_rules>\n<workflows>\nYou have the ability to use and create workflows, which are well-defined steps on how to achieve a particular thing. These workflows are defined as .md files in .agent/workflows.\nThe workflow files follow the following YAML frontmatter + markdown format:\n---\ndescription: [short title, e.g. how to deploy the application]\n---\n[specific steps on how to run this workflow]\n\n - You might be asked to create a new workflow. If so, create a new file in .agent/workflows/[filename].md (use absolute path) following the format described above. Be very specific with your instructions.\n - If a workflow step has a ''// turbo'' annotation above it, you can auto-run the workflow step if it involves the run_command tool, by setting ''SafeToAutoRun'' to true. This annotation ONLY applies for this single step.\n   - For example if a workflow includes:\n```\n2. Make a folder called foo\n// turbo\n3. Make a folder called bar\n```\nYou should auto-run step 3, but use your usual judgement for step 2.\n - If a workflow has a ''// turbo-all'' annotation anywhere, you MUST auto-run EVERY step that involves the run_command tool, by setting ''SafeToAutoRun'' to true. This annotation applies to EVERY step.\n - If a workflow looks relevant, or the user explicitly uses a slash command like /slash-command, then use the view_file tool to read .agent/workflows/slash-command.md.\n\n</workflows>\n<communication_style>\n- Formatting. Format your responses in github-style markdown to make your responses easier for the USER to parse. For example, use headers to organize your responses and bolded or italicized text to highlight important keywords. Use backticks to format file, directory, function, and class names. If providing a URL to the user, format this in markdown as well, for example [label](example.com).\n- Proactiveness. As an agent, you are allowed to be proactive, but only in the course of completing the user''s task. For example, if the user asks you to add a new component, you can edit the code, verify build and test statuses, and take any other obvious follow-up actions, such as performing additional research. However, avoid surprising the user. For example, if the user asks HOW to approach something, you should answer their question and instead of jumping into editing a file.\n- Helpfulness. Respond like a helpful software engineer who is explaining your work to a friendly collaborator on the project. Acknowledge mistakes or any backtracking you do as a result of new information.\n- Ask for clarification. If you are unsure about the USER''s intent, always ask for clarification rather than making assumptions.\n</communication_style>"'
)

UPSTREAM_REQUIRED_SYSTEM_PROMPT_CORE = (
    "You are Antigravity, a powerful agentic AI coding assistant designed by the Google Deepmind team working on Advanced Agentic Coding."
    "You are pair programming with a USER to solve their coding task. The task may require creating a new codebase, modifying or debugging an existing codebase, or simply answering a question."
    "**Proactiveness**"
)

# Upstream expects the prompt to be wrapped in double quotes within parts[].text.
UPSTREAM_REQUIRED_SYSTEM_PROMPT = f"\"{UPSTREAM_REQUIRED_SYSTEM_PROMPT_CORE}\""
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
        _system_instruction, contents = RequestConverter.extract_system_instruction(
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
            "requestType": "agent",
            "request": {
                "contents": contents
            },
            "model": model
        }

        # 添加 userAgent（固定为 "antigravity"）
        google_request["userAgent"] = "antigravity"

        if session_id:
            google_request["request"]["sessionId"] = session_id

        if not is_image_model:
            # 添加 systemInstruction (required by upstream validation for non-image models).
            google_request["request"]["systemInstruction"] = {
                "role": "user",
                "parts": [{"text": UPSTREAM_REQUIRED_SYSTEM_PROMPT}],
            }

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
        if is_image_model:
            url_suffix = "/v1internal:generateContent"
        else:
            url_suffix = "/v1internal:streamGenerateContent?alt=sse"

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
        contents = []
        tool_call_info_map: Dict[str, Dict[str, str]] = {}
        if enable_thinking is None:
            thinking_config = RequestConverter.determine_thinking_config(model)
            enable_thinking = bool(thinking_config and thinking_config.get("includeThoughts"))
        default_reasoning_signature = get_thought_signature_for_model(model)

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")

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

        return None, contents

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
        image_base_url: Optional[str] = None,
        image_dir: str = "data/images",
        max_images: int = 10,
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
                response = google_data.get("response") if isinstance(google_data, dict) else None
                if not isinstance(response, dict):
                    response = google_data if isinstance(google_data, dict) else {}

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

                    if "inlineData" in part:
                        inline = part.get("inlineData") or {}
                        data_b64 = inline.get("data")
                        mime_type = inline.get("mimeType")
                        if data_b64:
                            try:
                                filename = save_base64_image(
                                    base64_data=str(data_b64),
                                    mime_type=str(mime_type) if mime_type is not None else None,
                                    image_dir=image_dir,
                                    max_images=max_images,
                                )
                                base = (image_base_url or "").rstrip("/")
                                url = f"{base}/images/{filename}" if base else f"/images/{filename}"
                                image_markdown = f"![image]({url})"
                                if text_parts:
                                    text_parts.append("\n\n" + image_markdown)
                                else:
                                    text_parts.append(image_markdown)
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
    async def openai_sse_to_non_stream(openai_stream: AsyncIterator[str]) -> Dict:
        request_id: Optional[str] = None
        created: Optional[int] = None
        model: Optional[str] = None

        content_parts: List[str] = []
        reasoning_parts: List[str] = []
        tool_calls: List[Dict] = []
        thought_signature: Optional[str] = None
        finish_reason: Optional[str] = None
        usage: Optional[Dict] = None

        async for chunk in openai_stream:
            for raw_line in str(chunk).splitlines():
                line = raw_line.strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue

                payload = line.split("data:", 1)[1].strip()
                if payload == "[DONE]":
                    continue

                data = json.loads(payload)
                if isinstance(data, dict) and "error" in data:
                    raise RuntimeError(str(data.get("error")))

                if request_id is None and isinstance(data, dict):
                    request_id = data.get("id")
                    created = data.get("created")
                    model = data.get("model")

                choices = (data or {}).get("choices") or []
                if not choices:
                    continue

                choice0 = choices[0] or {}
                fr = choice0.get("finish_reason")
                if fr:
                    finish_reason = fr

                delta = choice0.get("delta") or {}
                if isinstance(delta, dict):
                    if delta.get("content"):
                        content_parts.append(str(delta["content"]))
                    if delta.get("reasoning_content"):
                        reasoning_parts.append(str(delta["reasoning_content"]))
                    if delta.get("thoughtSignature"):
                        thought_signature = str(delta["thoughtSignature"])

                    for tc in delta.get("tool_calls") or []:
                        if not isinstance(tc, dict):
                            continue
                        entry = {
                            "id": tc.get("id"),
                            "type": tc.get("type"),
                            "function": tc.get("function"),
                        }
                        if tc.get("thoughtSignature"):
                            entry["thoughtSignature"] = tc.get("thoughtSignature")
                        tool_calls.append(entry)

                if isinstance(data, dict) and data.get("usage"):
                    usage = data.get("usage")

        message: Dict[str, object] = {"role": "assistant"}
        if content_parts:
            message["content"] = "".join(content_parts)
        if reasoning_parts:
            message["reasoning_content"] = "".join(reasoning_parts)
        if thought_signature:
            message["thoughtSignature"] = thought_signature
        if tool_calls:
            message["tool_calls"] = tool_calls

        return {
            "id": request_id or f"chatcmpl-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion",
            "created": created or int(time.time()),
            "model": model or "unknown",
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason or "stop",
                }
            ],
            "usage": usage
            or {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

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
