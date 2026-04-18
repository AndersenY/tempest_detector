import numpy as np
from typing import List
from .models import SpectrumData, PEMINSignal, PanoramaConfig

class PanoramaProcessor:
    def __init__(self, config: PanoramaConfig):
        self.config = config

    def subtract_panoramas(self, spectrum_on: SpectrumData, spectrum_off: SpectrumData) -> np.ndarray:
        """Вычитание панорамы шума из панорамы с тестом"""
        if not np.array_equal(spectrum_on.frequencies, spectrum_off.frequencies):
            raise ValueError("Частотные сетки панорам не совпадают")
        return spectrum_on.amplitudes - spectrum_off.amplitudes

    def detect_signals(self, diff: np.ndarray, spectrum_on: SpectrumData) -> List[PEMINSignal]:
        """Поиск точек превышения порога"""
        above_thresh = np.where(diff > self.config.threshold_db)[0]
        if len(above_thresh) == 0:
            return []

        if self.config.combine_broadband:
            return self._group_triplets(diff, spectrum_on, above_thresh)
        else:
            return [
                PEMINSignal(
                    frequency=spectrum_on.frequencies[i],
                    amplitude_db=diff[i],
                    raw_amplitude_on=spectrum_on.amplitudes[i],
                    raw_amplitude_off=spectrum_on.amplitudes[i] - diff[i],
                    rbw_hz=spectrum_on.rbw_hz
                ) for i in above_thresh
            ]

    def _group_triplets(self, diff: np.ndarray, spectrum_on: SpectrumData, indices: np.ndarray) -> List[PEMINSignal]:
        """Алгоритм из п. 6.2.2: из каждых 3 смежных точек берется одна с макс. амплитудой"""
        signals = []
        for i in range(0, len(indices), 3):
            triplet = indices[i:i+3]
            if len(triplet) == 0:
                break
            max_idx = triplet[np.argmax(diff[triplet])]
            signals.append(PEMINSignal(
                frequency=spectrum_on.frequencies[max_idx],
                amplitude_db=diff[max_idx],
                raw_amplitude_on=spectrum_on.amplitudes[max_idx],
                raw_amplitude_off=spectrum_on.amplitudes[max_idx] - diff[max_idx],
                rbw_hz=spectrum_on.rbw_hz,
                is_broadband_group=True,
                marker_color="orange"
            ))
        return signals

    def verify_1(self, signal: PEMINSignal, new_amp_on: float) -> bool:
        """Верификация 1: тест ВКЛ. Если амплитуда упала >50% от превышения над шумом → помеха"""
        original_excess = signal.raw_amplitude_on - signal.raw_amplitude_off
        new_excess = new_amp_on - signal.raw_amplitude_off
        return new_excess >= 0.5 * original_excess

    def verify_2(self, signal: PEMINSignal, new_amp_off: float) -> bool:
        """Верификация 2: тест ВЫКЛ. Если уровень превышает порог → внешнее устройство"""
        return (new_amp_off - signal.raw_amplitude_off) <= self.config.threshold_db