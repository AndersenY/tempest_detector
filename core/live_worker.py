import time
import threading
from copy import copy
from PyQt6.QtCore import QThread, pyqtSignal
from .backends import BaseInstrument
from .config import PanoramaConfig


class LiveWorker(QThread):
    """Непрерывный захват спектра для режима прямого эфира.

    Запускает configure() один раз при старте, затем в цикле вызывает
    capture_spectrum() и эмитит spectrum_ready. Если снаружи вызван
    update_config(), конфиг применяется при следующей итерации цикла.
    """

    spectrum_ready = pyqtSignal(object, object)   # freqs_hz ndarray, amps_db ndarray
    error = pyqtSignal(str)

    def __init__(self, ctrl: BaseInstrument, cfg: PanoramaConfig) -> None:
        super().__init__()
        self._ctrl = ctrl
        self._cfg = cfg
        self._stop = False
        self._pending_cfg: PanoramaConfig | None = None
        self._cfg_lock = threading.Lock()

    def stop(self) -> None:
        self._stop = True

    def update_config(self, cfg: PanoramaConfig) -> None:
        """Применить новый конфиг на лету (вступит в силу на следующей итерации)."""
        with self._cfg_lock:
            self._pending_cfg = copy(cfg)

    # Минимальный интервал между кадрами.
    # Предотвращает переполнение очереди сигналов Qt когда бэкенд
    # (симулятор) работает быстрее, чем GUI успевает отрисовать.
    # Реальный SDR ограничен скоростью захвата и обычно этот лимит не достигает.
    _MIN_FRAME_S = 1.0 / 60   # ≈60 кадров/с максимум

    def run(self) -> None:
        try:
            self._ctrl.configure(self._cfg)
            while not self._stop:
                t0 = time.perf_counter()

                with self._cfg_lock:
                    pending = self._pending_cfg
                    self._pending_cfg = None
                if pending is not None:
                    self._cfg = pending
                    self._ctrl.configure(self._cfg)

                spec = self._ctrl.capture_spectrum()
                if not self._stop:
                    self.spectrum_ready.emit(
                        spec.frequencies_hz.copy(),
                        spec.amplitudes_db.copy(),
                    )

                # Если захват завершился быстрее _MIN_FRAME_S — немного ждём.
                # Это нужно только для симулятора без задержки.
                remaining = self._MIN_FRAME_S - (time.perf_counter() - t0)
                if remaining > 0.001:
                    time.sleep(remaining)

        except Exception as e:
            if not self._stop:
                self.error.emit(str(e))
