"""Conversation policy helpers for Home Assistant MCP tools.

The add-on used to add an extra local guard around Home Assistant action tools.
That was useful while device microphone transcription was unreliable, but it
made normal multi-turn confirmations frustrating once audio stabilized. Keep the
module as a compatibility layer for existing imports, while allowing MCP tools
to execute directly.
"""

from typing import Any, Awaitable, Callable

_last_user_text = ""


def set_last_user_text(text: str) -> None:
    global _last_user_text
    _last_user_text = (text or "").strip()


def get_last_user_text() -> str:
    return _last_user_text


def augment_tool_description(tool_name: str, description: str) -> str:
    return description


def augment_system_instructions(instructions: str) -> str:
    conversation_contract = (
        "\n\nREALTIME CONVERSATION CONTRACT: Keep the conversation open and "
        "natural. For every substantive non-terminal answer, end with one short "
        "follow-up question in the user's language, for example in Polish: "
        "'Czy moge cos jeszcze sprawdzic?'. If the latest user utterance clearly "
        "ends the conversation, for example 'ok dziekuje', 'dzieki', 'koniec "
        "rozmowy', 'stop', 'wystarczy', 'do uslyszenia', 'goodbye', or 'that's "
        "all', answer briefly and do not ask another question. Do not say filler "
        "like 'sekunda' or 'chwila' before tool calls. If a tool, web search, or "
        "Home Assistant MCP call is needed, call it silently and answer only when "
        "you have the result. If your answer ends with a real follow-up question "
        "and the user did not end the conversation, call the request_follow_up "
        "tool once so the device opens the microphone after your spoken answer. "
        "Never call request_follow_up after terminal phrases."
    )
    return (instructions or "").rstrip() + conversation_contract


def should_guard_tool(tool_name: str) -> bool:
    return False


def guarded_tool_handler(
    tool_name: str, handler: Callable[[Any], Awaitable[None]]
) -> Callable[[Any], Awaitable[None]]:
    return handler
