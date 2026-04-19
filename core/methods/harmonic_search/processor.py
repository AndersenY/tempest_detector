import numpy as np
from typing import List, Tuple
from ...models import Spectrum, PEMINSignal
from ...config import PanoramaConfig


class HarmonicProcessor:
    """
    Метод поиска по гармоникам.

    Алгоритм:
    1. Из разности ON−OFF находим кандидаты выше порога (те же, что и в методе разности).
    2. Для каждого кандидата на частоте f ищем гармоники 2f, 3f, ..., N·f в разностном спектре.
    3. Если найдено ≥ harmonic_min_count гармоник → ПЭМИН (зелёный, сразу, без В1/В2).
       Если найдено < harmonic_min_count гармоник → неопределённо (жёлтый).
       Если гармоник нет — помеха (красный).
    """

    def __init__(self, cfg: PanoramaConfig):
        self.cfg = cfg

    # ------------------------------------------------------------------
    # Основные методы
    # ------------------------------------------------------------------

    def subtract(self, on: Spectrum, off: Spectrum) -> np.ndarray:
        if on.amplitudes_db.shape != off.amplitudes_db.shape:
            raise ValueError("Размеры спектров ON и OFF не совпадают")
        return on.amplitudes_db - off.amplitudes_db

    def detect_candidates(self, diff_db: np.ndarray, on: Spectrum) -> List[PEMINSignal]:
        """Первичное обнаружение кандидатов по порогу (без верификации)."""
        above = np.where(diff_db > self.cfg.threshold_db)[0]
        if not above.size:
            return []

        # Группировка смежных точек — берём максимум из каждой группы
        groups = self._split_contiguous(above)
        signals = []
        for group in groups:
            arr = np.array(group)
            best = arr[np.argmax(diff_db[arr])]
            signals.append(self._make_signal(best, diff_db, on))

        if self.cfg.min_separation_hz > 0:
            signals = self._filter_by_separation(signals)

        return signals

    def analyze_harmonics(
        self,
        candidates: List[PEMINSignal],
        diff_db: np.ndarray,
        freqs_hz: np.ndarray,
    ) -> List[PEMINSignal]:
        """
        Для каждого кандидата ищет гармоники в разностном спектре и
        выставляет статус и цвет.
        """
        for sig in candidates:
            found_freqs, found_amps = self._find_harmonics(
                sig.frequency_hz, diff_db, freqs_hz
            )
            sig.harmonic_frequencies_hz = found_freqs
            sig.harmonic_amplitudes_db = found_amps
            sig.harmonic_count = len(found_freqs)

            if sig.harmonic_count >= self.cfg.harmonic_min_count:
                sig.status_color = "green"
                sig.verified_1 = True
                sig.verified_2 = True
            elif sig.harmonic_count > 0:
                sig.status_color = "yellow"
                sig.verified_1 = None
                sig.verified_2 = None
            else:
                sig.status_color = "red"
                sig.verified_1 = False
                sig.verified_2 = None

        return candidates

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _find_harmonics(
        self,
        f0: float,
        diff_db: np.ndarray,
        freqs_hz: np.ndarray,
    ) -> Tuple[List[float], List[float]]:
        """
        Ищет гармоники n·f0 (n = 2..harmonic_max_count) в diff_db.
        Допуск: половина RBW или harmonic_tolerance_hz, если задан явно.
        """
        tol = self.cfg.harmonic_tolerance_hz
        if tol <= 0:
            rbw = freqs_hz[1] - freqs_hz[0] if len(freqs_hz) > 1 else 1.0
            tol = rbw * 2.0  # ±2 бина

        found_freqs: List[float] = []
        found_amps: List[float] = []

        for n in range(2, self.cfg.harmonic_max_count + 1):
            target = n * f0
            if target > freqs_hz[-1]:
                break
            idx = np.argmin(np.abs(freqs_hz - target))
            if np.abs(freqs_hz[idx] - target) <= tol:
                if diff_db[idx] > self.cfg.threshold_db:
                    found_freqs.append(float(freqs_hz[idx]))
                    found_amps.append(float(diff_db[idx]))

        return found_freqs, found_amps

    def _split_contiguous(self, indices: np.ndarray) -> List[List[int]]:
        groups: List[List[int]] = []
        current = [int(indices[0])]
        for i in range(1, len(indices)):
            if indices[i] == indices[i - 1] + 1:
                current.append(int(indices[i]))
            else:
                groups.append(current)
                current = [int(indices[i])]
        groups.append(current)
        return groups

    def _filter_by_separation(self, signals: List[PEMINSignal]) -> List[PEMINSignal]:
        sep = self.cfg.min_separation_hz
        sorted_sigs = sorted(signals, key=lambda s: s.frequency_hz)
        kept: List[PEMINSignal] = []
        i = 0
        while i < len(sorted_sigs):
            group = [sorted_sigs[i]]
            j = i + 1
            while j < len(sorted_sigs) and sorted_sigs[j].frequency_hz - sorted_sigs[i].frequency_hz < sep:
                group.append(sorted_sigs[j])
                j += 1
            kept.append(max(group, key=lambda s: s.amplitude_diff_db))
            i = j
        return kept

    def _make_signal(self, idx: int, diff_db: np.ndarray, on: Spectrum) -> PEMINSignal:
        amp_on = on.amplitudes_db[idx]
        amp_diff = diff_db[idx]
        return PEMINSignal(
            frequency_hz=float(on.frequencies_hz[idx]),
            amplitude_diff_db=float(amp_diff),
            amplitude_on_db=float(amp_on),
            amplitude_off_db=float(amp_on - amp_diff),
            rbw_hz=on.rbw_hz,
            spectrum_index=int(idx),
            detection_method="harmonic_search",
        )
