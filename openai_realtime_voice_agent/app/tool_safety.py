"""Safety guards for Home Assistant MCP tool calls."""

import logging
import os
import re
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

_last_user_text = ""


TARGETED_ACTION_TOOLS = {
    "HassTurnOn",
    "HassTurnOff",
    "HassLightSet",
    "HassMediaPause",
    "HassMediaUnpause",
    "HassMediaNext",
    "HassMediaPrevious",
    "HassSetVolume",
    "HassSetVolumeRelative",
    "HassMediaPlayerMute",
    "HassMediaPlayerUnmute",
    "HassClimateSetTemperature",
    "HassFanSetSpeed",
}

ACTION_INTENT_PATTERNS = [
    # Polish
    r"\b(wlac|wlacz|włącz|włączaj|zalacz|załącz|uruchom|odpal|aktywu)\w*\b",
    r"\b(wylac|wylacz|wyłącz|zgas|zgaś|zamknij|zablokuj|dezaktywu)\w*\b",
    r"\b(ustaw|zmien|zmień|przestaw|podnies|podnieś|obniz|obniż)\w*\b",
    r"\b(podglosnij|podgłośnij|przycisz|scisz|ścisz|glosniej|głośniej|ciszej)\b",
    r"\b(pusc|puść|odtworz|odtwórz|graj|zagraj|wznow|wznów|pauz|zatrzymaj)\w*\b",
    r"\b(nastepn|następn|poprzedni|poprzednia|poprzednie)\w*\b",
    r"\b(przelacz|przełącz|przewin|przewiń)\w*\b",
    # English
    r"\b(turn|switch|set|change|open|close|lock|unlock|activate|deactivate)\b",
    r"\b(play|pause|resume|stop|skip|next|previous|mute|unmute)\b",
    r"\b(volume|brighter|dimmer|louder|quieter)\b",
]

NON_ACTION_CONVERSATION_PATTERNS = [
    r"\b(slyszysz|słyszysz|slychac|słychać|czy mnie|mnie slysz|mnie słysz)\b",
    r"\b(jak masz na imie|jak masz na imię|jak sie nazywasz|jak się nazywasz)\b",
    r"\b(co u ciebie|co slychac|co słychać|kim jestes|kim jesteś)\b",
    r"\b(can you hear me|do you hear me|what is your name|how are you)\b",
]

TARGET_KEYS = {
    "area",
    "areas",
    "area_id",
    "area_ids",
    "device",
    "devices",
    "device_id",
    "device_ids",
    "entity",
    "entities",
    "entity_id",
    "entity_ids",
    "name",
    "names",
    "target",
    "targets",
}


def set_last_user_text(text: str) -> None:
    global _last_user_text
    _last_user_text = (text or "").strip()


def get_last_user_text() -> str:
    return _last_user_text


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return any(_has_value(item) for item in value)
    if isinstance(value, dict):
        return any(_has_value(item) for item in value.values())
    return True


def has_explicit_target(arguments: dict[str, Any]) -> bool:
    """Return true when a tool call targets a specific entity, device, area, or name."""
    if not isinstance(arguments, dict):
        return False

    for key, value in arguments.items():
        normalized = key.lower()
        if normalized in TARGET_KEYS and _has_value(value):
            return True
        if isinstance(value, dict) and has_explicit_target(value):
            return True
    return False


def has_home_action_intent(text: str) -> bool:
    """Return true when the latest user utterance clearly asks for HA control."""
    normalized = (text or "").strip().lower()
    if not normalized:
        return False

    # Common conversational probes are never smart-home control requests, even
    # when words like "hear" or "speaker" tempt the model toward media tools.
    if any(re.search(pattern, normalized) for pattern in NON_ACTION_CONVERSATION_PATTERNS):
        return False

    return any(re.search(pattern, normalized) for pattern in ACTION_INTENT_PATTERNS)


def should_guard_tool(tool_name: str) -> bool:
    if os.environ.get("HA_MCP_ALLOW_DOMAIN_WIDE_ACTIONS", "false").strip().lower() == "true":
        return False
    return tool_name in TARGETED_ACTION_TOOLS


def augment_tool_description(tool_name: str, description: str) -> str:
    if not should_guard_tool(tool_name):
        return description
    safety = (
        " Safety rule: use this Home Assistant action only when the user's "
        "latest utterance clearly asks to control the home. Do not call it for "
        "conversational checks such as 'can you hear me?', 'what is your name?', "
        "or 'how are you?'. Never call this tool with only a domain such as "
        "'light' or 'switch'. Include a specific entity, device, area, or name. "
        "If the target or intent is ambiguous, ask a clarifying question instead."
    )
    return (description or "") + safety


def augment_system_instructions(instructions: str) -> str:
    safety = (
        "\n\nSMART HOME TOOL SAFETY: Home Assistant tools are only for explicit "
        "smart-home control or state questions. Do not call Home Assistant "
        "action tools for conversational or diagnostic questions such as "
        "'can you hear me?', 'what is your name?', 'how are you?', or similar. "
        "For those, answer directly. If a user asks to control the home but the "
        "target is ambiguous, ask a short clarifying question before calling a "
        "tool."
    )
    return (instructions or "").rstrip() + safety


def guarded_tool_handler(
    tool_name: str, handler: Callable[[Any], Awaitable[None]]
) -> Callable[[Any], Awaitable[None]]:
    async def wrapped(params: Any) -> None:
        arguments = getattr(params, "arguments", None) or {}
        if should_guard_tool(tool_name) and not has_home_action_intent(get_last_user_text()):
            logger.warning(
                "Blocked Home Assistant action without explicit user intent: %s arguments=%s last_user=%r",
                tool_name,
                arguments,
                get_last_user_text(),
            )
            await params.result_callback(
                "Tool call blocked: the latest user message did not include an "
                "explicit smart-home control request. Answer conversationally "
                "or ask a clarifying question."
            )
            return
        if should_guard_tool(tool_name) and not has_explicit_target(arguments):
            logger.warning(
                "Blocked unsafe broad Home Assistant tool call: %s arguments=%s last_user=%r",
                tool_name,
                arguments,
                get_last_user_text(),
            )
            await params.result_callback(
                "Tool call blocked: no specific target was provided. Ask the "
                "user which device, area, or entity they want to control."
            )
            return
        await handler(params)

    return wrapped
