import threading
import numpy as np


class AudioMonitor:
    """
    Тон-монитор уровня ПЭМИН-сигнала (аудиовизуальный метод, п. 3.1 ТЗ).

    Воспроизводит синусоидальный тон: частота линейно масштабируется по уровню дБ.
    Диапазон: _DB_MIN → _HZ_MIN (низкий тон), _DB_MAX → _HZ_MAX (высокий тон).

    Требует: pip install sounddevice
    Если sounddevice недоступен — работает в «немом» режиме (available=False).
    """

    _DB_MIN  = -90.0
    _DB_MAX  = -30.0
    _HZ_MIN  = 300
    _HZ_MAX  = 3000
    _SR      = 44100
    _GAIN    = 0.15    # громкость 0..1
    _BLOCK   = 1024    # сэмплов на фрейм

    def __init__(self) -> None:
        self._lock     = threading.Lock()
        self._freq_hz  = float(self._HZ_MIN)
        self._phase    = 0
        self._stream   = None
        self._active   = False

        try:
            import sounddevice as sd   # noqa: F401
            self._available = True
        except ImportError:
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    @property
    def active(self) -> bool:
        return self._active

    def set_amplitude(self, db: float) -> None:
        """Обновить тон под новый уровень сигнала (можно вызывать из любого потока)."""
        t = (db - self._DB_MIN) / (self._DB_MAX - self._DB_MIN)
        t = max(0.0, min(1.0, t))
        with self._lock:
            self._freq_hz = self._HZ_MIN + t * (self._HZ_MAX - self._HZ_MIN)

    def start(self) -> None:
        if not self._available or self._active:
            return
        import sounddevice as sd
        self._active = True
        self._phase  = 0
        self._stream = sd.OutputStream(
            samplerate=self._SR,
            channels=1,
            dtype="float32",
            blocksize=self._BLOCK,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        self._active = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _callback(self, outdata, frames, time_info, status) -> None:
        with self._lock:
            freq = self._freq_hz
        t = (self._phase + np.arange(frames, dtype=np.float64)) / self._SR
        wave = self._GAIN * np.sin(2.0 * np.pi * freq * t)
        outdata[:, 0] = wave.astype(np.float32)
        self._phase = (self._phase + frames) % self._SR
