import numpy as np
from typing import List
from .models import Spectrum, PEMINSignal
from .config import PanoramaConfig

class PanoramaProcessor:
    def __init__(self, cfg: PanoramaConfig):
        self.cfg = cfg

    def subtract(self, on: Spectrum, off: Spectrum) -> np.ndarray:
        # Сетки идентичны при неизменной конфигурации
        return on.amplitudes_db - off.amplitudes_db

    def detect(self, diff_db: np.ndarray, on: Spectrum) -> List[PEMINSignal]:
        above = np.where(diff_db > self.cfg.threshold_db)[0]
        if not above.size:
            return []
        return self._group_triplets(above, diff_db, on) if self.cfg.combine_triplets else \
            [self._make_signal(i, diff_db, on) for i in above]

    def _group_triplets(self, indices: np.ndarray, diff_db: np.ndarray, on: Spectrum) -> List[PEMINSignal]:
        signals = []
        for start in range(0, len(indices), 3):
            triplet = indices[start:start+3]
            if not triplet.size: break
            idx = triplet[np.argmax(diff_db[triplet])]
            sig = self._make_signal(idx, diff_db, on)
            sig.is_triplet_representative = True
            signals.append(sig)
        return signals

    def _make_signal(self, idx: int, diff_db: np.ndarray, on: Spectrum) -> PEMINSignal:
        return PEMINSignal(
            frequency_hz=on.frequencies_hz[idx],
            amplitude_diff_db=diff_db[idx],
            amplitude_on_db=on.amplitudes_db[idx],
            amplitude_off_db=on.amplitudes_db[idx] - diff_db[idx],
            rbw_hz=on.rbw_hz
        )

    def verify_1(self, sig: PEMINSignal, new_on_db: float) -> bool:
        """Тест ВКЛ. Если избыток упал >50% → помеха (п. 8.3.1)"""
        orig_excess = sig.amplitude_on_db - sig.amplitude_off_db
        new_excess = new_on_db - sig.amplitude_off_db
        return new_excess >= self.cfg.verification_ratio * orig_excess

    def verify_2(self, sig: PEMINSignal, new_off_db: float) -> bool:
        """Тест ВЫКЛ. Если уровень превысил порог → внешнее устройство (п. 8.3.1)"""
        return (new_off_db - sig.amplitude_off_db) <= self.cfg.threshold_db