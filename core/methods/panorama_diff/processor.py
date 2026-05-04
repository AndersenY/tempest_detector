import numpy as np
from typing import List
from ...models import Spectrum, PEMINSignal
from ...config import PanoramaConfig


class PanoramaProcessor:
    def __init__(self, cfg: PanoramaConfig):
        self.cfg = cfg

    def subtract(self, on: Spectrum, off: Spectrum) -> np.ndarray:
        if on.amplitudes_db.shape != off.amplitudes_db.shape:
            raise ValueError("Размеры спектров ON и OFF не совпадают")
        return on.amplitudes_db - off.amplitudes_db

    def effective_threshold(self, diff_db: np.ndarray) -> float:
        """Порог с адаптацией к уровню шума: max(fixed, median + k·MAD_sigma)."""
        if not self.cfg.use_adaptive_threshold:
            return self.cfg.threshold_db
        median = float(np.median(diff_db))
        mad = float(np.median(np.abs(diff_db - median)))
        adaptive = median + self.cfg.adaptive_threshold_sigma * 1.4826 * mad
        return max(self.cfg.threshold_db, adaptive)

    def detect(self, diff_db: np.ndarray, on: Spectrum) -> List[PEMINSignal]:
        threshold = self.effective_threshold(diff_db)
        above_indices = np.where(diff_db > threshold)[0]
        if not above_indices.size:
            return []

        if self.cfg.combine_triplets:
            signals = self._group_triplets(above_indices, diff_db, on)
        else:
            signals = [self._make_signal(idx, diff_db, on) for idx in above_indices]

        if self.cfg.min_separation_hz > 0:
            signals = self._filter_by_separation(signals)

        return signals

    def _filter_by_separation(self, signals: List[PEMINSignal]) -> List[PEMINSignal]:
        if not signals:
            return signals
        sep = self.cfg.min_separation_hz
        sorted_sigs = sorted(signals, key=lambda s: s.frequency_hz)
        # Greedy scan: compare each candidate to the last kept signal.
        # Guarantees that no two kept signals are within sep Hz of each other,
        # even when the strongest in a cluster is not the leftmost element.
        kept: List[PEMINSignal] = [sorted_sigs[0]]
        for sig in sorted_sigs[1:]:
            if sig.frequency_hz - kept[-1].frequency_hz >= sep:
                kept.append(sig)
            elif sig.amplitude_diff_db > kept[-1].amplitude_diff_db:
                kept[-1] = sig
        return kept

    def _group_triplets(self, indices: np.ndarray, diff_db: np.ndarray, on: Spectrum) -> List[PEMINSignal]:
        signals = []
        if not indices.size:
            return signals

        groups = []
        current_group = [indices[0]]
        for i in range(1, len(indices)):
            if indices[i] == indices[i - 1] + 1:
                current_group.append(indices[i])
            else:
                groups.append(current_group)
                current_group = [indices[i]]
        groups.append(current_group)

        min_bins = max(1, self.cfg.min_cluster_bins)
        for group in groups:
            if len(group) < min_bins:
                continue
            for start in range(0, len(group), 3):
                chunk = group[start:start + 3]
                if not chunk:
                    continue
                chunk_arr = np.array(chunk)
                best_local_idx = np.argmax(diff_db[chunk_arr])
                best_global_idx = chunk_arr[best_local_idx]
                sig = self._make_signal(best_global_idx, diff_db, on)
                sig.is_triplet_representative = True
                signals.append(sig)

        return signals

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
            detection_method="panorama_diff",
        )

    def verify_1(self, sig: PEMINSignal, new_on_db: float) -> bool:
        orig_excess = sig.amplitude_on_db - sig.amplitude_off_db
        if orig_excess <= 0:
            return False
        new_excess = new_on_db - sig.amplitude_off_db
        return new_excess >= (self.cfg.verification_ratio * orig_excess)

    def verify_2(self, sig: PEMINSignal, new_off_db: float) -> bool:
        return (new_off_db - sig.amplitude_off_db) < self.cfg.v2_drift_limit_db
