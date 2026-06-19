"""Simple serializer for raw binary PCM audio frames."""

import json
import logging
import os
import time

from pipecat.frames.frames import Frame, InputAudioRawFrame, OutputAudioRawFrame
from pipecat.serializers.base_serializer import FrameSerializer, FrameSerializerType

logger = logging.getLogger(__name__)


class RawAudioSerializer(FrameSerializer):
    """Serializer that treats binary messages as raw PCM audio.

    Text frames are small JSON control messages from the device. They are
    handled here because the Pipecat websocket transport routes all incoming
    messages through the serializer.
    """

    def __init__(self, input_sample_rate: int | None = None):
        # The device streams 16 kHz PCM16 mono. Pipecat/OpenAI Realtime runs at
        # 24 kHz, so websocket_handler.py adds an input resampler after this
        # serializer.
        if input_sample_rate is None:
            input_sample_rate = int(os.environ.get("DEVICE_INPUT_SAMPLE_RATE", "16000"))
        self._input_sample_rate = input_sample_rate
        self._on_interrupt = None
        self._on_flush = None
        self._on_wake = None
        self._audio_window_control = "connect"
        self._audio_window_started = time.monotonic()
        self._audio_window_frames = 0
        self._audio_window_bytes = 0
        self._audio_first_frame_logged = False

    def set_interrupt_handler(self, handler):
        """Register the async callback fired on device 'interrupt'."""
        self._on_interrupt = handler

    def set_flush_handler(self, handler):
        """Register the async callback fired on device 'flush'."""
        self._on_flush = handler

    def set_wake_handler(self, handler):
        """Register the async callback fired on device 'wake'."""
        self._on_wake = handler

    @property
    def type(self) -> FrameSerializerType:
        """Get the serialization type."""
        return FrameSerializerType.BINARY

    async def deserialize(self, message: bytes) -> InputAudioRawFrame | None:
        """Deserialize a websocket message into a Pipecat input frame."""
        if isinstance(message, str):
            try:
                data = json.loads(message)
            except (ValueError, TypeError):
                return None

            if isinstance(data, dict):
                message_type = data.get("type")
                if message_type == "interrupt":
                    logger.info("device interrupt received")
                    self._log_audio_window("interrupt")
                    await self._run_control_handler(self._on_interrupt, "interrupt")
                elif message_type == "flush":
                    self._log_audio_window("flush")
                    await self._run_control_handler(self._on_flush, "flush")
                    self._reset_audio_window("flush")
                elif message_type == "wake":
                    logger.info("device wake received")
                    self._reset_audio_window("wake")
                    await self._run_control_handler(self._on_wake, "wake")
            return None

        if not isinstance(message, bytes):
            return None

        if len(message) % 2 != 0:
            logger.warning("Received audio with odd byte count: %s bytes, skipping", len(message))
            return None

        self._audio_window_frames += 1
        self._audio_window_bytes += len(message)
        if not self._audio_first_frame_logged:
            self._audio_first_frame_logged = True
            logger.info(
                "device audio after %s: first frame=%s bytes rate=%sHz",
                self._audio_window_control,
                len(message),
                self._input_sample_rate,
            )

        return InputAudioRawFrame(
            audio=message,
            sample_rate=self._input_sample_rate,
            num_channels=1,
        )

    def _reset_audio_window(self, control: str) -> None:
        self._audio_window_control = control
        self._audio_window_started = time.monotonic()
        self._audio_window_frames = 0
        self._audio_window_bytes = 0
        self._audio_first_frame_logged = False

    def _log_audio_window(self, control: str) -> None:
        elapsed_ms = int((time.monotonic() - self._audio_window_started) * 1000)
        if self._audio_window_frames == 0:
            logger.warning(
                "device %s received after %s: no audio frames in %sms",
                control,
                self._audio_window_control,
                elapsed_ms,
            )
            return
        logger.info(
            "device %s received after %s: %s audio frames, %s bytes in %sms",
            control,
            self._audio_window_control,
            self._audio_window_frames,
            self._audio_window_bytes,
            elapsed_ms,
        )

    async def _run_control_handler(self, handler, name: str) -> None:
        if handler is None:
            return
        try:
            await handler()
        except Exception as e:
            logger.warning("device %s handler failed: %r", name, e)

    async def serialize(self, frame: Frame) -> bytes:
        """Serialize output audio frames to raw PCM bytes."""
        if isinstance(frame, OutputAudioRawFrame):
            audio_bytes = frame.audio
            logger.debug("Serializing OutputAudioRawFrame: %s bytes", len(audio_bytes))
            return audio_bytes
        logger.debug("Serializing non-audio frame: %s, returning empty bytes", type(frame).__name__)
        return b""
