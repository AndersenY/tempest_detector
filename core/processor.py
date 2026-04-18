import numpy as np
from typing import List
from .models import Spectrum, PEMINSignal
from .config import PanoramaConfig

class PanoramaProcessor:
    def __init__(self, cfg: PanoramaConfig):
        self.cfg = cfg
        # Предварительный расчет окна Ханна для эффективности
        self.window = np.hanning(cfg.fft_size)

    def subtract(self, on: Spectrum, off: Spectrum) -> np.ndarray:
        """Вычисление разности панорам (ON - OFF)"""
        # Проверка на совпадение размеров массивов на всякий случай
        if on.amplitudes_db.shape != off.amplitudes_db.shape:
            raise ValueError("Размеры спектров ON и OFF не совпадают")
        return on.amplitudes_db - off.amplitudes_db

    def detect(self, diff_db: np.ndarray, on: Spectrum) -> List[PEMINSignal]:
        """Поиск кандидатов, превысивших порог"""
        above_indices = np.where(diff_db > self.cfg.threshold_db)[0]
        
        if not above_indices.size:
            return []

        if self.cfg.combine_triplets:
            return self._group_triplets(above_indices, diff_db, on)
        else:
            # Если группировка отключена, возвращаем все точки
            return [self._make_signal(idx, diff_db, on) for idx in above_indices]

    def _group_triplets(self, indices: np.ndarray, diff_db: np.ndarray, on: Spectrum) -> List[PEMINSignal]:
        """
        Реализация алгоритма п. 6.2.2 РЭ:
        Из каждых трех СМЕЖНЫХ (по частоте/индексу) точек, превысивших порог, 
        в список попадает только одна с максимальной амплитудой.
        """
        signals = []
        if not indices.size:
            return signals

        # 1. Разбиваем линейный список индексов на группы смежных индексов
        # Например: [10, 11, 12, 15, 16] -> [[10,11,12], [15,16]]
        groups = []
        current_group = [indices[0]]
        
        for i in range(1, len(indices)):
            if indices[i] == indices[i-1] + 1:
                current_group.append(indices[i])
            else:
                groups.append(current_group)
                current_group = [indices[i]]
        groups.append(current_group)

        # 2. Обрабатываем каждую группу смежных точек
        for group in groups:
            # Внутри группы берем кусками по 3 точки
            for start in range(0, len(group), 3):
                chunk = group[start:start+3]
                if not chunk:
                    continue
                
                # Находим индекс с максимальной амплитудой в этой тройке
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
            spectrum_index=int(idx) # Сохраняем индекс для быстрой верификации
        )

    def verify_1(self, sig: PEMINSignal, new_on_db: float) -> bool:
        """
        Тест ВКЛ (п. 7.4 РЭ).
        Если избыток упал >50% от исходного -> помеха (сигнал нестабилен или внешний).
        Возвращает True, если сигнал СТАБИЛЕН (прошел тест).
        """
        orig_excess = sig.amplitude_on_db - sig.amplitude_off_db
        # Защита от деления на ноль или отрицательных значений, если шум скакнул
        if orig_excess <= 0:
            return False
            
        new_excess = new_on_db - sig.amplitude_off_db
        # Если новый избыток меньше 50% от старого -> FAIL
        return new_excess >= (self.cfg.verification_ratio * orig_excess)

    def verify_2(self, sig: PEMINSignal, new_off_db: float) -> bool:
        """
        Тест ВЫКЛ. Проверяем, что уровень шума в точке не вырос аномально.
        Если вырос > 3-6 дБ, считаем, что включилась помеха.
        """
        drift_limit = 6.0 # дБ
        return (new_off_db - sig.amplitude_off_db) < drift_limit