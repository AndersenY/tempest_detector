import numpy as np
from .models import Spectrum


def estimate_display_line(spectrum: Spectrum) -> float:
    """
    Авто-расчёт Display Line по модели гауссового шума (п. 3.1 ТЗ).

    Алгоритм: медиана + 2σ, где σ оценивается по IQR (устойчиво к выбросам-сигналам).
    Результат компенсирует флюктуации ±6 дБ: 2σ ≈ 3 дБ запас для типичного флуктуирующего фона.
    """
    a = spectrum.amplitudes_db
    median = float(np.median(a))
    q25, q75 = np.percentile(a, [25, 75])
    sigma = (q75 - q25) / 1.349   # перевод IQR → σ (Gaussian)
    # On a perfectly flat/low-noise spectrum sigma → 0, which collapses the
    # display line to the median and triggers false detections. Enforce a
    # minimum of 0.5 dB to keep a small but non-zero guard margin.
    sigma = max(sigma, 0.5)
    return median + 2.0 * sigma


def find_peak_in_window(
    spectrum: Spectrum,
    center_hz: float,
    window_hz: float,
) -> tuple[float, float]:
    """
    Поиск максимума в окне [center ± window/2].

    Возвращает (freq_hz, amplitude_db).
    Если окно пусто — возвращает ближайший бин.
    """
    freqs = spectrum.frequencies_hz
    amps  = spectrum.amplitudes_db
    mask  = np.abs(freqs - center_hz) <= window_hz / 2
    if not mask.any():
        idx = int(np.argmin(np.abs(freqs - center_hz)))
        return float(freqs[idx]), float(amps[idx])
    sub_amps  = amps[mask]
    sub_freqs = freqs[mask]
    best = int(np.argmax(sub_amps))
    return float(sub_freqs[best]), float(sub_amps[best])


def median_filter(spectrum: Spectrum, kernel_bins: int = 5) -> np.ndarray:
    """Медианная фильтрация амплитуд (подавление импульсных помех)."""
    from scipy.ndimage import median_filter as _mf
    k = max(1, kernel_bins | 1)   # нечётное
    return _mf(spectrum.amplitudes_db, size=k)


def snr_db(signal_amp_db: float, noise_amp_db: float) -> float:
    """Отношение сигнал/шум в дБ."""
    return signal_amp_db - noise_amp_db
