"""Log the conversation transcript (assistant + user) into the add-on log.

WHY: with gpt-realtime the model hears the user's audio natively and bursts the
whole spoken reply as audio — the only window into *what it actually said* used to
be the OpenAI tool-call arguments. This processor surfaces the assistant's spoken
text (and, when input transcription is enabled, the user's transcript) as plain
INFO lines so the add-on log alone explains a turn.

How the text reaches us (verified against pipecat 0.0.97's *real*
`pipecat.services.openai.realtime.llm.OpenAIRealtimeLLMService` — NOT the older
`openai_realtime_beta` module, which pushes different frames):

  - Assistant reply, AUDIO modality (what we use): the service handles
    `response.output_audio_transcript.delta` and pushes a **`TTSTextFrame`** per
    chunk (NOT `LLMTextFrame` — that's only for the text modality). The whole
    response is bracketed by `LLMFullResponseStartFrame` /
    `LLMFullResponseEndFrame`. We accumulate the chunks and log one line on the
    End frame. (We also match `LLMTextFrame` so a text-modality run still logs.)
    These flow DOWNSTREAM out of the service, so the "assistant" tap sits AFTER
    it in the pipeline.

  - User transcript: `conversation.item.input_audio_transcription.completed`
    pushes a `TranscriptionFrame` — but UPSTREAM (toward the input, so the user
    context aggregator can consume it) and ONLY when input transcription is
    configured (main.py: transcription is None unless TRANSCRIPTION_LANGUAGE is
    set). A tap placed AFTER the service never sees it; the "user" tap therefore
    sits BEFORE the service (between the user aggregator and the LLM).

Because the two transcripts travel in opposite directions past the service, no
single position sees both — so the pipeline wires TWO instances of this class,
one per role (see websocket_handler.build_pipeline). It is pure instrumentation:
it never transforms or drops a frame. (Listed for removal under CLAUDE.md
roadmap #5 once the system is stable.)
"""
import logging
from typing import Awaitable, Callable, Optional

from pipecat.frames.frames import (
    Frame,
    TTSTextFrame,
    LLMTextFrame,
    LLMFullResponseEndFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from app.conversation_tools import assistant_requests_follow_up, is_terminal_utterance
from app.tool_safety import set_last_user_text

logger = logging.getLogger(__name__)


class TranscriptLogger(FrameProcessor):
    """Forward-only processor that logs assistant and/or user transcript lines.

    Args:
        capture: which side to log — "assistant" (TTS/LLM reply text, place AFTER
            the LLM), "user" (TranscriptionFrame, place BEFORE the LLM), or "both".
    """

    def __init__(
        self,
        capture: str = "both",
        send_transcript: Optional[Callable[[str, str], Awaitable[None]]] = None,
        on_terminal_user_text: Optional[Callable[[], None]] = None,
        on_follow_up_assistant_text: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._capture = capture
        self._send_transcript = send_transcript
        self._on_terminal_user_text = on_terminal_user_text
        self._on_follow_up_assistant_text = on_follow_up_assistant_text
        self._assistant_buf: list[str] = []

    async def _emit_transcript(self, role: str, text: str) -> None:
        if self._send_transcript is None:
            return
        try:
            await self._send_transcript(role, text)
        except Exception as e:
            logger.warning("Failed to emit %s transcript to device: %r", role, e)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if self._capture in ("assistant", "both"):
            # Accumulate the reply text chunks (audio modality -> TTSTextFrame;
            # text modality -> LLMTextFrame), then log once per response on the
            # End bracket so it's one readable line instead of one per chunk.
            if isinstance(frame, (TTSTextFrame, LLMTextFrame)):
                if frame.text:
                    self._assistant_buf.append(frame.text)
            elif isinstance(frame, LLMFullResponseEndFrame):
                text = "".join(self._assistant_buf).strip()
                self._assistant_buf = []
                if text:
                    await self._emit_transcript("assistant", text)
                    if (
                        self._on_follow_up_assistant_text is not None
                        and assistant_requests_follow_up(text)
                    ):
                        try:
                            self._on_follow_up_assistant_text()
                        except Exception as e:
                            logger.warning("Failed to request assistant follow-up: %r", e)
                    logger.info(f"🤖 assistant: {text}")

        if self._capture in ("user", "both"):
            if isinstance(frame, TranscriptionFrame):
                text = (frame.text or "").strip()
                if text:
                    set_last_user_text(text)
                    await self._emit_transcript("user", text)
                    if self._on_terminal_user_text is not None and is_terminal_utterance(text):
                        self._on_terminal_user_text()
                    logger.info(f"🗣️ user: {text}")

        await self.push_frame(frame, direction)
