"""Audio recording utility for debugging."""

import logging
import os
import struct
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class AudioRecorder:
    """Records audio to WAV files for debugging."""

    def __init__(self, output_dir: str = "recordings"):
        """Initialize audio recorder."""
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        self._input_file: Optional[object] = None
        self._output_file: Optional[object] = None
        self._input_bytes = 0
        self._output_bytes = 0
        self._last_flush = time.monotonic()
        self._flush_interval_seconds = 1.0

    def start_recording(self, client_id: str):
        """Start recording audio for a client session."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        input_filename = os.path.join(
            self.output_dir,
            f"input_{client_id}_{timestamp}.wav",
        )
        self._input_file = open(input_filename, "wb")
        self._write_wav_header(self._input_file, sample_rate=24000, channels=1, bits_per_sample=16)
        self._input_bytes = 0

        output_filename = os.path.join(
            self.output_dir,
            f"output_{client_id}_{timestamp}.wav",
        )
        self._output_file = open(output_filename, "wb")
        self._write_wav_header(self._output_file, sample_rate=24000, channels=1, bits_per_sample=16)
        self._output_bytes = 0
        self._last_flush = time.monotonic()

        logger.info("Started recording: input=%s, output=%s", input_filename, output_filename)

    def record_input_audio(self, audio_bytes: bytes):
        """Record audio received from ESP32 device."""
        if self._input_file and audio_bytes:
            if len(audio_bytes) % 2 != 0:
                logger.warning("Input audio has odd byte count: %s, padding with zero", len(audio_bytes))
                audio_bytes = audio_bytes + b"\x00"
            self._input_file.write(audio_bytes)
            self._input_bytes += len(audio_bytes)
            self._maybe_flush()

    def record_output_audio(self, audio_bytes: bytes):
        """Record audio received from OpenAI."""
        if self._output_file and audio_bytes:
            if len(audio_bytes) % 2 != 0:
                logger.warning("Output audio has odd byte count: %s, padding with zero", len(audio_bytes))
                audio_bytes = audio_bytes + b"\x00"
            self._output_file.write(audio_bytes)
            self._output_bytes += len(audio_bytes)
            self._maybe_flush()

    def stop_recording(self):
        """Stop recording and finalize WAV files."""
        if self._input_file:
            self._update_wav_sizes(self._input_file, self._input_bytes)
            self._input_file.flush()
            self._input_file.close()
            self._input_file = None
            logger.info("Stopped input recording: %s bytes", self._input_bytes)

        if self._output_file:
            self._update_wav_sizes(self._output_file, self._output_bytes)
            self._output_file.flush()
            self._output_file.close()
            self._output_file = None
            logger.info("Stopped output recording: %s bytes", self._output_bytes)

    def _write_wav_header(self, file, sample_rate: int, channels: int, bits_per_sample: int):
        """Write a placeholder WAV file header."""
        byte_rate = sample_rate * channels * (bits_per_sample // 8)
        block_align = channels * (bits_per_sample // 8)

        file.write(b"RIFF")
        file.write(struct.pack("<I", 0))
        file.write(b"WAVE")

        file.write(b"fmt ")
        file.write(struct.pack("<I", 16))
        file.write(struct.pack("<H", 1))
        file.write(struct.pack("<H", channels))
        file.write(struct.pack("<I", sample_rate))
        file.write(struct.pack("<I", byte_rate))
        file.write(struct.pack("<H", block_align))
        file.write(struct.pack("<H", bits_per_sample))

        file.write(b"data")
        file.write(struct.pack("<I", 0))

    def _maybe_flush(self):
        """Flush diagnostic files occasionally without blocking every audio frame."""
        now = time.monotonic()
        if now - self._last_flush < self._flush_interval_seconds:
            return
        if self._input_file:
            self._update_wav_sizes(self._input_file, self._input_bytes)
            self._input_file.flush()
        if self._output_file:
            self._update_wav_sizes(self._output_file, self._output_bytes)
            self._output_file.flush()
        self._last_flush = now

    def _update_wav_sizes(self, file, data_size: int):
        """Refresh WAV size fields while preserving the current append offset."""
        pos = file.tell()
        file.seek(4)
        file.write(struct.pack("<I", 36 + data_size))
        file.seek(40)
        file.write(struct.pack("<I", data_size))
        file.seek(pos)
