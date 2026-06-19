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
        "\n\nREALTIME CONVERSATION CONTRACT: You are a general conversational "
        "assistant with optional Home Assistant tools. Home Assistant control is "
        "only one capability, not your default topic. Answer the user's actual "
        "question directly; for casual or meta questions such as 'co u ciebie "
        "slychac?', answer conversationally and do not mention devices, rooms, "
        "speakers, lights, or the smart home unless the user explicitly asks "
        "about them. Use Home Assistant tools only when the user clearly asks to "
        "inspect or change the home. Ask one short follow-up question only when "
        "it is genuinely useful, you need clarification, or the conversation "
        "naturally invites a reply. If the latest user utterance clearly ends "
        "the conversation, for example 'ok dziekuje', 'dzieki', 'koniec rozmowy', "
        "'stop', 'wystarczy', 'do uslyszenia', 'goodbye', or 'that's all', answer "
        "briefly and do not ask another question. Do not say filler like "
        "'sekunda' or 'chwila' before tool calls. If a tool, web search, or Home "
        "Assistant MCP call is needed, call it silently and answer only when you "
        "have the result. The device follow-up microphone is managed by the "
        "backend after your final spoken text; do not mention or try to control "
        "it."
    )
    return (instructions or "").rstrip() + conversation_contract


def should_guard_tool(tool_name: str) -> bool:
    return False


def guarded_tool_handler(
    tool_name: str, handler: Callable[[Any], Awaitable[None]]
) -> Callable[[Any], Awaitable[None]]:
    return handler
