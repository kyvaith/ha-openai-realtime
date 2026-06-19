"""Small device-control tools for deterministic realtime conversations."""

import logging
import re
import unicodedata
from typing import Any, Awaitable, Callable, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from pipecat.services.llm_service import FunctionCallParams

logger = logging.getLogger(__name__)

_TERMINAL_PHRASES = (
    "ok dziekuje",
    "okej dziekuje",
    "dziekuje",
    "dzieki",
    "wystarczy",
    "koniec",
    "koniec rozmowy",
    "stop",
    "do uslyszenia",
    "do widzenia",
    "na razie",
    "goodbye",
    "bye",
    "that's all",
    "that is all",
    "thanks",
    "thank you",
)


def _normalize_utterance(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9 ]+", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def is_terminal_utterance(text: str) -> bool:
    """Return true when the user clearly ends the conversation."""
    normalized = _normalize_utterance(text)
    if not normalized:
        return False
    return any(
        normalized == phrase or normalized.startswith(f"{phrase} ") or normalized.endswith(f" {phrase}")
        for phrase in _TERMINAL_PHRASES
    )


def assistant_requests_follow_up(text: str) -> bool:
    """Return true when the assistant's final spoken text invites a reply."""
    cleaned = (text or "").strip().rstrip("\"'”’)]}")
    if not cleaned:
        return False
    if is_terminal_utterance(cleaned):
        return False
    return cleaned.endswith("?")


def get_request_follow_up_tool_definition() -> Dict[str, Any]:
    """Return the OpenAI Realtime tool definition for a device follow-up window."""
    return {
        "type": "function",
        "name": "request_follow_up",
        "description": (
            "Open the device microphone after the current spoken answer finishes. "
            "Use this exactly when your answer ends with a real follow-up question "
            "and you want the user to continue without saying the wake word again. "
            "Do not use it when the user ended the conversation."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    }


def create_request_follow_up_tool_handler(
    request_follow_up_callback: Callable[[], None],
) -> Callable[["FunctionCallParams"], Awaitable[None]]:
    """Create a Pipecat function handler that marks the current reply for follow-up."""

    async def request_follow_up_tool_handler(params: "FunctionCallParams") -> None:
        logger.info("request_follow_up tool called")
        request_follow_up_callback()
        await params.result_callback("Follow-up microphone window will open after this reply.")

    return request_follow_up_tool_handler
