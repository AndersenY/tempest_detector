import numpy as np
from typing import List
from .models import Spectrum, PEMINSignal
from .config import PanoramaConfig


class PanoramaProcessor:
    def __init__(self, cfg: PanoramaConfig):
        self.cfg = cfg
        self.window = np.hanning(cfg.fft_size)

    def subtract(self, on: Spectrum, off: Spectrum) -> np.ndarray:
        """Вычисление разности панорам (ON - OFF)"""
        if on.amplitudes_db.shape != off.amplitudes_db.shape:
            raise ValueError("Размеры спектров ON и OFF не совпадают")
        return on.amplitudes_db - off.amplitudes_db

    def detect(self, diff_db: np.ndarray, on: Spectrum) -> List[PEMINSignal]:
        """Поиск кандидатов, превысивших порог"""
        above_indices = np.where(diff_db > self.cfg.threshold_db)[0]

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
        """
        Из кандидатов, расположенных ближе min_separation_hz друг к другу,
        оставляет только сигнал с максимальной амплитудой.
        Обрабатывает список отсортированным по частоте.
        """
        if not signals:
            return signals

        sep = self.cfg.min_separation_hz
        # Сортируем по частоте
        sorted_sigs = sorted(signals, key=lambda s: s.frequency_hz)

        kept: List[PEMINSignal] = []
        i = 0
        while i < len(sorted_sigs):
            # Собираем группу сигналов в пределах sep от текущего
            group = [sorted_sigs[i]]
            j = i + 1
            while j < len(sorted_sigs) and sorted_sigs[j].frequency_hz - sorted_sigs[i].frequency_hz < sep:
                group.append(sorted_sigs[j])
                j += 1
            # Из группы берём сигнал с максимальным превышением
            best = max(group, key=lambda s: s.amplitude_diff_db)
            kept.append(best)
            i = j

        return kept

    def _group_triplets(self, indices: np.ndarray, diff_db: np.ndarray, on: Spectrum) -> List[PEMINSignal]:
        """
        Алгоритм п. 6.2.2 РЭ:
        Из каждых трёх СМЕЖНЫХ (по индексу в спектре) точек, превысивших порог,
        в список попадает только одна — с максимальной амплитудой.

        Важно: «смежные» означает соседние по индексу в массиве спектра,
        а не просто каждые три из общего списка превышений.
        """
        signals = []
        if not indices.size:
            return signals

        # Шаг 1: разбиваем линейный список индексов на группы смежных индексов.
        # Пример: [10, 11, 12, 50, 51] → [[10, 11, 12], [50, 51]]
        groups = []
        current_group = [indices[0]]
        for i in range(1, len(indices)):
            if indices[i] == indices[i - 1] + 1:
                current_group.append(indices[i])
            else:
                groups.append(current_group)
                current_group = [indices[i]]
        groups.append(current_group)

        # Шаг 2: внутри каждой группы смежных точек берём чанки по 3.
        # Каждый чанк — самостоятельная «тройка», из которой берём максимум.
        for group in groups:
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
        amp_off = amp_on - amp_diff

        return PEMINSignal(
            frequency_hz=float(on.frequencies_hz[idx]),
            amplitude_diff_db=float(amp_diff),
            amplitude_on_db=float(amp_on),
            amplitude_off_db=float(amp_off),
            rbw_hz=on.rbw_hz,
            spectrum_index=int(idx),
        )

    def verify_1(self, sig: PEMINSignal, new_on_db: float) -> bool:
        """
        Тест ВКЛ (п. 7.4 РЭ).
        Если новый избыток упал ниже 50 % от исходного → сигнал нестабилен (помеха).
        Возвращает True, если сигнал СТАБИЛЕН (тест пройден).
        """
        orig_excess = sig.amplitude_on_db - sig.amplitude_off_db
        if orig_excess <= 0:
            return False
        new_excess = new_on_db - sig.amplitude_off_db
        return new_excess >= (self.cfg.verification_ratio * orig_excess)

    def verify_2(self, sig: PEMINSignal, new_off_db: float) -> bool:
        """
        Тест ВЫКЛ (п. 7.4 РЭ).
        Проверяем, что уровень фона в точке не вырос аномально при выключенном тесте.
        Критерий: рост фона не более drift_limit дБ относительно исходного фона.

        Если фон вырос сильно — значит, в эфире появилось внешнее устройство
        (оно работало уже во время измерения фона и продолжает работать).
        Возвращает True, если фон чистый (тест пройден).

        Примечание: РЭ не фиксирует конкретное числовое значение порога для В2,
        формулируя критерий как «наличие сигнала». 6 дБ — стандартный инженерный
        выбор, совпадающий с порогом обнаружения.
        """
        return (new_off_db - sig.amplitude_off_db) < self.cfg.v2_drift_limit_db