"""Emit deterministic va_client phase messages from Pipecat frames.

The device UI and mic gate are driven by compact JSON text messages:

    {"type":"phase","value":"listening|thinking|replying|idle"}

The important detail is that OpenAI Realtime replies can be segmented, and tool
calls can produce a BotStopped gap before the final answer. This processor keeps
the device in a stable phase across those gaps:

* user starts speaking -> listening
* user stops speaking -> delayed thinking fallback
* function/tool call -> thinking immediately
* tool result -> keep thinking until the post-tool reply starts
* bot starts speaking -> replying
* bot stops speaking -> idle only after a debounce, unless a tool reply is still pending
"""

import asyncio
import logging
import os

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)


class PhaseEmitter(FrameProcessor):
    """Forwards phase transitions to the device as JSON text frames."""

    def __init__(
        self,
        send_phase,
        send_json=None,
        idle_debounce_s: float = None,
        thinking_delay_s: float = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._send_phase = send_phase
        self._send_json = send_json

        if idle_debounce_s is None:
            try:
                idle_debounce_s = float(os.environ.get("PHASE_IDLE_DEBOUNCE_MS", "1500")) / 1000.0
            except (TypeError, ValueError):
                idle_debounce_s = 1.5
        if thinking_delay_s is None:
            try:
                thinking_delay_s = float(os.environ.get("PHASE_THINKING_DELAY_MS", "2500")) / 1000.0
            except (TypeError, ValueError):
                thinking_delay_s = 2.5

        self._idle_debounce_s = max(0.0, idle_debounce_s)
        self._thinking_delay_s = max(0.0, thinking_delay_s)
        self._idle_task: asyncio.Task | None = None
        self._thinking_task: asyncio.Task | None = None
        self._current: str | None = None
        self._tool_active = False
        self._awaiting_post_tool_reply = False
        self._follow_up_requested = False
        self._conversation_end_requested = False

    def request_follow_up(self) -> None:
        """Ask the device to open its follow-up mic window after this reply drains."""
        if self._conversation_end_requested:
            logger.info("request_follow_up ignored because conversation end is pending")
            return
        self._follow_up_requested = True

    def request_conversation_end(self) -> None:
        """Ask the device to show a terminal thanks state after this reply drains."""
        self._conversation_end_requested = True
        self._follow_up_requested = False

    async def _emit(self, value: str) -> None:
        if value == self._current:
            return
        self._current = value
        logger.info("phase -> %s", value)
        if self._send_phase is None:
            return
        try:
            await self._send_phase(value)
        except Exception as e:
            logger.warning("Failed to emit phase %r: %r", value, e)

    def _cancel_pending_idle(self) -> None:
        if self._idle_task is not None and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = None

    def _cancel_pending_thinking(self) -> None:
        if self._thinking_task is not None and not self._thinking_task.done():
            self._thinking_task.cancel()
        self._thinking_task = None

    async def _emit_idle_after_debounce(self) -> None:
        try:
            await asyncio.sleep(self._idle_debounce_s)
        except asyncio.CancelledError:
            return
        if self._tool_active or self._awaiting_post_tool_reply:
            self._idle_task = asyncio.create_task(self._emit_idle_after_debounce())
            return
        if self._conversation_end_requested:
            self._conversation_end_requested = False
            self._follow_up_requested = False
            if self._send_json is not None:
                try:
                    await self._send_json({"type": "thanks"})
                    await asyncio.sleep(0.9)
                except Exception as e:
                    logger.warning("Failed to emit thanks: %r", e)
        elif self._follow_up_requested:
            self._follow_up_requested = False
            if self._send_json is not None:
                try:
                    await self._send_json({"type": "request_follow_up"})
                except Exception as e:
                    logger.warning("Failed to emit request_follow_up: %r", e)
        await self._emit("idle")

    async def _emit_thinking_after_delay(self) -> None:
        try:
            await asyncio.sleep(self._thinking_delay_s)
        except asyncio.CancelledError:
            return
        if self._tool_active or self._awaiting_post_tool_reply:
            return
        await self._emit("thinking")

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame):
            self._cancel_pending_idle()
            self._cancel_pending_thinking()
            self._tool_active = False
            self._awaiting_post_tool_reply = False
            self._follow_up_requested = False
            self._conversation_end_requested = False
            await self._emit("listening")
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._cancel_pending_idle()
            self._cancel_pending_thinking()
            self._thinking_task = asyncio.create_task(self._emit_thinking_after_delay())
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._cancel_pending_idle()
            self._cancel_pending_thinking()
            self._tool_active = False
            self._awaiting_post_tool_reply = False
            await self._emit("replying")
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._cancel_pending_idle()
            self._idle_task = asyncio.create_task(self._emit_idle_after_debounce())
        else:
            frame_name = type(frame).__name__
            if frame_name in ("FunctionCallsStartedFrame", "FunctionCallInProgressFrame"):
                self._tool_active = True
                self._awaiting_post_tool_reply = False
                self._cancel_pending_idle()
                self._cancel_pending_thinking()
                await self._emit("thinking")
            elif frame_name == "FunctionCallResultFrame":
                self._tool_active = False
                self._awaiting_post_tool_reply = True
                self._cancel_pending_idle()
                self._cancel_pending_thinking()
                await self._emit("thinking")
            elif frame_name == "FunctionCallCancelFrame":
                self._tool_active = False
                self._awaiting_post_tool_reply = False
                self._follow_up_requested = False

        await self.push_frame(frame, direction)
