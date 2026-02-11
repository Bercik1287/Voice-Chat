"""Moduł audio – przechwytywanie i odtwarzanie dźwięku z kompresją Opus."""

import logging
import struct
import threading
from collections import deque

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------
# Stałe audio
# ---------------------------------------------------------------
SAMPLE_RATE = 48000       # Hz (wymagane przez Opus)
CHANNELS = 1              # mono
FRAME_DURATION_MS = 20    # 20 ms ramki – optymalnie dla Opus
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # 960 próbek
DTYPE = "int16"

# Próbujemy importować opuslib, jeśli niedostępne – surowy PCM
try:
    import opuslib
    HAS_OPUS = True
    logger.info("Codec Opus dostępny – kompresja włączona.")
except ImportError:
    HAS_OPUS = False
    logger.warning("opuslib niedostępne – transmisja surowym PCM (większe zużycie pasma).")


class AudioCodec:
    """Enkoder/dekoder audio (Opus lub surowy PCM jako fallback)."""

    def __init__(self, sample_rate: int = SAMPLE_RATE, channels: int = CHANNELS):
        self.sample_rate = sample_rate
        self.channels = channels

        if HAS_OPUS:
            self.encoder = opuslib.Encoder(sample_rate, channels, opuslib.APPLICATION_VOIP)
            self.decoder = opuslib.Decoder(sample_rate, channels)
        else:
            self.encoder = None
            self.decoder = None

    def encode(self, pcm_data: bytes) -> bytes:
        """Kompresuje ramkę PCM int16."""
        if self.encoder:
            return self.encoder.encode(pcm_data, FRAME_SIZE)
        return pcm_data  # fallback – surowy PCM

    def decode(self, data: bytes) -> bytes:
        """Dekompresuje ramkę do PCM int16."""
        if self.decoder:
            return self.decoder.decode(data, FRAME_SIZE)
        return data  # fallback

    @property
    def is_compressed(self) -> bool:
        return HAS_OPUS


class AudioEngine:
    """Zarządza strumieniami wejścia/wyjścia audio."""

    def __init__(
        self,
        send_callback=None,
        sample_rate: int = SAMPLE_RATE,
        channels: int = CHANNELS,
    ):
        """
        Args:
            send_callback: Funkcja wywoływana z zakodowanymi danymi audio
                           do wysłania przez sieć: callback(encoded_bytes).
            sample_rate: Częstotliwość próbkowania.
            channels: Liczba kanałów (1 = mono).
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.send_callback = send_callback

        self.codec = AudioCodec(sample_rate, channels)

        self._input_stream: sd.InputStream | None = None
        self._output_stream: sd.OutputStream | None = None

        self._playback_buffer: deque[bytes] = deque(maxlen=50)  # ~1s bufora
        self._running = False
        self._muted = False

        # Poziom głośności wejścia/wyjścia (0.0 – 1.0)
        self.input_volume: float = 10.0
        self.output_volume: float = 10.0

        # Callback do informowania GUI o poziomie sygnału
        self.level_callback = None
        self._input_level: float = 0.0
        self._output_level: float = 0.0

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------
    def start(self):
        """Uruchamia strumienie audio."""
        if self._running:
            return

        self._running = True

        self._input_stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=DTYPE,
            blocksize=FRAME_SIZE,
            callback=self._input_callback,
        )

        self._output_stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=DTYPE,
            blocksize=FRAME_SIZE,
            callback=self._output_callback,
        )

        self._input_stream.start()
        self._output_stream.start()
        logger.info("Strumienie audio uruchomione.")

    def stop(self):
        """Zatrzymuje strumienie audio."""
        self._running = False

        if self._input_stream:
            self._input_stream.stop()
            self._input_stream.close()
            self._input_stream = None

        if self._output_stream:
            self._output_stream.stop()
            self._output_stream.close()
            self._output_stream = None

        self._playback_buffer.clear()
        logger.info("Strumienie audio zatrzymane.")

    # ------------------------------------------------------------------
    # Wyciszenie
    # ------------------------------------------------------------------
    @property
    def muted(self) -> bool:
        return self._muted

    @muted.setter
    def muted(self, value: bool):
        self._muted = value
        logger.info("Mikrofon %s.", "wyciszony" if value else "włączony")

    def toggle_mute(self) -> bool:
        self._muted = not self._muted
        return self._muted

    # ------------------------------------------------------------------
    # Odtwarzanie odebranych danych
    # ------------------------------------------------------------------
    def receive_audio(self, encoded_data: bytes):
        """Dodaje odebrane dane audio do bufora odtwarzania."""
        try:
            pcm_data = self.codec.decode(encoded_data)
            self._playback_buffer.append(pcm_data)
        except Exception as exc:
            logger.warning("Błąd dekodowania audio: %s", exc)

    # ------------------------------------------------------------------
    # Callbacki strumieni
    # ------------------------------------------------------------------
    def _input_callback(self, indata, frames, time_info, status):
        """Wywoływane przez sounddevice gdy mamy nowe dane z mikrofonu."""
        if status:
            logger.debug("Input status: %s", status)

        if not self._running:
            return

        # Oblicz poziom sygnału
        audio_array = np.frombuffer(indata, dtype=np.int16).astype(np.float32)
        if len(audio_array) > 0:
            rms = np.sqrt(np.mean(audio_array ** 2)) / 32768.0
            self._input_level = min(rms * 5, 1.0)  # skaluj do 0-1

        if self._muted:
            return

        # Zastosuj głośność wejściową
        if self.input_volume < 1.0:
            audio_array = np.frombuffer(indata, dtype=np.int16).astype(np.float32)
            audio_array *= self.input_volume
            pcm_bytes = audio_array.astype(np.int16).tobytes()
        else:
            pcm_bytes = bytes(indata)

        # Enkoduj i wyślij
        if self.send_callback:
            try:
                encoded = self.codec.encode(pcm_bytes)
                self.send_callback(encoded)
            except Exception as exc:
                logger.debug("Błąd enkodowania: %s", exc)

    def _output_callback(self, outdata, frames, time_info, status):
        """Wywoływane przez sounddevice gdy potrzebuje danych do odtworzenia."""
        if status:
            logger.debug("Output status: %s", status)

        if self._playback_buffer:
            pcm_data = self._playback_buffer.popleft()
            audio_array = np.frombuffer(pcm_data, dtype=np.int16).copy()

            # Zastosuj głośność wyjściową
            if self.output_volume < 1.0:
                float_array = audio_array.astype(np.float32)
                float_array *= self.output_volume
                audio_array = float_array.astype(np.int16)

            # Oblicz poziom sygnału wyjściowego
            self._output_level = min(
                np.sqrt(np.mean(audio_array.astype(np.float32) ** 2)) / 32768.0 * 5, 1.0
            )

            # Dopasuj rozmiar
            expected_bytes = frames * self.channels * 2  # int16 = 2 bajty
            data_bytes = audio_array.tobytes()

            if len(data_bytes) >= expected_bytes:
                outdata[:] = np.frombuffer(data_bytes[:expected_bytes], dtype=np.int16).reshape(
                    -1, self.channels
                )
            else:
                # Uzupełnij ciszą
                padded = data_bytes + b"\x00" * (expected_bytes - len(data_bytes))
                outdata[:] = np.frombuffer(padded, dtype=np.int16).reshape(-1, self.channels)
        else:
            # Cisza
            outdata.fill(0)
            self._output_level = 0.0

    # ------------------------------------------------------------------
    # Urządzenia
    # ------------------------------------------------------------------
    @staticmethod
    def list_input_devices() -> list[dict]:
        """Zwraca listę dostępnych urządzeń wejściowych."""
        devices = sd.query_devices()
        return [
            {"index": i, "name": d["name"], "channels": d["max_input_channels"]}
            for i, d in enumerate(devices)
            if d["max_input_channels"] > 0
        ]

    @staticmethod
    def list_output_devices() -> list[dict]:
        """Zwraca listę dostępnych urządzeń wyjściowych."""
        devices = sd.query_devices()
        return [
            {"index": i, "name": d["name"], "channels": d["max_output_channels"]}
            for i, d in enumerate(devices)
            if d["max_output_channels"] > 0
        ]

    @staticmethod
    def set_input_device(device_index: int):
        """Ustawia domyślne urządzenie wejściowe."""
        sd.default.device[0] = device_index

    @staticmethod
    def set_output_device(device_index: int):
        """Ustawia domyślne urządzenie wyjściowe."""
        sd.default.device[1] = device_index
