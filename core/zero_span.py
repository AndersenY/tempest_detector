from copy import copy
from PyQt6.QtCore import QThread, pyqtSignal
from .backends import BaseInstrument
from .config import PanoramaConfig
from .signal_processor import find_peak_in_window


class ZeroSpanWorker(QThread):
    """
    Непрерывный захват амплитуды на фиксированной частоте (нулевой обзор).

    Перенастраивает прибор на узкую полосу ±_HALF_SPAN вокруг целевой частоты,
    захватывает спектр в цикле, извлекает пиковую амплитуду и испускает сигнал.
    При остановке восстанавливает исходный PanoramaConfig.
    """

    amplitude_updated = pyqtSignal(float)   # текущий уровень в дБ
    error = pyqtSignal(str)

    _HALF_SPAN = 250_000   # ±250 кГц — минимально надёжный диапазон для RTL-SDR

    def __init__(self, ctrl: BaseInstrument, cfg: PanoramaConfig,
                 freq_hz: float) -> None:
        super().__init__()
        self._ctrl    = ctrl
        self._cfg     = cfg        # исходный конфиг — восстанавливается после остановки
        self._freq_hz = freq_hz
        self._stop    = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        narrow = copy(self._cfg)
        narrow.start_freq_hz   = self._freq_hz - self._HALF_SPAN
        narrow.stop_freq_hz    = self._freq_hz + self._HALF_SPAN
        narrow.averaging_count = 3
        narrow.use_max_hold    = False

        try:
            self._ctrl.configure(narrow)
            while not self._stop:
                spec = self._ctrl.capture_spectrum()
                _, amp = find_peak_in_window(
                    spec, self._freq_hz, self._HALF_SPAN * 1.6
                )
                if not self._stop:
                    self.amplitude_updated.emit(amp)
        except Exception as e:
            if not self._stop:
                self.error.emit(str(e))
        finally:
            try:
                self._ctrl.configure(self._cfg)
            except Exception:
                pass
