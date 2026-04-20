import time
import numpy as np
from .base import BaseInstrument
from ..config import PanoramaConfig
from ..models import Spectrum

_N_BINS = 4096


class DemoSimulator(BaseInstrument):
    """
    Синтетический генератор спектра для работы без SDR-оборудования.

    Моделирует VGA-подобный ПЭМИН-сигнал: шумовой фон + ряд гармоник n·F₁.
    Тестовый сигнал включается/выключается флагом `test_active`.

    Типичный сценарий (управляется MainWindow):
      capture 1 → test_active=False  → фон (OFF)
      capture 2 → test_active=True   → сигнал (ON)
      capture 3 → test_active=True   → верификация В1
      capture 4 → test_active=False  → верификация В2
    """

    _NOISE_FLOOR_DB  = -80.0
    _NOISE_SIGMA_DB  =  1.5
    _SIGNAL_PEAK_DB  = -45.0   # ~35 дБ над шумом — реалистичный ПЭМИН
    _HARMONIC_STEP   =  7.0    # дБ ослабления на каждую следующую гармонику
    _PEAK_SPREAD     =  4      # полуширина пика (бинов)
    _MEASURE_DELAY_S =  0.25   # имитация времени захвата

    def __init__(self) -> None:
        self._cfg: PanoramaConfig | None = None
        self._f1_hz: float = 0.0
        self.test_active: bool = False

    @property
    def name(self) -> str:
        return "Демо-симулятор"

    @property
    def is_connected(self) -> bool:
        return True

    def connect(self) -> None:
        pass

    def close(self) -> None:
        self.test_active = False

    def configure(self, cfg: PanoramaConfig) -> None:
        self._cfg = cfg
        span = cfg.stop_freq_hz - cfg.start_freq_hz
        # F₁ выбирается так, чтобы все запрошенные гармоники поместились в диапазон
        n = max(cfg.harmonic_max_count, 3)
        self._f1_hz = cfg.start_freq_hz + span / (n + 1)

    def capture_spectrum(self) -> Spectrum:
        if not self._cfg:
            raise RuntimeError("Симулятор не настроен — вызовите configure().")

        cfg = self._cfg
        freqs = np.linspace(cfg.start_freq_hz, cfg.stop_freq_hz, _N_BINS)
        rbw   = (cfg.stop_freq_hz - cfg.start_freq_hz) / _N_BINS

        amplitudes = np.random.normal(self._NOISE_FLOOR_DB, self._NOISE_SIGMA_DB, _N_BINS)

        if self.test_active:
            self._add_harmonics(amplitudes, freqs, rbw, cfg)

        time.sleep(self._MEASURE_DELAY_S)

        return Spectrum(
            frequencies_hz=freqs,
            amplitudes_db=amplitudes,
            rbw_hz=rbw,
            timestamp=time.time(),
        )

    # ------------------------------------------------------------------

    def _add_harmonics(self, amplitudes: np.ndarray, freqs: np.ndarray,
                       rbw: float, cfg: PanoramaConfig) -> None:
        for n in range(1, cfg.harmonic_max_count + 1):
            freq_n = self._f1_hz * n
            if freq_n < cfg.start_freq_hz or freq_n > cfg.stop_freq_hz:
                continue

            peak_db = self._SIGNAL_PEAK_DB - (n - 1) * self._HARMONIC_STEP
            # небольшой разброс амплитуды между измерениями (нестабильность ≈ 0.5 дБ)
            peak_db += np.random.normal(0.0, 0.5)

            idx = int(round((freq_n - cfg.start_freq_hz) / rbw))
            for k in range(-self._PEAK_SPREAD, self._PEAK_SPREAD + 1):
                j = idx + k
                if 0 <= j < _N_BINS:
                    # Гауссова форма пика
                    bin_amp = peak_db - k * k * 1.8
                    if bin_amp > amplitudes[j]:
                        amplitudes[j] = bin_amp
